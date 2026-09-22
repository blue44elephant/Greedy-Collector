"""Explicit stored-observation promotion; one Attribution-owned transaction, no I/O."""
from sqlalchemy import inspect, select, text, func
from ..models import (DiscoveryPromotion as Promotion, DiscoveryObservation as Observation,
    DiscoveryResult as Result, DiscoveryReview as Review, DiscoveryRunSource as Source,
    DiscoverySubject as Subject, PROMOTION_TRIGGER_SQL)
from ..migration_state import supports_revision
from ..attribution.service import AttributionService, Evidence, Link, atomic, row_data, ACTOR
from ..attribution.domain import Conflict, AttributionError, EvidenceContentInput, LinkInput, fingerprint
from .service import DiscoveryService
from .domain import clean
from .registry import REGISTRY

REVISION = '20260915_01'


class PromotionUnavailable(AttributionError):
    pass


class PromotionService(AttributionService):
    def __init__(self, session, *, metadata_only=False, registry=None):
        connection = session.connection()
        view = inspect(connection)
        if 'discovery_promotions' not in view.get_table_names():
            raise PromotionUnavailable('Discovery promotion storage is not initialized for this database.')
        if {c['name'] for c in view.get_columns('discovery_promotions')} != set(Promotion.__table__.columns.keys()):
            raise PromotionUnavailable('Discovery promotion storage is not initialized for this database.')
        if not metadata_only and not supports_revision(connection, REVISION):
            raise PromotionUnavailable('Discovery promotion storage is not initialized for this database.')
        installed = dict(connection.execute(text("SELECT name,sql FROM sqlite_master WHERE type='trigger'")).all())
        norm = lambda sql: ' '.join(sql.strip().rstrip(';').split()).lower()
        if any(norm(installed.get(name,'')) != norm(sql) for name,sql in PROMOTION_TRIGGER_SQL.items()):
            raise PromotionUnavailable('Discovery promotion storage is not initialized for this database.')
        super().__init__(session, metadata_only=metadata_only)
        self.discovery = DiscoveryService(session, metadata_only=metadata_only, registry=registry)
        self.registry = registry or REGISTRY

    def _material(self, observation_id):
        observation = self.discovery._get(Observation, observation_id)
        result = self.discovery._get(Result, observation.result_id)
        source = self.discovery._get(Source, observation.execution_id)
        subject = self.discovery._get(Subject, result.query_subject_id)
        # Review authorization follows the selected immutable material, not a
        # result-wide Relevant badge covering different, newly returned content.
        review = self.db.scalar(select(Review).join(Observation, Review.observation_id == Observation.id).where(
            Review.result_id == result.id, Observation.content_sha256 == observation.content_sha256
        ).order_by(Review.sequence.desc()).limit(1))
        status = review.status if review else 'unreviewed'
        policy = self.registry.sources.get(source.source_id)
        transform = self.registry.transforms.get(source.transform_id)
        local = (source.transform_id, source.source_id, observation.kind, result.predicate) == (
            'wallet.local_labels','gc_labels','local_label_snapshot','locally_labeled_as')
        github = (source.transform_id, source.source_id, observation.kind, result.predicate) == (
            'wallet.public_code_mentions','github','code_search_result','repository_contains')
        from .ens import verified_material
        endpoint=self.db.get(Subject,result.from_subject_id) if result.predicate=='resolves_to' else None
        ens=verified_material(result,observation,source,subject,endpoint)
        from .manual_source import is_manual_material
        manual=is_manual_material(result,observation,source)
        from .graphsense import public_material
        endpoint=self.db.get(Subject,result.to_subject_id) if result.predicate=='publicly_labeled_as' else None
        public=public_material(result,observation,source,subject,endpoint)
        eligible_source = bool((local or github or ens or manual or public) and policy and transform and policy.storage_allowed
            and policy.retention_policy_id == source.retention_policy_id
            and (policy.version,transform.version) == (source.source_version,source.transform_version)
            and source.descriptor_snapshot.get('source',{}).get('storage_allowed')
            and subject.kind == 'blockchain_address')
        if local: eligible_source = eligible_source and bool(observation.origin_label_id)
        if github: eligible_source = eligible_source and observation.source_snapshot.get('public') is True
        eligible = bool(eligible_source and status == 'relevant')
        reason = None if eligible else ('source_not_promotable' if not eligible_source else 'review_required')
        observation_values = row_data(observation)
        snapshot = {
            'schema_version':1, 'source_subsystem':'Greedy Collector Discovery',
            'discovery_result_id':result.id, 'discovery_observation_id':observation.id,
            'observation_fingerprint':observation.content_sha256,
            'subject':{'chain':subject.namespace,'address':subject.canonical_value},
            'predicate':result.predicate, 'candidate_kind':result.kind,
            'fact_key':result.fact_key, 'run_id':source.run_id, 'execution_id':source.id,
            'transform_id':source.transform_id, 'transform_version':source.transform_version,
            'source_id':source.source_id, 'source_version':source.source_version,
            'coverage':source.coverage, 'provider_total':source.provider_total,
            'observation':observation_values,
        }
        if manual or public:
            # A manual capture repeats its quoted context in the observation
            # excerpt and source snapshot. Sanitize each bounded component;
            # the Attribution model owns the composite metadata's 32 KiB cap.
            selected=snapshot.pop('observation')
            snapshot={**clean(snapshot),'observation':clean(selected)}
        else:snapshot=clean(snapshot)
        evidence_fields = dict(
            evidence_type='discovery_snapshot',
            title='GC Discovery - Local Label' if local else 'GC Discovery - ENS primary name' if ens else 'GC Discovery - Manual source observation' if manual else 'GC Discovery - GraphSense public tag' if public else 'GC Discovery - GitHub code mention',
            summary=observation.summary, excerpt=observation.excerpt,
            source_name='Greedy Collector Label via Discovery' if local else 'ENS / Ethereum via Discovery' if ens else 'Manual analyst capture via Discovery' if manual else 'GraphSense public TagPacks via Discovery' if public else 'GitHub via Discovery',
            source_url=observation.source_url, source_locator='discovery-observation:'+observation.id,
            source_catalog_id=source.source_id, origin='analyst_added' if local or manual else 'public_osint',
            observed_on=observation.observed_on or (observation.observed_at.date() if observation.observed_at else None),
            published_on=observation.published_on or (observation.published_at.date() if observation.published_at else None),
        )
        values = EvidenceContentInput.model_validate(
            {**clean(evidence_fields),'metadata_json':snapshot} if manual or public
            else clean({**evidence_fields,'metadata_json':snapshot})
        ).model_dump()
        values.update(collection_method='discovery_snapshot',origin_label_id=None,origin_match_id=None,
                      origin_discovery_observation_id=observation.id)
        # Unverified code context is retained only as context. Exact code excerpts
        # allow explicit analyst interpretation; exactness supplies no stance.
        context_only = github and observation.verification not in ('exact_in_excerpt','exact_in_document')
        source_fingerprint = fingerprint({'policy_version':1, 'capture':values,
            'review_id':review.id if review else None, 'eligible':eligible,
            'context_only':context_only, 'retention_policy':policy.retention_policy_id if policy else None})
        return dict(observation_id=observation.id,result_id=result.id,
            observation_fingerprint=observation.content_sha256,source_fingerprint=source_fingerprint,
            review_status=status,review_id=review.id if review else None,eligible=eligible,reason=reason,
            context_only=context_only,chain=subject.namespace,address=subject.canonical_value,
            evidence=values)

    def preview(self, observation_id):
        return self._material(observation_id)

    @atomic
    def promote(self, observation_id, payload):
        from .promotion_schemas import PromotionInput
        data = PromotionInput.model_validate(payload)
        # Duplicate identity is permanent, including withdrawn/replaced links.
        prior = self.db.scalar(select(Promotion).where(Promotion.observation_id == observation_id,
                                                      Promotion.claim_id == data.claim_id))
        if prior:
            raise Conflict('This observation is already promoted to this claim; inspect its retained link', prior.id)
        preview = self._material(observation_id)
        if data.result_id != preview['result_id']:
            raise AttributionError('The selected observation does not belong to this result')
        if data.expected_source_fingerprint != preview['source_fingerprint']:
            raise Conflict('Promotion preview changed; review the selected observation again')
        if not preview['eligible']:
            raise AttributionError('The selected material requires a Relevant review and an eligible source')
        claim = self._claim(data.claim_id)
        if claim.version != data.expected_claim_version:
            raise Conflict('Attribution version changed; reload before writing')
        if (claim.chain,claim.subject_ref) != (preview['chain'],preview['address']):
            raise AttributionError('Choose a claim for this exact wallet and chain')
        link = LinkInput.model_validate(data.link.model_dump()).model_dump()
        if preview['context_only'] and (link['stance'],link['directness']) != ('context','context'):
            raise AttributionError('Unverified search material can only provide contextual evidence')
        values = preview['evidence']
        digest = fingerprint(values)
        evidence = self.db.scalar(select(Evidence).where(Evidence.content_sha256 == digest,
            Evidence.origin_discovery_observation_id == observation_id).order_by(Evidence.id).limit(1))
        if evidence is None:
            evidence = Evidence(**values,captured_by=ACTOR,content_sha256=digest)
            self.db.add(evidence); self.db.flush()
            self._event(evidence,'created','Reviewed Discovery observation explicitly captured')
        linked = self._link(claim,evidence.id,link,data.expected_claim_version)
        promotion = Promotion(observation_id=observation_id,claim_id=claim.id,evidence_id=evidence.id,
            link_id=linked['link']['id'],source_fingerprint=preview['source_fingerprint'],capture_fingerprint=digest,
            claim_version_before=data.expected_claim_version,claim_version_after=linked['claim']['version'])
        self.db.add(promotion); self.db.flush()
        return {'promotion':self._read_promotion(promotion,linked['link']), 'claim':linked['claim']}

    def _read_promotion(self, row, link):
        return {**row_data(row),'stance':link['stance'],'directness':link['directness'],
                'rationale':link['rationale'],'withdrawn_at':link['withdrawn_at']}

    def history(self, result_id, *, limit=20, offset=0):
        self.discovery._get(Result,result_id)
        if type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0:
            raise AttributionError('Invalid page bounds')
        query = select(Promotion,Link).join(Observation,Promotion.observation_id == Observation.id).join(
            Link,Promotion.link_id == Link.id).where(Observation.result_id == result_id)
        total = self.db.scalar(select(func.count()).select_from(query.subquery()))
        rows = self.db.execute(query.order_by(Promotion.created_at,Promotion.id).offset(offset).limit(limit)).all()
        return {'items':[self._read_promotion(p,row_data(l)) for p,l in rows], 'total':total,
            'limit':limit,'offset':offset,'next_offset':offset+limit if offset+limit < total else None}
