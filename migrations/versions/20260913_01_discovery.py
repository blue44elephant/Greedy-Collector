"""ED-1 Discovery foundation. Frozen schema; no application model imports."""
from alembic import op
import sqlalchemy as sa
revision = '20260913_01'
down_revision = '20260912_01'
branch_labels = None
depends_on = None

def upgrade():
    op.create_table('discovery_subjects',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('namespace', sa.String(128), nullable=False),
        sa.Column('canonical_value', sa.Text, nullable=False),
        sa.Column('display_value', sa.Text, nullable=False),
        sa.Column('normalization_version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('identity_sha256', sa.String(64), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('blockchain_address', 'url', 'domain', 'repository', 'annotation')", name="ck_discovery_subjects_1"),
        sa.CheckConstraint('normalization_version >= 1', name="ck_discovery_subjects_2"),
        sa.CheckConstraint('length(identity_sha256) = 64', name="ck_discovery_subjects_3"),
        sa.CheckConstraint('length(canonical_value) BETWEEN 1 AND 2048', name="ck_discovery_subjects_4"),
        sa.CheckConstraint('length(namespace) > 0', name="ck_discovery_subjects_5"),
        sa.CheckConstraint("kind != 'blockchain_address' OR namespace IN ('bitcoin','ethereum')", name="ck_discovery_subjects_6"),
        sa.CheckConstraint("kind != 'blockchain_address' OR namespace != 'ethereum' OR canonical_value = lower(canonical_value)", name="ck_discovery_subjects_7"),
        sa.UniqueConstraint('identity_sha256', name="uq_discovery_subjects_1"),
    )
    op.create_index("ix_discovery_subjects_1", 'discovery_subjects', ['kind', 'namespace', 'id'], unique=False)
    op.create_table('discovery_runs',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_runs_subject_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('parent_observation_id', sa.String(36), sa.ForeignKey('discovery_observations.id', name='fk_discovery_runs_parent_observation_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('root_run_id', sa.String(36), sa.ForeignKey('discovery_runs.id', name='fk_discovery_runs_root_run_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('lineage_depth', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('idempotency_key', sa.String(128), nullable=False),
        sa.Column('request_sha256', sa.String(64), nullable=False),
        sa.Column('request_snapshot', sa.JSON, nullable=False),
        sa.Column('actor_ref', sa.String(128), nullable=False, server_default=sa.text("'local_analyst'")),
        sa.Column('status', sa.String(24), nullable=False, server_default=sa.text("'queued'")),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('deadline_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('cancel_requested_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.CheckConstraint("status IN ('queued', 'running', 'completed', 'partial', 'failed', 'cancelled', 'interrupted')", name="ck_discovery_runs_1"),
        sa.CheckConstraint('version >= 1', name="ck_discovery_runs_2"),
        sa.CheckConstraint('lineage_depth >= 0', name="ck_discovery_runs_3"),
        sa.CheckConstraint('(lineage_depth = 0 AND parent_observation_id IS NULL AND root_run_id IS NULL) OR (lineage_depth > 0 AND parent_observation_id IS NOT NULL AND root_run_id IS NOT NULL)', name="ck_discovery_runs_4"),
        sa.CheckConstraint('completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at', name="ck_discovery_runs_5"),
        sa.CheckConstraint('deadline_at >= created_at', name="ck_discovery_runs_6"),
        sa.UniqueConstraint('idempotency_key', name="uq_discovery_runs_1"),
    )
    op.create_index("ix_discovery_runs_1", 'discovery_runs', ['subject_id', 'created_at', 'id'], unique=False)
    op.create_index("ix_discovery_runs_2", 'discovery_runs', ['status', 'created_at', 'id'], unique=False)
    op.create_index("ix_discovery_runs_3", 'discovery_runs', ['root_run_id', 'created_at', 'id'], unique=False)
    op.create_index("ix_discovery_runs_4", 'discovery_runs', ['parent_observation_id'], unique=False)
    op.create_table('discovery_run_sources',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('run_id', sa.String(36), sa.ForeignKey('discovery_runs.id', name='fk_discovery_run_sources_run_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('ordinal', sa.Integer, nullable=False),
        sa.Column('transform_id', sa.String(128), nullable=False),
        sa.Column('transform_version', sa.Integer, nullable=False),
        sa.Column('source_id', sa.String(128), nullable=False),
        sa.Column('source_version', sa.Integer, nullable=False),
        sa.Column('config_generation', sa.String(64), nullable=False),
        sa.Column('descriptor_snapshot', sa.JSON, nullable=False),
        sa.Column('parameters', sa.JSON, nullable=False),
        sa.Column('query_fingerprint', sa.String(64), nullable=False),
        sa.Column('cache_from_id', sa.String(36), sa.ForeignKey('discovery_run_sources.id', name='fk_discovery_run_sources_cache_from_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('status', sa.String(24), nullable=False, server_default=sa.text("'queued'")),
        sa.Column('started_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('retention_policy_id', sa.String(128), nullable=False),
        sa.Column('coverage', sa.String(24), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('provider_total', sa.Integer, nullable=True),
        sa.Column('returned_count', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('requests_reserved', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('requests_attempted', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('cost_unit', sa.String(32), nullable=False),
        sa.Column('units_reserved', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('units_consumed', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('quota_bucket', sa.String(128), nullable=False),
        sa.Column('quota_window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('quota_snapshot', sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column('attempt_log', sa.JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column('error_code', sa.String(64), nullable=True),
        sa.Column('retry_after_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("status IN ('queued', 'running', 'succeeded', 'cache_hit', 'manual_ready', 'unavailable', 'rate_limited', 'budget_exhausted', 'timeout', 'failed', 'cancelled', 'interrupted')", name="ck_discovery_run_sources_1"),
        sa.CheckConstraint("coverage IN ('bounded', 'provider_incomplete', 'limit_reached', 'unknown')", name="ck_discovery_run_sources_2"),
        sa.CheckConstraint('ordinal > 0 AND transform_version > 0 AND source_version > 0', name="ck_discovery_run_sources_3"),
        sa.CheckConstraint('returned_count >= 0 AND requests_reserved >= 0 AND requests_attempted >= 0 AND units_reserved >= 0 AND units_consumed >= 0', name="ck_discovery_run_sources_4"),
        sa.CheckConstraint('provider_total IS NULL OR provider_total >= 0', name="ck_discovery_run_sources_5"),
        sa.CheckConstraint("status NOT IN ('cache_hit','manual_ready') OR (requests_attempted = 0 AND units_consumed = 0)", name="ck_discovery_run_sources_6"),
        sa.CheckConstraint("(status = 'cache_hit') = (cache_from_id IS NOT NULL)", name="ck_discovery_run_sources_7"),
        sa.CheckConstraint('completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at', name="ck_discovery_run_sources_8"),
        sa.UniqueConstraint('run_id', 'ordinal', name="uq_discovery_run_sources_1"),
        sa.UniqueConstraint('run_id', 'transform_id', 'source_id', name="uq_discovery_run_sources_2"),
    )
    op.create_index("ix_discovery_run_sources_1", 'discovery_run_sources', ['query_fingerprint', 'status', 'expires_at', 'completed_at'], unique=False)
    op.create_index("ix_discovery_run_sources_2", 'discovery_run_sources', ['quota_bucket', 'quota_window_start', 'status'], unique=False)
    op.create_index("ix_discovery_run_sources_3", 'discovery_run_sources', ['cache_from_id'], unique=False)
    op.create_table('discovery_results',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('query_subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_results_query_subject_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('kind', sa.String(32), nullable=False),
        sa.Column('predicate', sa.String(64), nullable=False),
        sa.Column('from_subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_results_from_subject_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('to_subject_id', sa.String(36), sa.ForeignKey('discovery_subjects.id', name='fk_discovery_results_to_subject_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('fact_key', sa.JSON, nullable=False),
        sa.Column('identity_sha256', sa.String(64), nullable=False),
        sa.Column('first_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_seen_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('material_revision', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.Column('review_status', sa.String(16), nullable=False, server_default=sa.text("'unreviewed'")),
        sa.Column('reviewed_material_revision', sa.Integer, nullable=False, server_default=sa.text('0')),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.CheckConstraint("kind IN ('candidate_evidence', 'candidate_identifier', 'candidate_relationship')", name="ck_discovery_results_1"),
        sa.CheckConstraint("predicate IN ('mentioned_at', 'repository_contains', 'explorer_labeled_as', 'locally_labeled_as', 'publicly_listed_by', 'reverse_name_record', 'resolves_to', 'registration_record_for', 'certificate_names', 'observed_at', 'archived_at', 'uses_tracking_id', 'advertises_at')", name="ck_discovery_results_2"),
        sa.CheckConstraint("review_status IN ('unreviewed', 'relevant', 'irrelevant')", name="ck_discovery_results_3"),
        sa.CheckConstraint('material_revision >= 1 AND version >= 1', name="ck_discovery_results_4"),
        sa.CheckConstraint('reviewed_material_revision BETWEEN 0 AND material_revision', name="ck_discovery_results_5"),
        sa.CheckConstraint('last_seen_at >= first_seen_at', name="ck_discovery_results_6"),
        sa.UniqueConstraint('identity_sha256', name="uq_discovery_results_1"),
    )
    op.create_index("ix_discovery_results_1", 'discovery_results', ['query_subject_id', 'last_seen_at', 'id'], unique=False)
    op.create_index("ix_discovery_results_2", 'discovery_results', ['from_subject_id', 'predicate', 'id'], unique=False)
    op.create_index("ix_discovery_results_3", 'discovery_results', ['to_subject_id', 'predicate', 'id'], unique=False)
    op.create_index("ix_discovery_results_4", 'discovery_results', ['review_status', 'last_seen_at', 'id'], unique=False)
    op.create_table('discovery_observations',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('result_id', sa.String(36), sa.ForeignKey('discovery_results.id', name='fk_discovery_observations_result_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('execution_id', sa.String(36), sa.ForeignKey('discovery_run_sources.id', name='fk_discovery_observations_execution_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('source_record_key', sa.String(512), nullable=False),
        sa.Column('kind', sa.String(40), nullable=False),
        sa.Column('source_url', sa.Text, nullable=True),
        sa.Column('source_locator', sa.String(512), nullable=True),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('summary', sa.Text, nullable=False),
        sa.Column('excerpt', sa.Text, nullable=True),
        sa.Column('excerpt_complete', sa.Boolean, nullable=False, server_default=sa.text('0')),
        sa.Column('verification', sa.String(32), nullable=False),
        sa.Column('match_context', sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column('source_class', sa.String(40), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('observed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('observed_on', sa.Date, nullable=True),
        sa.Column('published_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('published_on', sa.Date, nullable=True),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('source_snapshot', sa.JSON, nullable=False),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.Column('origin_label_id', sa.String(36), sa.ForeignKey('labels.id', name='fk_discovery_observations_origin_label_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('origin_match_id', sa.String(36), sa.ForeignKey('kyc_matches.id', name='fk_discovery_observations_origin_match_id', ondelete='RESTRICT'), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("kind IN ('search_result', 'code_search_result', 'local_label_snapshot', 'verified_page_observation', 'explorer_annotation', 'name_service_record', 'research_result', 'archive_index_record', 'analyst_capture')", name="ck_discovery_observations_1"),
        sa.CheckConstraint("verification IN ('not_checked', 'exact_in_excerpt', 'exact_in_document', 'technical_verified', 'mismatch', 'not_applicable')", name="ck_discovery_observations_2"),
        sa.CheckConstraint('length(content_sha256) = 64', name="ck_discovery_observations_3"),
        sa.CheckConstraint('observed_at IS NULL OR observed_on IS NULL', name="ck_discovery_observations_4"),
        sa.CheckConstraint('published_at IS NULL OR published_on IS NULL', name="ck_discovery_observations_5"),
        sa.CheckConstraint('origin_label_id IS NULL OR origin_match_id IS NULL', name="ck_discovery_observations_6"),
        sa.CheckConstraint("kind != 'local_label_snapshot' OR origin_label_id IS NOT NULL", name="ck_discovery_observations_7"),
        sa.CheckConstraint("length(trim(coalesce(source_url,''))) > 0 OR length(trim(coalesce(source_locator,''))) > 0", name="ck_discovery_observations_8"),
        sa.UniqueConstraint('execution_id', 'result_id', 'source_record_key', 'content_sha256', name="uq_discovery_observations_1"),
    )
    op.create_index("ix_discovery_observations_1", 'discovery_observations', ['result_id', 'retrieved_at', 'id'], unique=False)
    op.create_index("ix_discovery_observations_2", 'discovery_observations', ['result_id', 'content_sha256'], unique=False)
    op.create_index("ix_discovery_observations_3", 'discovery_observations', ['origin_label_id'], unique=False)
    op.create_index("ix_discovery_observations_4", 'discovery_observations', ['origin_match_id'], unique=False)
    op.create_table('discovery_run_items',
        sa.Column('run_source_id', sa.String(36), sa.ForeignKey('discovery_run_sources.id', name='fk_discovery_run_items_run_source_id', ondelete='RESTRICT'), nullable=False, primary_key=True),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('discovery_observations.id', name='fk_discovery_run_items_observation_id', ondelete='RESTRICT'), nullable=False, primary_key=True),
        sa.Column('ordinal', sa.Integer, nullable=False),
        sa.Column('rank', sa.Integer, nullable=True),
        sa.Column('included_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('inclusion_kind', sa.String(16), nullable=False),
        sa.CheckConstraint('ordinal > 0', name="ck_discovery_run_items_1"),
        sa.CheckConstraint('rank IS NULL OR rank >= 0', name="ck_discovery_run_items_2"),
        sa.CheckConstraint("inclusion_kind IN ('retrieved', 'local', 'cache')", name="ck_discovery_run_items_3"),
        sa.UniqueConstraint('run_source_id', 'ordinal', name="uq_discovery_run_items_1"),
    )
    op.create_index("ix_discovery_run_items_1", 'discovery_run_items', ['observation_id'], unique=False)
    op.create_table('discovery_reviews',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('result_id', sa.String(36), sa.ForeignKey('discovery_results.id', name='fk_discovery_reviews_result_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('observation_id', sa.String(36), sa.ForeignKey('discovery_observations.id', name='fk_discovery_reviews_observation_id', ondelete='RESTRICT'), nullable=False),
        sa.Column('sequence', sa.Integer, nullable=False),
        sa.Column('material_revision', sa.Integer, nullable=False),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('actor_ref', sa.String(128), nullable=False, server_default=sa.text("'local_analyst'")),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint('sequence > 0 AND material_revision > 0', name="ck_discovery_reviews_1"),
        sa.CheckConstraint("status IN ('unreviewed', 'relevant', 'irrelevant')", name="ck_discovery_reviews_2"),
        sa.CheckConstraint('length(trim(reason)) BETWEEN 1 AND 4000', name="ck_discovery_reviews_3"),
        sa.UniqueConstraint('result_id', 'sequence', name="uq_discovery_reviews_1"),
    )
    op.create_index("ix_discovery_reviews_1", 'discovery_reviews', ['observation_id'], unique=False)
    op.create_index("ix_discovery_reviews_2", 'discovery_reviews', ['occurred_at', 'id'], unique=False)
    op.execute("CREATE TRIGGER discovery_observations_no_update BEFORE UPDATE ON discovery_observations BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_observations_no_delete BEFORE DELETE ON discovery_observations BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_observations_no_replace BEFORE INSERT ON discovery_observations WHEN EXISTS (SELECT 1 FROM discovery_observations WHERE id = NEW.id OR (execution_id = NEW.execution_id AND result_id = NEW.result_id AND source_record_key = NEW.source_record_key AND content_sha256 = NEW.content_sha256)) BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_run_items_no_update BEFORE UPDATE ON discovery_run_items BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_run_items_no_delete BEFORE DELETE ON discovery_run_items BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_run_items_no_replace BEFORE INSERT ON discovery_run_items WHEN EXISTS (SELECT 1 FROM discovery_run_items WHERE (run_source_id = NEW.run_source_id AND observation_id = NEW.observation_id) OR (run_source_id = NEW.run_source_id AND ordinal = NEW.ordinal)) BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_reviews_no_update BEFORE UPDATE ON discovery_reviews BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_reviews_no_delete BEFORE DELETE ON discovery_reviews BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")
    op.execute("CREATE TRIGGER discovery_reviews_no_replace BEFORE INSERT ON discovery_reviews WHEN EXISTS (SELECT 1 FROM discovery_reviews WHERE id = NEW.id OR (result_id = NEW.result_id AND sequence = NEW.sequence)) BEGIN SELECT RAISE(ABORT, 'Discovery history is immutable'); END")

def downgrade():
    connection = op.get_bind()
    for table in ['discovery_subjects', 'discovery_runs', 'discovery_run_sources', 'discovery_results', 'discovery_observations', 'discovery_run_items', 'discovery_reviews']:
        if connection.execute(sa.text('SELECT COUNT(*) FROM ' + table)).scalar_one():
            raise RuntimeError('Cannot downgrade populated Discovery history; use explicit backup recovery')
    op.execute("DROP TRIGGER IF EXISTS discovery_observations_no_update")
    op.execute("DROP TRIGGER IF EXISTS discovery_observations_no_delete")
    op.execute("DROP TRIGGER IF EXISTS discovery_observations_no_replace")
    op.execute("DROP TRIGGER IF EXISTS discovery_run_items_no_update")
    op.execute("DROP TRIGGER IF EXISTS discovery_run_items_no_delete")
    op.execute("DROP TRIGGER IF EXISTS discovery_run_items_no_replace")
    op.execute("DROP TRIGGER IF EXISTS discovery_reviews_no_update")
    op.execute("DROP TRIGGER IF EXISTS discovery_reviews_no_delete")
    op.execute("DROP TRIGGER IF EXISTS discovery_reviews_no_replace")
    op.drop_table('discovery_reviews')
    op.drop_table('discovery_run_items')
    op.drop_table('discovery_observations')
    op.drop_table('discovery_results')
    op.drop_table('discovery_run_sources')
    op.drop_table('discovery_runs')
    op.drop_table('discovery_subjects')
