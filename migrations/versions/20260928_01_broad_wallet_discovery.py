"""Source-bound broad candidates and immutable review/case history; no collection."""
from alembic import op
import sqlalchemy as sa
revision='20260928_01'
down_revision='20260927_02'
branch_labels=None
depends_on=None

def upgrade():
    op.create_table('discovery_broad_candidates',sa.Column('id',sa.String(64),primary_key=True),
        sa.Column('observation_id',sa.String(36),sa.ForeignKey('discovery_observations.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('chain',sa.String(32),nullable=False),sa.Column('wallet',sa.String(128),nullable=False),
        sa.Column('provider',sa.String(128),nullable=False),sa.Column('kind',sa.String(16),nullable=False),
        sa.Column('value',sa.String(255),nullable=False),sa.Column('canonical_url',sa.String(2048),nullable=False),
        sa.Column('material',sa.JSON(),nullable=False),sa.Column('status',sa.String(16),nullable=False),sa.Column('version',sa.Integer(),nullable=False),
        sa.CheckConstraint("kind IN ('alias','entity','domain')",name='ck_broad_candidate_kind'),
        sa.CheckConstraint("status IN ('unreviewed','relevant','irrelevant') AND version >= 1",name='ck_broad_candidate_review'))
    for name,columns in [('observation',['observation_id']),('wallet',['chain','wallet']),('provider',['provider']),('review',['status']),('url',['canonical_url']),('value',['kind','value'])]:
        op.create_index('ix_broad_candidate_'+name,'discovery_broad_candidates',columns)
    op.create_table('discovery_broad_candidate_reviews',sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('candidate_id',sa.String(64),sa.ForeignKey('discovery_broad_candidates.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('sequence',sa.Integer(),nullable=False),sa.Column('status',sa.String(16),nullable=False),
        sa.Column('note',sa.String(2000),nullable=False),sa.Column('created_at',sa.String(40),nullable=False),
        sa.UniqueConstraint('candidate_id','sequence'),sa.CheckConstraint("status IN ('unreviewed','relevant','irrelevant') AND sequence >= 1 AND length(trim(note)) > 0",name='ck_broad_review'))
    fields=('id','observation_id','chain','wallet','provider','kind','value','canonical_url','material')
    condition=' OR '.join('NEW.'+f+' IS NOT OLD.'+f for f in fields)
    op.execute("CREATE TRIGGER broad_candidate_material BEFORE UPDATE ON discovery_broad_candidates WHEN "+condition+" BEGIN SELECT RAISE(ABORT,'Candidate provenance is immutable'); END")
    for table in ('discovery_broad_candidates','discovery_broad_candidate_reviews'):
        op.execute(f"CREATE TRIGGER {table}_no_delete BEFORE DELETE ON {table} BEGIN SELECT RAISE(ABORT,'Broad history is immutable'); END")
        op.execute(f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'Broad history is immutable'); END")
    op.execute("CREATE TRIGGER broad_reviews_no_update BEFORE UPDATE ON discovery_broad_candidate_reviews BEGIN SELECT RAISE(ABORT,'Broad review is immutable'); END")
    for operation in ('UPDATE','DELETE'):
        op.execute(f"CREATE TRIGGER broad_case_pin_no_{operation.lower()} BEFORE {operation} ON case_entities WHEN OLD.entity_type='broad_discovery' BEGIN SELECT RAISE(ABORT,'Broad case pin is immutable'); END")
    op.execute("CREATE TRIGGER broad_case_pin_no_replace BEFORE INSERT ON case_entities WHEN EXISTS(SELECT 1 FROM case_entities WHERE id=NEW.id AND entity_type='broad_discovery') BEGIN SELECT RAISE(ABORT,'Broad case pin is immutable'); END")

def downgrade():
    c=op.get_bind()
    if c.exec_driver_sql('SELECT 1 FROM discovery_broad_candidates LIMIT 1').first() or c.exec_driver_sql("SELECT 1 FROM case_entities WHERE entity_type='broad_discovery' LIMIT 1").first():raise RuntimeError('Retained broad discovery material prevents downgrade')
    for name in ('broad_candidate_material','discovery_broad_candidates_no_delete','discovery_broad_candidates_no_replace','discovery_broad_candidate_reviews_no_delete','discovery_broad_candidate_reviews_no_replace','broad_reviews_no_update','broad_case_pin_no_update','broad_case_pin_no_delete','broad_case_pin_no_replace'):op.execute('DROP TRIGGER '+name)
    op.drop_table('discovery_broad_candidate_reviews');op.drop_table('discovery_broad_candidates')
