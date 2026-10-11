"""Authoritative OFAC snapshot registry, separate from labels and risk.

Revision ID: 20261011_01_authoritative_sanctions_registry
Revises: 20260929_01_public_source_capture
"""
from alembic import op
import sqlalchemy as sa

revision = '20261011_01_authoritative_sanctions_registry'
down_revision = '20260929_01_public_source_capture'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('sanctions_snapshots',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('source_id',sa.String(40),nullable=False),
        sa.Column('source_url',sa.String(500),nullable=False),
        sa.Column('retrieved_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('published_at',sa.String(80)),
        sa.Column('sha256',sa.String(64),nullable=False),
        sa.Column('official_sha256',sa.String(64)),
        sa.Column('integrity_status',sa.String(24),nullable=False),
        sa.Column('parser_version',sa.String(32),nullable=False),
        sa.Column('entity_count',sa.Integer,nullable=False),
        sa.Column('identifier_count',sa.Integer,nullable=False),
        sa.Column('change_counts',sa.JSON,nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('created_at',sa.DateTime(timezone=True),nullable=False))
    op.create_index('ix_sanctions_snapshots_source_id','sanctions_snapshots',['source_id'])
    op.create_table('sanctions_registry_state',
        sa.Column('source_id',sa.String(40),primary_key=True),
        sa.Column('current_snapshot_id',sa.String(36),sa.ForeignKey('sanctions_snapshots.id')),
        sa.Column('sync_lease_until',sa.DateTime(timezone=True)))
    op.create_table('sanctions_entities',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('snapshot_id',sa.String(36),sa.ForeignKey('sanctions_snapshots.id'),nullable=False),
        sa.Column('source_entity_id',sa.String(80),nullable=False),
        sa.Column('name',sa.String(500),nullable=False),
        sa.Column('entity_type',sa.String(80)),
        sa.Column('programs',sa.JSON,nullable=False),
        sa.Column('aliases',sa.JSON,nullable=False),
        sa.Column('remarks',sa.Text),
        sa.UniqueConstraint('snapshot_id','source_entity_id',name='uq_sanctions_entity_snapshot'))
    for name in ('snapshot_id','source_entity_id','name'):
        op.create_index('ix_sanctions_entities_'+name,'sanctions_entities',[name])
    op.create_table('sanctions_identifiers',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('snapshot_id',sa.String(36),sa.ForeignKey('sanctions_snapshots.id'),nullable=False),
        sa.Column('entity_id',sa.String(36),sa.ForeignKey('sanctions_entities.id'),nullable=False),
        sa.Column('source_field',sa.String(160),nullable=False),
        sa.Column('source_asset',sa.String(80),nullable=False),
        sa.Column('raw_value',sa.String(512),nullable=False),
        sa.Column('text_key',sa.String(512),nullable=False),
        sa.Column('canonical_address',sa.String(512)),
        sa.Column('chain',sa.String(32)),
        sa.Column('mapping_status',sa.String(32),nullable=False),
        sa.UniqueConstraint('snapshot_id','entity_id','source_field','raw_value',name='uq_sanctions_identifier_source'))
    for name in ('snapshot_id','entity_id','source_asset','text_key'):
        op.create_index('ix_sanctions_identifiers_'+name,'sanctions_identifiers',[name])
    op.create_index('ix_sanctions_exact_chain','sanctions_identifiers',['snapshot_id','chain','canonical_address'])
    op.create_table('sanctions_sync_events',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('source_id',sa.String(40),nullable=False),
        sa.Column('attempted_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('status',sa.String(20),nullable=False),
        sa.Column('reason',sa.String(40)),
        sa.Column('snapshot_id',sa.String(36),sa.ForeignKey('sanctions_snapshots.id')))
    op.create_index('ix_sanctions_sync_events_source_id','sanctions_sync_events',['source_id'])
    op.create_table('sanctions_case_pins',
        sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('case_id',sa.String(36),sa.ForeignKey('cases.id'),nullable=False),
        sa.Column('captured_at',sa.DateTime(timezone=True),nullable=False),
        sa.Column('record',sa.JSON,nullable=False))
    op.create_index('ix_sanctions_case_pins_case_id','sanctions_case_pins',['case_id'])


def downgrade():
    for name in ('sanctions_case_pins','sanctions_sync_events','sanctions_identifiers',
                 'sanctions_entities','sanctions_registry_state','sanctions_snapshots'):
        op.drop_table(name)
