"""Immutable Discovery promotion provenance and Attribution capture origin.

Revision ID: 20260915_01
Revises: 20260913_01
"""
from alembic import op
import sqlalchemy as sa

revision = '20260915_01'
down_revision = '20260913_01'
branch_labels = None
depends_on = None

OLD_CHECKS = {'ck_attribution_evidence_1': "evidence_type IN ('official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'research_snapshot', 'label_snapshot', 'analyst_observation')", 'ck_attribution_evidence_3': "collection_method IN ('analyst_entry', 'label_snapshot', 'research_snapshot')", 'ck_attribution_evidence_8': "(collection_method = 'analyst_entry' AND origin_label_id IS NULL AND origin_match_id IS NULL AND evidence_type NOT IN ('label_snapshot','research_snapshot')) OR (collection_method = 'label_snapshot' AND origin_label_id IS NOT NULL AND origin_match_id IS NULL AND evidence_type = 'label_snapshot') OR (collection_method = 'research_snapshot' AND origin_match_id IS NOT NULL AND origin_label_id IS NULL AND evidence_type = 'research_snapshot')"}
NEW_CHECKS = {'ck_attribution_evidence_1': "evidence_type IN ('official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'research_snapshot', 'label_snapshot', 'analyst_observation', 'discovery_snapshot')", 'ck_attribution_evidence_3': "collection_method IN ('analyst_entry', 'label_snapshot', 'research_snapshot', 'discovery_snapshot')", 'ck_attribution_evidence_8': "((collection_method = 'analyst_entry' AND origin_label_id IS NULL AND origin_match_id IS NULL AND evidence_type NOT IN ('label_snapshot','research_snapshot','discovery_snapshot')) OR (collection_method = 'label_snapshot' AND origin_label_id IS NOT NULL AND origin_match_id IS NULL AND evidence_type = 'label_snapshot') OR (collection_method = 'research_snapshot' AND origin_match_id IS NOT NULL AND origin_label_id IS NULL AND evidence_type = 'research_snapshot')) AND origin_discovery_observation_id IS NULL OR (collection_method = 'discovery_snapshot' AND evidence_type = 'discovery_snapshot' AND origin_discovery_observation_id IS NOT NULL AND origin_label_id IS NULL AND origin_match_id IS NULL)"}
ATTRIBUTION_TRIGGERS = {'attribution_events_no_delete': "CREATE TRIGGER attribution_events_no_delete BEFORE DELETE ON attribution_events BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END", 'attribution_events_no_replace': "CREATE TRIGGER attribution_events_no_replace BEFORE INSERT ON attribution_events WHEN EXISTS (SELECT 1 FROM attribution_events WHERE id = NEW.id OR (sequence = NEW.sequence AND (entity_id = NEW.entity_id OR claim_id = NEW.claim_id OR evidence_id = NEW.evidence_id))) BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END", 'attribution_events_no_update': "CREATE TRIGGER attribution_events_no_update BEFORE UPDATE ON attribution_events BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END", 'attribution_evidence_no_delete': "CREATE TRIGGER attribution_evidence_no_delete BEFORE DELETE ON attribution_evidence BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END", 'attribution_evidence_no_replace': "CREATE TRIGGER attribution_evidence_no_replace BEFORE INSERT ON attribution_evidence WHEN EXISTS (SELECT 1 FROM attribution_evidence WHERE id = NEW.id) BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END", 'attribution_evidence_no_update': "CREATE TRIGGER attribution_evidence_no_update BEFORE UPDATE ON attribution_evidence BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END"}
PROMOTION_TRIGGERS = {'discovery_promotions_no_update': "CREATE TRIGGER discovery_promotions_no_update BEFORE UPDATE ON discovery_promotions BEGIN SELECT RAISE(ABORT, 'Discovery promotions are immutable'); END", 'discovery_promotions_no_delete': "CREATE TRIGGER discovery_promotions_no_delete BEFORE DELETE ON discovery_promotions BEGIN SELECT RAISE(ABORT, 'Discovery promotions are immutable'); END", 'discovery_promotions_no_replace': "CREATE TRIGGER discovery_promotions_no_replace BEFORE INSERT ON discovery_promotions WHEN EXISTS (SELECT 1 FROM discovery_promotions WHERE id = NEW.id OR (observation_id = NEW.observation_id AND claim_id = NEW.claim_id)) BEGIN SELECT RAISE(ABORT, 'Discovery promotions are immutable'); END", 'discovery_promotions_valid_link': "CREATE TRIGGER discovery_promotions_valid_link BEFORE INSERT ON discovery_promotions WHEN NOT EXISTS (SELECT 1 FROM attribution_claim_evidence l JOIN attribution_evidence e ON e.id = l.evidence_id WHERE l.id = NEW.link_id AND l.claim_id = NEW.claim_id AND l.evidence_id = NEW.evidence_id AND e.origin_discovery_observation_id = NEW.observation_id AND e.content_sha256 = NEW.capture_fingerprint) BEGIN SELECT RAISE(ABORT, 'Discovery promotion references must agree'); END"}
PROMOTION_DDL = "\nCREATE TABLE discovery_promotions (\n\tid VARCHAR(36) NOT NULL, \n\tobservation_id VARCHAR(36) NOT NULL, \n\tclaim_id VARCHAR(36) NOT NULL, \n\tevidence_id VARCHAR(36) NOT NULL, \n\tlink_id VARCHAR(36) NOT NULL, \n\tsource_fingerprint VARCHAR(64) NOT NULL, \n\tcapture_fingerprint VARCHAR(64) NOT NULL, \n\tclaim_version_before INTEGER NOT NULL, \n\tclaim_version_after INTEGER NOT NULL, \n\tactor_ref VARCHAR(128) DEFAULT 'local_analyst' NOT NULL, \n\tcreated_at DATETIME NOT NULL, \n\tPRIMARY KEY (id), \n\tCONSTRAINT uq_discovery_promotions_1 UNIQUE (observation_id, claim_id), \n\tCONSTRAINT ck_discovery_promotions_1 CHECK (length(source_fingerprint) = 64 AND length(capture_fingerprint) = 64), \n\tCONSTRAINT ck_discovery_promotions_2 CHECK (claim_version_before >= 1 AND claim_version_after = claim_version_before + 1), \n\tCONSTRAINT ck_discovery_promotions_3 CHECK (actor_ref = 'local_analyst'), \n\tCONSTRAINT fk_discovery_promotions_observation_id FOREIGN KEY(observation_id) REFERENCES discovery_observations (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_discovery_promotions_claim_id FOREIGN KEY(claim_id) REFERENCES attribution_claims (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_discovery_promotions_evidence_id FOREIGN KEY(evidence_id) REFERENCES attribution_evidence (id) ON DELETE RESTRICT, \n\tCONSTRAINT fk_discovery_promotions_link_id FOREIGN KEY(link_id) REFERENCES attribution_claim_evidence (id) ON DELETE RESTRICT\n)\n\n"
INDEX_DDL = ['CREATE INDEX ix_discovery_promotions_1 ON discovery_promotions (claim_id, created_at, id)', 'CREATE INDEX ix_discovery_promotions_2 ON discovery_promotions (evidence_id)', 'CREATE INDEX ix_discovery_promotions_3 ON discovery_promotions (link_id)']


