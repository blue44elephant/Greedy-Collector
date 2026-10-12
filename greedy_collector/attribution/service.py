"""Explicit local AT-1 commands. Each mutation owns a dedicated Session transaction."""
from functools import wraps
from ..chain_types import supported_chain

from pydantic import ValidationError

from sqlalchemy import exists, func, inspect, or_, select, text, update
from sqlalchemy.exc import IntegrityError, OperationalError

from ..models import (AttributionEntity as Entity, AttributionClaim as Claim,
                      AttributionEvidence as Evidence, AttributionClaimEvidence as Link,
                      AttributionEvent as Event, ATTRIBUTION_TRIGGER_SQL, utcnow)
from ..kyc.presentation import sanitize_research
from ..migration_state import migration_scripts, supports_revision
from .domain import (AttributionError, Conflict, NotFound, SchemaUnavailable,
                     EntityInput, ClaimInput, ScopeInput, EvidenceInput, LinkInput,
                     choice, fingerprint, json_safe, name_key, normalize_subject, reason_text)
from .enums import ASSESSMENTS, ENTITY_TYPES, RELATIONSHIPS, STANCES

REVISION = "20260912_01"
ACTOR = "local_analyst"  # Unauthenticated local operator, not a verified person.
TABLES = (Entity.__tablename__, Claim.__tablename__, Evidence.__tablename__, Link.__tablename__, Event.__tablename__)


def row_data(row):
    return json_safe({column.name: (None if column.name == "origin_discovery_observation_id" and row.collection_method != "discovery_snapshot" else getattr(row, column.name)) for column in row.__table__.columns})


def atomic(method):
    @wraps(method)
    def command(self, *args, **kwargs):
        if self.db.new or self.db.dirty or self.db.deleted:
            raise AttributionError("Use a dedicated clean Session for attribution commands")
        try:
            connection = self.db.connection()
            # Serialize SQLite writers before parent-state checks; stale versions still fail.
            if not connection.connection.driver_connection.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
            result = method(self, *args, **kwargs)
            self.db.flush()
            self.db.commit()
            return result
        except IntegrityError:
            self.db.rollback()
            raise Conflict("Attribution constraint conflict; refresh the local records") from None
        except ValidationError:
            self.db.rollback()
            raise AttributionError("Invalid attribution input; check fields and provenance requirements") from None
        except OperationalError:
            self.db.rollback()
            raise Conflict("Attribution storage is unavailable or busy; reload and retry") from None
        except Exception:
            self.db.rollback()
            raise
    return command


