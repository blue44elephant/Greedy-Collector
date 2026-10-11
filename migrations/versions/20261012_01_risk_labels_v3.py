"""Persist complete v3 assessments and explicit Label archive state.

Revision ID: 20261012_01_risk_labels_v3
Revises: 20261011_01_authoritative_sanctions_registry
"""
from alembic import op
import sqlalchemy as sa


revision = "20261012_01_risk_labels_v3"
down_revision = "20261011_01_authoritative_sanctions_registry"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("risk_results") as batch:
        batch.add_column(sa.Column("assessment", sa.JSON(), nullable=True))
    with op.batch_alter_table("labels") as batch:
        batch.add_column(sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch.add_column(sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM risk_results WHERE assessment IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard saved v3 risk assessments")
    if connection.execute(sa.text("SELECT 1 FROM labels WHERE active = 0 OR archived_at IS NOT NULL LIMIT 1")).first():
        raise RuntimeError("Downgrade would discard Label archive state")
    with op.batch_alter_table("labels") as batch:
        batch.drop_column("archived_at")
        batch.drop_column("active")
    with op.batch_alter_table("risk_results") as batch:
        batch.drop_column("assessment")
