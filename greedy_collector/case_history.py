"""Case-owned history, including pins created by existing analytical services."""
from sqlalchemy import DDL, event, inspect
from sqlalchemy.orm import Session
from fastapi.encoders import jsonable_encoder
from .models import Case, CaseEntity, AnalystNote, CaseEvent, CaseReport, SanctionsCasePin, utcnow, new_id

IMMUTABLE_TABLES = ("case_events", "case_reports", "case_entities", "sanctions_case_pins")
CASE_TRIGGER_SQL = {}
for table in IMMUTABLE_TABLES:
    for operation in ("update", "delete"):
        name = f"case2_{table}_no_{operation}"
        CASE_TRIGGER_SQL[name] = (
            f"CREATE TRIGGER {name} BEFORE {operation.upper()} ON {table} "
            "BEGIN SELECT RAISE(ABORT, 'Case history is immutable'); END"
        )
    name = f"case2_{table}_no_replace"
    CASE_TRIGGER_SQL[name] = (
        f"CREATE TRIGGER {name} BEFORE INSERT ON {table} "
        f"WHEN EXISTS (SELECT 1 FROM {table} WHERE id=NEW.id) "
        "BEGIN SELECT RAISE(ABORT, 'Case history is immutable'); END"
    )

def immutable(mapper, connection, target):
    raise ValueError("Case history is immutable")

for model in (CaseEvent, CaseReport, CaseEntity, SanctionsCasePin):
    event.listen(model, "before_update", immutable)
    event.listen(model, "before_delete", immutable)
    for name, sql in CASE_TRIGGER_SQL.items():
        if name.startswith(f"case2_{model.__tablename__}_"):
            event.listen(model.__table__, "after_create", DDL(sql).execute_if(dialect="sqlite"))

def snapshot(row):
    return jsonable_encoder({c.name: getattr(row, c.name) for c in row.__table__.columns})

@event.listens_for(Session, "before_flush")
def record_case_changes(session, flush_context, instances):
    # One transaction contains the original mutation, its history, and Case revision.
    now = utcnow()
    new_cases = {r.id: r for r in session.new if isinstance(r, Case) and r.id}
    changes = list(session.new) + [r for r in session.dirty if session.is_modified(r, include_collections=False)]
    for row in changes:
        if not isinstance(row, (Case, CaseEntity, AnalystNote, SanctionsCasePin, CaseReport)):
            continue
        is_new = row in session.new
        row.id = row.id or new_id()
        if isinstance(row, Case):
            if is_new:
                row.created_at = row.created_at or now
                row.updated_at = row.updated_at or now
                row.version = row.version or 1
                row.summary = row.summary or {}
                row.status = row.status or "Open"
                row.description = row.description or ""
                new_cases[row.id] = row
                kind = "case_created"
            else:
                history = inspect(row).attrs.archived_at.history
                kind = ("case_archived" if row.archived_at else "case_restored") if history.has_changes() else "case_updated"
                # Content-only updates are covered by their own event.
                if not any(inspect(row).attrs[k].history.has_changes() for k in ("title", "description", "summary", "status", "archived_at")):
                    continue
                row.updated_at = now
            case = row
        else:
            case = new_cases.get(row.case_id) or session.get(Case, row.case_id)
            if case is None:
                continue  # Let the FK report the missing Case.
            if isinstance(row, CaseEntity):
                row.added_at = row.added_at or now
                row.metadata_json = row.metadata_json or {}
                kind = row.entity_type + ("_added" if row.entity_type in ("wallet", "transaction", "label", "graph_snapshot", "attachment", "discovery_observation") else "_pinned")
            elif isinstance(row, AnalystNote):
                row.created_at = row.created_at or now
                row.updated_at = now
                row.version = row.version or 1
                row.author = row.author or "analyst"
                kind = "note_added" if is_new else ("note_archived" if row.archived_at else "note_restored") if inspect(row).attrs.archived_at.history.has_changes() else "note_updated"
            elif isinstance(row, SanctionsCasePin):
                row.captured_at = row.captured_at or now
                kind = "sanctions_pinned"
            else:
                kind = "report_generated"
            if not isinstance(row, CaseReport):
                case.updated_at = now
        record = snapshot(row) if not isinstance(row, CaseReport) else {
            "format": row.format, "sha256": row.sha256, "state_fingerprint": row.state_fingerprint}
        if isinstance(row, Case) and not is_new:
            record["version"] = row.version + 1
        if isinstance(row, AnalystNote) and not is_new:
            old = inspect(row).attrs.body.history.deleted
            record["previous_body"] = old[0] if old else row.body
            record["version"] = row.version + 1
        session.add(CaseEvent(case_id=case.id, kind=kind, reference_id=row.id, created_at=now, record=record))
