"""Append-only cross-Case narcotics intelligence; no operator data conversion."""
from alembic import op
import sqlalchemy as sa

revision = "20261013_01_narcotics_network_intelligence"
down_revision = "20261012_02_case_history"
branch_labels = None
depends_on = None

TABLES = (
    "narcotics_case_profiles", "narcotics_profile_substances", "narcotics_logistics_objects",
    "narcotics_profile_identifiers", "narcotics_mo_fingerprints", "narcotics_case_link_runs",
    "narcotics_case_links", "narcotics_link_reviews", "narcotics_nexus_runs", "narcotics_priority_runs",
)

def col(name, type, fk=None, nullable=False):
    return sa.Column(name, type, *([sa.ForeignKey(fk)] if fk else []), nullable=nullable)

def create(name, columns, indexed=(), unique=None):
    op.create_table(name, sa.Column("id", sa.String(36), primary_key=True), *columns,
                    *([sa.UniqueConstraint(*unique)] if unique else []))
    for field in indexed: op.create_index("ix_" + name + "_" + field, name, [field])

def upgrade():
    case = lambda: col("case_id", sa.String(36), "cases.id")
    record = lambda: col("record", sa.JSON())
    at = lambda: col("created_at", sa.String(40))
    profile = lambda: col("profile_id", sa.String(36), "narcotics_case_profiles.id")
    create(TABLES[0], [case(), col("revision", sa.Integer()), at(), record()], ("case_id",), ("case_id", "revision"))
    create(TABLES[1], [profile(), case(), col("category", sa.String(160), nullable=True), record()], ("profile_id",))
    create(TABLES[2], [profile(), case(), record()], ("profile_id",))
    create(TABLES[3], [profile(), col("kind", sa.String(40)), col("value", sa.String(300))], ("profile_id",))
    op.create_index("ix_narcotics_identifiers_lookup", TABLES[3], ["kind", "value"])
    for table in TABLES[4:6]: create(table, [case(), at(), record()], ("case_id",))
    create(TABLES[6], [col("run_id", sa.String(36), TABLES[5] + ".id"),
        col("case_a", sa.String(36), "cases.id"), col("case_b", sa.String(36), "cases.id"),
        col("link_type", sa.String(48)), col("strength", sa.String(16)), record()], ("run_id",))
    create(TABLES[7], [col("link_id", sa.String(36), TABLES[6] + ".id"), col("sequence", sa.Integer()),
        col("status", sa.String(16)), at(), record()], ("link_id",), ("link_id", "sequence"))
    create(TABLES[8], [at(), record()])
    create(TABLES[9], [col("nexus_id", sa.String(36), TABLES[8] + ".id"), at(), record()], ("nexus_id",))
    for table in TABLES:
        for operation in ("update", "delete"):
            op.execute(f"CREATE TRIGGER narc1_{table}_no_{operation} BEFORE {operation.upper()} ON {table} BEGIN SELECT RAISE(ABORT, 'Narcotics intelligence history is immutable'); END")
        op.execute(f"CREATE TRIGGER narc1_{table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS (SELECT 1 FROM {table} WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT, 'Narcotics intelligence history is immutable'); END")

def downgrade():
    connection = op.get_bind()
    if any(connection.execute(sa.text("SELECT 1 FROM " + table + " LIMIT 1")).first() for table in TABLES):
        raise RuntimeError("Retained narcotics intelligence history prevents downgrade")
    for table in reversed(TABLES):
        for operation in ("update", "delete", "replace"): op.execute(f"DROP TRIGGER narc1_{table}_no_{operation}")
        op.drop_table(table)
