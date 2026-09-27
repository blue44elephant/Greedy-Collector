"""Immutable observed-flow runs and chain-scoped adjacency indexes."""
import sqlalchemy as sa
from alembic import op
revision='20260927_02'
down_revision='20260927_01'
branch_labels=None
depends_on=None
INDEXES={
    'ix_flow_from': 'chain, from_address, timestamp',
    'ix_flow_to': 'chain, to_address, timestamp',
    'ix_flow_from_folded': 'chain, lower(from_address), timestamp',
    'ix_flow_to_folded': 'chain, lower(to_address), timestamp',
    'ix_flow_asset_time': 'chain, asset_contract, timestamp',
}

def upgrade():
    op.create_table('fund_flow_runs',sa.Column('id',sa.String(36),primary_key=True),sa.Column('chain',sa.String(32),nullable=False),
        sa.Column('source',sa.String(128),nullable=False),sa.Column('created_at',sa.String(40),nullable=False),sa.Column('snapshot',sa.JSON(),nullable=False))
    op.create_index('ix_fund_flow_runs_source','fund_flow_runs',['chain','source','created_at'])
    for name,columns in INDEXES.items():op.execute(f'CREATE INDEX {name} ON transactions ({columns})')
    for operation in ('UPDATE','DELETE'):
        op.execute(f"CREATE TRIGGER fund_flow_runs_no_{operation.lower()} BEFORE {operation} ON fund_flow_runs BEGIN SELECT RAISE(ABORT, 'Fund-flow history is immutable'); END")
    op.execute("CREATE TRIGGER fund_flow_case_pin_no_update BEFORE UPDATE ON case_entities WHEN OLD.entity_type='fund_flow' BEGIN SELECT RAISE(ABORT, 'Fund-flow case pin is immutable'); END")

def downgrade():
    bind=op.get_bind()
    if bind.execute(sa.text('SELECT 1 FROM fund_flow_runs LIMIT 1')).first() or bind.execute(sa.text("SELECT 1 FROM case_entities WHERE entity_type='fund_flow' LIMIT 1")).first():
        raise RuntimeError('Refusing to discard retained fund-flow material')
    for name in ('fund_flow_runs_no_update','fund_flow_runs_no_delete','fund_flow_case_pin_no_update'):op.execute(f'DROP TRIGGER {name}')
    for name in INDEXES:op.drop_index(name,table_name='transactions')
    op.drop_table('fund_flow_runs')
