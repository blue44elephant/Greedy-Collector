"""CASE-2 versioned Case edits and immutable report/event storage.

Frozen migration. No source collection, user database access, or runtime models.
"""
from alembic import op
import sqlalchemy as sa

revision = "20261012_02_case_history"
down_revision = "20261012_01_risk_labels_v3"
branch_labels = None
depends_on = None

def upgrade():
    op.add_column("cases", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("cases", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("cases", sa.Column("summary", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("case_entities", sa.Column("added_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("analyst_notes", sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("analyst_notes", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("analyst_notes", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE analyst_notes SET updated_at=created_at")
    op.create_table("case_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("kind", sa.String(64), nullable=False),
        sa.Column("reference_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("record", sa.JSON(), nullable=False))
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"])
    op.create_table("case_reports",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), sa.ForeignKey("cases.id"), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("state_fingerprint", sa.String(64), nullable=False),
        sa.Column("generator_version", sa.String(32), nullable=False),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("state", sa.JSON(), nullable=False),
        sa.Column("content", sa.LargeBinary(), nullable=False))
    op.create_index("ix_case_reports_case_id", "case_reports", ["case_id"])
    op.execute("""INSERT INTO case_events (id,case_id,kind,reference_id,created_at,record)
        SELECT id,id,'case_created',id,created_at,'{"imported_before_case2": true}' FROM cases""")
    for table in ("case_events", "case_reports", "case_entities", "sanctions_case_pins"):
        for operation in ("update", "delete"):
            op.execute(f"CREATE TRIGGER case2_{table}_no_{operation} BEFORE {operation.upper()} ON {table} BEGIN SELECT RAISE(ABORT, 'Case history is immutable'); END")
        op.execute(f"CREATE TRIGGER case2_{table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT, 'Case history is immutable'); END")

def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM case_reports LIMIT 1")).first():
        raise RuntimeError("Retained immutable report history prevents downgrade")
    if connection.execute(sa.text("SELECT 1 FROM case_events WHERE kind != 'case_created' LIMIT 1")).first():
        raise RuntimeError("Retained Case history prevents downgrade")
    for table in ("case_events", "case_reports", "case_entities", "sanctions_case_pins"):
        for operation in ("update", "delete", "replace"):
            op.execute(f"DROP TRIGGER case2_{table}_no_{operation}")
    op.drop_table("case_reports")
    op.drop_table("case_events")
    for table, columns in (("analyst_notes", ("version", "updated_at", "archived_at")),
                           ("case_entities", ("added_at",)),
                           ("cases", ("version", "archived_at", "summary"))):
        for column in columns:
            op.drop_column(table, column)