def _begin():
    connection = op.get_bind()
    if connection.dialect.name != 'sqlite':
        raise RuntimeError('ED-6 currently requires SQLite')
    # Batch replacement must not cascade/restrict existing child references.
    # Alembic uses its dedicated offline application connection with FK checks
    # disabled; validate all references before committing the DDL transaction.
    if connection.exec_driver_sql('PRAGMA foreign_keys').scalar_one():
        raise RuntimeError('Use the dedicated Alembic migration connection for ED-6')
    if not connection.connection.driver_connection.in_transaction:
        connection.exec_driver_sql('BEGIN IMMEDIATE')
    return connection


def _evidence(up):
    for name in ATTRIBUTION_TRIGGERS:
        if name.startswith('attribution_evidence_'):
            op.execute('DROP TRIGGER '+name)
    with op.batch_alter_table('attribution_evidence', recreate='always') as batch:
        for name in OLD_CHECKS:
            batch.drop_constraint(name, type_='check')
        if up:
            batch.add_column(sa.Column('origin_discovery_observation_id',sa.String(36),nullable=True))
            batch.create_foreign_key('fk_attribution_evidence_origin_discovery_observation_id','discovery_observations',['origin_discovery_observation_id'],['id'],ondelete='RESTRICT')
            batch.create_index('ix_attribution_evidence_7',['origin_discovery_observation_id'])
        else:
            batch.drop_index('ix_attribution_evidence_7')
            batch.drop_constraint('fk_attribution_evidence_origin_discovery_observation_id',type_='foreignkey')
            batch.drop_column('origin_discovery_observation_id')
        for name,sql in (NEW_CHECKS if up else OLD_CHECKS).items():
            batch.create_check_constraint(name,sql)
    for name,sql in ATTRIBUTION_TRIGGERS.items():
        if name.startswith('attribution_evidence_'):
            op.execute(sql)


def upgrade():
    connection = _begin()
    _evidence(True)
    op.execute(PROMOTION_DDL)
    for sql in INDEX_DDL: op.execute(sql)
    for sql in PROMOTION_TRIGGERS.values(): op.execute(sql)
    if connection.exec_driver_sql('PRAGMA foreign_key_check').all():
        raise RuntimeError('ED-6 migration failed foreign-key validation')


def downgrade():
    connection = _begin()
    if connection.exec_driver_sql('SELECT 1 FROM discovery_promotions LIMIT 1').first() or connection.exec_driver_sql("SELECT 1 FROM attribution_evidence WHERE collection_method = 'discovery_snapshot' LIMIT 1").first():
        raise RuntimeError('Cannot downgrade populated Discovery promotion history')
    for name in PROMOTION_TRIGGERS: op.execute('DROP TRIGGER '+name)
    op.drop_table('discovery_promotions')
    _evidence(False)
    if connection.exec_driver_sql('PRAGMA foreign_key_check').all():
        raise RuntimeError('ED-6 downgrade failed foreign-key validation')
