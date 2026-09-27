"""Immutable technical cluster versions; explicit migration only."""
import sqlalchemy as sa
from alembic import op

revision = "20260927_01"
down_revision = "20260923_02"
branch_labels = None
depends_on = None

FROZEN = ("technical_cluster_versions", "technical_cluster_members", "technical_cluster_evidence",
          "technical_cluster_exclusions", "technical_cluster_evidence_links")

def upgrade():
    op.create_table("technical_clusters", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("chain", sa.String(32), nullable=False), sa.Column("current_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.String(40), nullable=False), sa.CheckConstraint("chain IN ('bitcoin','litecoin')", name="ck_technical_chain"))
    op.create_index("ix_technical_clusters_chain", "technical_clusters", ["chain"])
    op.create_table("technical_cluster_versions", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("cluster_id", sa.String(36), sa.ForeignKey("technical_clusters.id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False), sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("cluster_id", "number"))
    op.create_table("technical_cluster_members",
        sa.Column("version_id", sa.String(36), sa.ForeignKey("technical_cluster_versions.id"), primary_key=True),
        sa.Column("address", sa.String(128), primary_key=True), sa.Column("chain", sa.String(32), nullable=False))
    op.create_index("ix_technical_member_lookup", "technical_cluster_members", ["chain", "address"])
    op.create_table("technical_cluster_evidence", sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("chain", sa.String(32), nullable=False), sa.Column("tx_hash", sa.String(128), nullable=False),
        sa.Column("material", sa.JSON(), nullable=False), sa.Column("created_at", sa.String(40), nullable=False))
    op.create_index("ix_technical_evidence_transaction", "technical_cluster_evidence", ["chain", "tx_hash"])
    op.create_table("technical_cluster_exclusions", sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("evidence_id", sa.String(64), sa.ForeignKey("technical_cluster_evidence.id"), nullable=False),
        sa.Column("chain", sa.String(32), nullable=False), sa.Column("tx_hash", sa.String(128), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False), sa.Column("created_at", sa.String(40), nullable=False),
        sa.UniqueConstraint("chain", "tx_hash"), sa.CheckConstraint("length(trim(reason)) > 0", name="ck_technical_exclusion_reason"))
    op.create_table("technical_cluster_evidence_links",
        sa.Column("version_id", sa.String(36), sa.ForeignKey("technical_cluster_versions.id"), primary_key=True),
        sa.Column("evidence_id", sa.String(64), sa.ForeignKey("technical_cluster_evidence.id"), primary_key=True))
    for table in FROZEN:
        for operation in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT, 'Technical cluster history is immutable'); END")
    op.execute("CREATE TRIGGER technical_cluster_identity BEFORE UPDATE ON technical_clusters WHEN NEW.id != OLD.id OR NEW.chain != OLD.chain OR NEW.created_at != OLD.created_at BEGIN SELECT RAISE(ABORT, 'Cluster identity is immutable'); END")
    op.execute("CREATE TRIGGER technical_case_pin_no_update BEFORE UPDATE ON case_entities WHEN OLD.entity_type = 'technical_cluster' BEGIN SELECT RAISE(ABORT, 'Technical cluster case pin is immutable'); END")
    op.execute("CREATE TRIGGER technical_member_chain BEFORE INSERT ON technical_cluster_members WHEN NEW.chain != (SELECT c.chain FROM technical_clusters c JOIN technical_cluster_versions v ON v.cluster_id=c.id WHERE v.id=NEW.version_id) BEGIN SELECT RAISE(ABORT, 'Cluster member chain mismatch'); END")
    op.execute("CREATE TRIGGER technical_evidence_chain BEFORE INSERT ON technical_cluster_evidence_links WHEN (SELECT e.chain FROM technical_cluster_evidence e WHERE e.id=NEW.evidence_id) != (SELECT c.chain FROM technical_clusters c JOIN technical_cluster_versions v ON v.cluster_id=c.id WHERE v.id=NEW.version_id) BEGIN SELECT RAISE(ABORT, 'Cluster evidence chain mismatch'); END")

def downgrade():
    bind = op.get_bind()
    for table in ("technical_clusters",) + FROZEN:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Refusing to discard retained technical cluster material")
    if bind.execute(sa.text("SELECT 1 FROM case_entities WHERE entity_type='technical_cluster' LIMIT 1")).first():
        raise RuntimeError("Refusing to discard pinned cluster material")
    for trigger in ("technical_cluster_identity", "technical_case_pin_no_update", "technical_member_chain", "technical_evidence_chain"):
        op.execute(f"DROP TRIGGER {trigger}")
    for table in FROZEN:
        for operation in ("update", "delete"):
            op.execute(f"DROP TRIGGER {table}_no_{operation}")
    for table in ("technical_cluster_evidence_links", "technical_cluster_exclusions", "technical_cluster_members", "technical_cluster_versions", "technical_cluster_evidence", "technical_clusters"):
        op.drop_table(table)