class AttributionService:
    def __init__(self, session, *, metadata_only=False):
        self.db = session
        connection = session.connection()
        if connection.dialect.name != "sqlite":
            raise SchemaUnavailable("AT-1 currently requires SQLite")
        existing = set(inspect(connection).get_table_names())
        if not set(TABLES) <= existing:
            raise SchemaUnavailable("Attribution requires alembic upgrade head")
        for model in (Entity, Claim, Evidence, Link, Event):
            actual = {column['name'] for column in inspect(connection).get_columns(model.__tablename__)}
            expected = set(model.__table__.columns.keys())
            if model is Evidence and "origin_discovery_observation_id" not in actual and not supports_revision(connection, "20260915_01"):
                expected.remove("origin_discovery_observation_id")
            if actual != expected:
                raise SchemaUnavailable("Attribution schema columns are incompatible; migrate before use")
        installed = dict(connection.execute(text("SELECT name, sql FROM sqlite_master WHERE type='trigger'")).all())
        normalize = lambda sql: " ".join(sql.strip().rstrip(";").split()).lower()
        if any(normalize(installed.get(name, "")) != normalize(sql) for name, sql in ATTRIBUTION_TRIGGER_SQL.items()):
            raise SchemaUnavailable("Attribution immutability triggers are missing or incompatible")
        if connection.exec_driver_sql("PRAGMA foreign_keys").scalar_one() != 1:
            raise SchemaUnavailable("Attribution requires SQLite foreign-key enforcement")
        if not metadata_only:
            if not supports_revision(connection, REVISION, scripts=migration_scripts()):
                raise SchemaUnavailable("Attribution migration revision is required; do not blindly stamp an existing database")

    def _get(self, model, identifier):
        row = self.db.get(model, identifier, populate_existing=True)
        if row is None:
            raise NotFound("Attribution record not found")
        return row

    def _entity(self, identifier, active=True):
        row = self._get(Entity, identifier)
        if active and row.archived_at:
            raise Conflict("Entity is archived")
        return row

    def _claim(self, identifier, active=True):
        row = self._get(Claim, identifier)
        if active:
            if row.archived_at:
                raise Conflict("Claim is archived")
            self._entity(row.entity_id)
        return row

    def _event(self, row, kind, reason, before=None, after=None, extra=None, system=False):
        target = "entity_id" if isinstance(row, Entity) else "claim_id" if isinstance(row, Claim) else "evidence_id"
        payload = {"schema_version": 1, "before": before, "after": after if after is not None else row_data(row)}
        if extra:
            payload.update(json_safe(extra))
        event = Event(**{target: row.id}, sequence=getattr(row, "version", 1), event_type=kind,
                      actor_kind="system" if system else "analyst", actor_ref=ACTOR if not system else "attribution.review_invalidation",
                      reason=reason_text(reason), payload=json_safe(payload))
        self.db.add(event)
        self.db.flush()

    def _change(self, row, expected_version, values):
        if type(expected_version) is not int or expected_version < 1:
            raise AttributionError("A positive expected_version is required")
        before = row_data(row)
        model = type(row)
        result = self.db.execute(update(model).where(model.id == row.id, model.version == expected_version)
                                 .values(**values, version=expected_version + 1, updated_at=utcnow())
                                 .execution_options(synchronize_session=False))
        if result.rowcount != 1:
            raise Conflict("Attribution version changed; reload before writing")
        self.db.expire(row)
        return before

    def _page(self, model, query, *, limit=50, offset=0):
        if type(limit) is not int or not 1 <= limit <= 200 or type(offset) is not int or offset < 0:
            raise AttributionError("Invalid page bounds")
        # A Core subquery includes even deferred ORM columns. Count identities
        # so legacy evidence lists do not read the ED-6-only origin column.
        identities = query.with_only_columns(model.id, maintain_column_froms=True).order_by(None)
        total = self.db.scalar(select(func.count()).select_from(identities.subquery()))
        rows = self.db.scalars(query.limit(limit).offset(offset)).all()
        return {"items": [row_data(row) for row in rows], "total": total,
                "next_offset": offset + len(rows) if offset + len(rows) < total else None}

    @atomic
    def create_entity(self, payload):
        values = sanitize_research(EntityInput.model_validate(payload).model_dump())
        row = Entity(**values, name_key=name_key(values["canonical_name"]), created_by=ACTOR)
        self.db.add(row); self.db.flush()
        self._event(row, "created", "Entity explicitly created by local analyst")
        return row_data(row)

    def get_entity(self, identifier):
        return row_data(self._get(Entity, identifier))

    def list_entities(self, *, search=None, entity_type=None, include_archived=False, limit=50, offset=0):
        query = select(Entity)
        if not include_archived: query = query.where(Entity.archived_at.is_(None))
        if entity_type: query = query.where(Entity.entity_type == choice(entity_type, ENTITY_TYPES))
        if search:
            key = name_key(search)
            # Aliases keep their literal spelling. Normalize only at query time,
            # using the same Unicode rules as canonical names and no merge logic.
            self.db.connection().connection.driver_connection.create_function(
                'gc_attribution_name_key', 1, name_key, deterministic=True)
            aliases = func.json_each(Entity.aliases).table_valued('value').alias()
            alias_match = exists(select(1).select_from(aliases).where(
                func.gc_attribution_name_key(aliases.c.value).contains(key, autoescape=True)))
            query = query.where(or_(Entity.name_key.contains(key, autoescape=True), alias_match))
        return self._page(Entity, query.order_by(Entity.created_at, Entity.id), limit=limit, offset=offset)

    @atomic
    def update_entity(self, identifier, payload, *, expected_version, reason):
        row = self._entity(identifier)
        values = sanitize_research(EntityInput.model_validate(payload).model_dump())
        values["name_key"] = name_key(values["canonical_name"])
        before = self._change(row, expected_version, values)
        self._event(row, "descriptor_changed", reason, before)
        for claim in self.db.scalars(select(Claim).where(Claim.entity_id == row.id).order_by(Claim.id)).all():
            previous = self._change(claim, claim.version, {"needs_review": True})
            self._event(claim, "review_required", reason, previous, extra={"entity_version": row.version}, system=True)
        return row_data(row)

    @atomic
    def archive_entity(self, identifier, *, expected_version, reason, restore=False):
        row = self._entity(identifier, active=False)
        if bool(row.archived_at) != bool(restore): raise Conflict("Entity already has the requested archive state")
        before = self._change(row, expected_version, {"archived_at": None if restore else utcnow()})
        self._event(row, "restored" if restore else "archived", reason, before)
        if restore:
            for claim in self.db.scalars(select(Claim).where(Claim.entity_id == row.id).order_by(Claim.id)).all():
                previous = self._change(claim, claim.version, {"needs_review": True})
                self._event(claim, "review_required", reason, previous, system=True)
        return row_data(row)

    @atomic
    def create_claim(self, payload):
        values = ClaimInput.model_validate(payload).model_dump()
        self._entity(values["entity_id"])
        key = ("subject_type", "chain", "subject_ref", "relationship", "entity_id")
        existing = self.db.scalar(select(Claim).where(*(getattr(Claim, field) == values[field] for field in key)))
        if existing: raise Conflict("This attribution claim already exists", existing.id)
        values["scope_note"] = sanitize_research(values["scope_note"])
        row = Claim(**values, created_by=ACTOR)
        self.db.add(row); self.db.flush()
        self._event(row, "created", "Unassessed claim explicitly created by local analyst")
        return row_data(row)

    def get_claim(self, identifier):
        row = self._claim(identifier, active=False)
        result = row_data(row)
        result["entity_archived"] = self._entity(row.entity_id, active=False).archived_at is not None
        return result

    def list_claims(self, *, chain=None, subject_ref=None, entity_id=None, relationship=None, assessment=None,
                    needs_review=None, include_archived=False, limit=50, offset=0):
        query = select(Claim).join(Entity, Entity.id == Claim.entity_id)
        if not include_archived: query = query.where(Claim.archived_at.is_(None), Entity.archived_at.is_(None))
        if chain: query = query.where(Claim.chain == supported_chain(chain))
        if subject_ref:
            if not chain: raise AttributionError("Subject filters require a chain")
            query = query.where(Claim.subject_ref == normalize_subject(chain, subject_ref))
        if entity_id: query = query.where(Claim.entity_id == entity_id)
        if relationship: query = query.where(Claim.relationship == choice(relationship, RELATIONSHIPS))
        if assessment: query = query.where(Claim.assessment == choice(assessment, ASSESSMENTS))
        if needs_review is not None: query = query.where(Claim.needs_review == needs_review)
        return self._page(Claim, query.order_by(Claim.created_at, Claim.id), limit=limit, offset=offset)

    @atomic
    def update_claim_scope(self, identifier, payload, *, expected_version, reason):
        row = self._claim(identifier)
        values = ScopeInput.model_validate(payload).model_dump()
        values["scope_note"] = sanitize_research(values["scope_note"])
        before = self._change(row, expected_version, {**values, "needs_review": True})
        self._event(row, "scope_changed", reason, before)
        return row_data(row)

    @atomic
    def archive_claim(self, identifier, *, expected_version, reason, restore=False):
        row = self._claim(identifier, active=False)
        if restore: self._entity(row.entity_id)
        if bool(row.archived_at) != bool(restore): raise Conflict("Claim already has the requested archive state")
        values = {"archived_at": None if restore else utcnow()}
        if restore: values["needs_review"] = True
        before = self._change(row, expected_version, values)
        self._event(row, "restored" if restore else "archived", reason, before)
        return row_data(row)

    def _capture(self, payload):
        values = EvidenceInput.model_validate(payload).model_dump()
        values = sanitize_research(values)
        values.update(collection_method="analyst_entry", origin_label_id=None, origin_match_id=None)
        row = Evidence(**values, captured_by=ACTOR, content_sha256=fingerprint(values))
        self.db.add(row); self.db.flush()
        self._event(row, "created", "Immutable analyst-entered evidence captured")
        return row

    @atomic
    def create_evidence(self, payload):
        return row_data(self._capture(payload))

    def get_evidence(self, identifier):
        return row_data(self._get(Evidence, identifier))

    def list_evidence(self, *, source_catalog_id=None, origin=None, limit=50, offset=0):
        query = select(Evidence)
        if source_catalog_id: query = query.where(Evidence.source_catalog_id == source_catalog_id)
        if origin: query = query.where(Evidence.origin == choice(origin, ("public_osint", "analyst_added", "commercial_proprietary", "privileged_nonpublic")))
        return self._page(Evidence, query.order_by(Evidence.captured_at, Evidence.id), limit=limit, offset=offset)

    def _link(self, claim, evidence_id, payload, expected_version):
        values = sanitize_research(LinkInput.model_validate(payload).model_dump())
        self._get(Evidence, evidence_id)
        existing = self.db.scalar(select(Link).where(Link.claim_id == claim.id, Link.evidence_id == evidence_id))
        if existing: raise Conflict("Evidence is already linked; restore a withdrawn link explicitly", existing.id)
        before = self._change(claim, expected_version, {"needs_review": True})
        link = Link(claim_id=claim.id, evidence_id=evidence_id, **values, added_by=ACTOR)
        self.db.add(link); self.db.flush()
        self._event(claim, "evidence_linked", values["rationale"], before, extra={"link_before": None, "link_after": row_data(link)})
        return {"claim": row_data(claim), "link": row_data(link)}

    @atomic
    def link_evidence(self, claim_id, evidence_id, payload, *, expected_version):
        return self._link(self._claim(claim_id), evidence_id, payload, expected_version)

    @atomic
    def create_and_link_evidence(self, claim_id, evidence_payload, link_payload, *, expected_version):
        claim = self._claim(claim_id)
        evidence = self._capture(evidence_payload)
        return self._link(claim, evidence.id, link_payload, expected_version)

    def list_claim_evidence(self, claim_id, *, include_withdrawn=False, stance=None, limit=50, offset=0):
        self._claim(claim_id, active=False)
        query = select(Link).where(Link.claim_id == claim_id)
        if not include_withdrawn: query = query.where(Link.withdrawn_at.is_(None))
        if stance: query = query.where(Link.stance == choice(stance, STANCES))
        return self._page(Link, query.order_by(Link.added_at, Link.id), limit=limit, offset=offset)

    @atomic
    def update_evidence_link(self, claim_id, link_id, payload, *, expected_version, reason):
        claim = self._claim(claim_id); link = self._get(Link, link_id)
        if link.claim_id != claim.id: raise NotFound("Claim evidence link not found")
        if link.withdrawn_at: raise Conflict("Restore the evidence link before editing relevance")
        values = sanitize_research(LinkInput.model_validate(payload).model_dump())
        before = self._change(claim, expected_version, {"needs_review": True})
        old_link = row_data(link)
        for field, value in values.items(): setattr(link, field, value)
        link.updated_at = utcnow(); self.db.flush()
        self._event(claim, "evidence_changed", reason, before, extra={"link_before": old_link, "link_after": row_data(link)})
        return {"claim": row_data(claim), "link": row_data(link)}

    @atomic
    def withdraw_evidence(self, claim_id, link_id, *, expected_version, reason, restore=False):
        claim = self._claim(claim_id); link = self._get(Link, link_id)
        if link.claim_id != claim.id: raise NotFound("Claim evidence link not found")
        if bool(link.withdrawn_at) != bool(restore): raise Conflict("Link already has the requested withdrawal state")
        before = self._change(claim, expected_version, {"needs_review": True})
        old_link = row_data(link)
        link.withdrawn_at = None if restore else utcnow(); link.updated_at = utcnow(); self.db.flush()
        self._event(claim, "evidence_restored" if restore else "evidence_withdrawn", reason, before,
                    extra={"link_before": old_link, "link_after": row_data(link)})
        return {"claim": row_data(claim), "link": row_data(link)}

    @atomic
    def replace_evidence(self, claim_id, link_id, evidence_payload, link_payload, *, expected_version, reason):
        claim = self._claim(claim_id); old_link = self._get(Link, link_id)
        if old_link.claim_id != claim.id: raise NotFound("Claim evidence link not found")
        if old_link.withdrawn_at: raise Conflict("Evidence link is already withdrawn")
        values = sanitize_research(LinkInput.model_validate(link_payload).model_dump())
        evidence = self._capture(evidence_payload)
        before = self._change(claim, expected_version, {"needs_review": True})
        old = row_data(old_link)
        old_link.withdrawn_at = utcnow(); old_link.updated_at = utcnow()
        link = Link(claim_id=claim.id, evidence_id=evidence.id, **values, added_by=ACTOR)
        self.db.add(link); self.db.flush()
        self._event(claim, "evidence_changed", reason, before,
                    extra={"link_before": old, "withdrawn_link": row_data(old_link), "link_after": row_data(link)})
        return {"claim": row_data(claim), "link": row_data(link), "withdrawn_link": row_data(old_link)}

    @atomic
    def change_assessment(self, claim_id, assessment, rationale, *, expected_version, reviewed_link_ids,
                          acknowledged_contradictions, conflict_discussion="", source_verification=""):
        claim = self._claim(claim_id)
        choice(assessment, ASSESSMENTS)
        rationale = reason_text(rationale)
        links = self.db.scalars(select(Link).where(Link.claim_id == claim.id, Link.withdrawn_at.is_(None)).order_by(Link.id)).all()
        active = {link.id for link in links}
        contradictions = {link.id for link in links if link.stance == "contradicts"}
        if len(reviewed_link_ids) != len(set(reviewed_link_ids)) or set(reviewed_link_ids) != active:
            raise Conflict("Review every current active evidence link before assessment")
        if len(acknowledged_contradictions) != len(set(acknowledged_contradictions)) or set(acknowledged_contradictions) != contradictions:
            raise AttributionError("Explicitly acknowledge every contradicting evidence link")
        if contradictions: rationale += "\nConflicts: " + reason_text(conflict_discussion)
        supporting = [link for link in links if link.stance == "supports"]
        if assessment in ("possible", "supported", "strongly_supported") and not supporting:
            raise AttributionError("This assessment requires active supporting evidence")
        direct = [self._get(Evidence, link.evidence_id) for link in supporting if link.directness == "direct"]
        if assessment in ("supported", "strongly_supported") and not any(row.source_reliability != "unassessed" for row in direct):
            raise AttributionError("Supported assessments require direct support with assessed source reliability")
        if assessment == "strongly_supported":
            if not any(row.source_reliability == "reliable" for row in direct):
                raise AttributionError("Strong support requires reliable direct evidence")
            rationale += "\nSource verification: " + reason_text(source_verification)
        rationale = reason_text(rationale)
        before = self._change(claim, expected_version, {"assessment": assessment, "assessment_rationale": rationale,
                              "assessed_at": utcnow(), "assessed_by": ACTOR, "needs_review": False})
        entity = self._entity(claim.entity_id)
        self._event(claim, "assessment_changed", rationale, before,
                    extra={"reviewed_links": [row_data(link) for link in links], "entity_version": entity.version})
        return row_data(claim)

    def event_history(self, *, claim_id=None, entity_id=None, evidence_id=None, after_sequence=0, limit=50):
        targets = [(Claim, "claim_id", claim_id), (Entity, "entity_id", entity_id), (Evidence, "evidence_id", evidence_id)]
        selected = [(model, field, identifier) for model, field, identifier in targets if identifier is not None]
        if len(selected) != 1: raise AttributionError("Choose exactly one event scope")
        if type(after_sequence) is not int or after_sequence < 0: raise AttributionError("Invalid event cursor")
        model, field, identifier = selected[0]; self._get(model, identifier)
        query = select(Event).where(getattr(Event, field) == identifier, Event.sequence > after_sequence).order_by(Event.sequence)
        result = self._page(Event, query, limit=limit)
        result["next_sequence"] = result["items"][-1]["sequence"] if result.pop("next_offset") is not None else None
        return result


    def claim_evidence_details(self, claim_id, **filters):
        """Bounded link page with one batched capture-summary query for HTTP views."""
        result = self.list_claim_evidence(claim_id, **filters)
        identifiers = [item['evidence_id'] for item in result['items']]
        evidence = {row.id: row_data(row) for row in self.db.scalars(
            select(Evidence).where(Evidence.id.in_(identifiers))).all()} if identifiers else {}
        fields = ('id', 'title', 'evidence_type', 'source_name', 'source_url',
                  'source_locator', 'origin', 'source_reliability', 'captured_at')
        for item in result['items']:
            item['evidence'] = {key: evidence[item['evidence_id']][key] for key in fields}
        return result

    def claim_detail(self, claim_id):
        """Current proposition, entity and bounded evidence; history stays separate."""
        result = self.get_claim(claim_id)
        result['entity'] = self.get_entity(result['entity_id'])
        counts = dict(self.db.execute(select(Link.stance, func.count()).where(
            Link.claim_id == claim_id, Link.withdrawn_at.is_(None)).group_by(Link.stance)).all())
        result['active_evidence_counts'] = {stance: counts.get(stance, 0) for stance in STANCES}
        result['active_evidence'] = {**self.claim_evidence_details(claim_id), 'limit': 50, 'offset': 0}
        return result

    def event_page(self, *, claim_id=None, entity_id=None, evidence_id=None, limit=50, offset=0):
        """HTTP offset pagination with total across the entire selected stream.

        The AT-1 sequence-cursor method remains available with its original semantics.
        """
        targets = [(Claim, 'claim_id', claim_id), (Entity, 'entity_id', entity_id),
                   (Evidence, 'evidence_id', evidence_id)]
        selected = [(model, field, identifier) for model, field, identifier in targets if identifier is not None]
        if len(selected) != 1:
            raise AttributionError('Choose exactly one event scope')
        model, field, identifier = selected[0]
        self._get(model, identifier)
        query = select(Event).where(getattr(Event, field) == identifier).order_by(Event.sequence)
        return self._page(Event, query, limit=limit, offset=offset)
