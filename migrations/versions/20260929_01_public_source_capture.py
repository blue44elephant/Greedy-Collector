"""Immutable explicit public source captures, reviews and promotions."""
from alembic import op
import sqlalchemy as sa
revision='20260929_01_public_source_capture'
down_revision='20260928_01'
branch_labels=None
depends_on=None
TABLES=('discovery_public_captures','discovery_capture_reviews','discovery_capture_promotions')

def upgrade():
    op.create_table(TABLES[0],sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('observation_id',sa.String(36),sa.ForeignKey('discovery_observations.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('result_id',sa.String(36),sa.ForeignKey('discovery_results.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('normalized_url',sa.String(2048),nullable=False),sa.Column('retrieved_at',sa.String(40),nullable=False),
        sa.Column('body_sha256',sa.String(64)),sa.Column('status',sa.String(16),nullable=False),sa.Column('material',sa.JSON(),nullable=False),sa.Column('raw_body',sa.LargeBinary()),
        sa.CheckConstraint("status IN ('captured','failed')",name='ck_public_capture_status'))
    for name,cols in [('observation',['observation_id','retrieved_at']),('result',['result_id']),('url',['normalized_url','retrieved_at']),('hash',['body_sha256'])]:op.create_index('ix_public_capture_'+name,TABLES[0],cols)
    op.create_table(TABLES[1],sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('capture_id',sa.String(36),sa.ForeignKey(TABLES[0]+'.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('sequence',sa.Integer(),nullable=False),sa.Column('status',sa.String(16),nullable=False),
        sa.Column('note',sa.String(2000),nullable=False),sa.Column('created_at',sa.String(40),nullable=False),
        sa.UniqueConstraint('capture_id','sequence'),sa.CheckConstraint("sequence >= 1 AND status IN ('unreviewed','relevant','irrelevant') AND length(trim(note)) > 0",name='ck_public_capture_review'))
    op.create_table(TABLES[2],sa.Column('id',sa.String(36),primary_key=True),
        sa.Column('capture_id',sa.String(36),sa.ForeignKey(TABLES[0]+'.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('claim_id',sa.String(36),sa.ForeignKey('attribution_claims.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('evidence_id',sa.String(36),sa.ForeignKey('attribution_evidence.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('link_id',sa.String(36),sa.ForeignKey('attribution_claim_evidence.id',ondelete='RESTRICT'),nullable=False),
        sa.Column('source_fingerprint',sa.String(64),nullable=False),sa.Column('created_at',sa.String(40),nullable=False),sa.UniqueConstraint('capture_id','claim_id'))
    for table in TABLES:
        for operation in ('UPDATE','DELETE'):
            op.execute(f"CREATE TRIGGER {table}_no_{operation.lower()} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'Public capture history is immutable'); END")
        op.execute(f"CREATE TRIGGER {table}_no_replace BEFORE INSERT ON {table} WHEN EXISTS(SELECT 1 FROM {table} WHERE id=NEW.id) BEGIN SELECT RAISE(ABORT,'Public capture history is immutable'); END")
    op.execute("CREATE TRIGGER public_capture_origin BEFORE INSERT ON discovery_public_captures WHEN NOT EXISTS(SELECT 1 FROM discovery_observations WHERE id=NEW.observation_id AND result_id=NEW.result_id AND kind='search_result') BEGIN SELECT RAISE(ABORT,'Capture origin must agree'); END")
    op.execute("CREATE TRIGGER public_capture_promotion_link BEFORE INSERT ON discovery_capture_promotions WHEN NOT EXISTS(SELECT 1 FROM attribution_claim_evidence l JOIN attribution_evidence e ON e.id=l.evidence_id JOIN discovery_public_captures c ON c.id=NEW.capture_id WHERE l.id=NEW.link_id AND l.claim_id=NEW.claim_id AND l.evidence_id=NEW.evidence_id AND e.origin_discovery_observation_id=c.observation_id AND json_extract(e.metadata_json,'$.capture.id')=c.id) BEGIN SELECT RAISE(ABORT,'Capture promotion must agree'); END")
    for operation in ('UPDATE','DELETE'):
        op.execute(f"CREATE TRIGGER public_capture_case_no_{operation.lower()} BEFORE {operation} ON case_entities WHEN OLD.entity_type='public_source_capture' BEGIN SELECT RAISE(ABORT,'Capture case pin is immutable'); END")
    op.execute("CREATE TRIGGER public_capture_case_no_replace BEFORE INSERT ON case_entities WHEN EXISTS(SELECT 1 FROM case_entities WHERE id=NEW.id AND entity_type='public_source_capture') BEGIN SELECT RAISE(ABORT,'Capture case pin is immutable'); END")

def downgrade():
    if op.get_bind().exec_driver_sql('SELECT 1 FROM discovery_public_captures LIMIT 1').first():raise RuntimeError('Retained public captures prevent downgrade')
    for name in ('public_capture_origin','public_capture_promotion_link','public_capture_case_no_update','public_capture_case_no_delete','public_capture_case_no_replace'):op.execute('DROP TRIGGER '+name)
    for table in reversed(TABLES):
        for suffix in ('update','delete','replace'):op.execute('DROP TRIGGER '+table+'_no_'+suffix)
        op.drop_table(table)
