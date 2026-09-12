"""Add attribution persistence and immutable evidence/history (AT-1)."""
from alembic import op
import sqlalchemy as sa

revision = "20260912_01"
down_revision = "20260630_01"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('attribution_entities',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('canonical_name', sa.String(255), nullable=False),
        sa.Column('name_key', sa.String(255), nullable=False),
        sa.Column('entity_type', sa.String(32), nullable=False, server_default=sa.text("'unknown'")),
        sa.Column('description', sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column('aliases', sa.JSON, nullable=False, server_default=sa.text("'[]'")),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.CheckConstraint("entity_type IN ('organization', 'person', 'service', 'protocol', 'public_body', 'online_identity', 'unknown')", name="ck_attribution_entities_1"),
        sa.CheckConstraint('version >= 1', name="ck_attribution_entities_2"),
        sa.CheckConstraint('length(trim(canonical_name)) > 0', name="ck_attribution_entities_3"),
        sa.CheckConstraint('length(trim(name_key)) > 0', name="ck_attribution_entities_4"),
    )
    op.create_index('ix_attribution_entities_1', 'attribution_entities', ['name_key', 'id'], unique=False)
    op.create_index('ix_attribution_entities_2', 'attribution_entities', ['archived_at', 'entity_type', 'id'], unique=False)

    op.create_table('attribution_claims',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('subject_type', sa.String(16), nullable=False, server_default=sa.text("'wallet'")),
        sa.Column('chain', sa.String(32), nullable=False),
        sa.Column('subject_ref', sa.String(128), nullable=False),
        sa.Column('entity_id', sa.String(36), sa.ForeignKey('attribution_entities.id', name='fk_attribution_claims_entity_id', ondelete="RESTRICT"), nullable=False),
        sa.Column('relationship', sa.String(32), nullable=False),
        sa.Column('valid_from', sa.Date, nullable=True),
        sa.Column('valid_to', sa.Date, nullable=True),
        sa.Column('scope_note', sa.Text, nullable=False),
        sa.Column('assessment', sa.String(32), nullable=False, server_default=sa.text("'unassessed'")),
        sa.Column('assessment_rationale', sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column('assessed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('assessed_by', sa.String(128), nullable=True),
        sa.Column('needs_review', sa.Boolean, nullable=False, server_default=sa.text('1')),
        sa.Column('created_by', sa.String(128), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('version', sa.Integer, nullable=False, server_default=sa.text('1')),
        sa.CheckConstraint("subject_type = 'wallet'", name="ck_attribution_claims_1"),
        sa.CheckConstraint("chain IN ('bitcoin','ethereum')", name="ck_attribution_claims_2"),
        sa.CheckConstraint("relationship IN ('operated_by', 'controlled_by', 'publicly_declared_by')", name="ck_attribution_claims_3"),
        sa.CheckConstraint("assessment IN ('unassessed', 'possible', 'supported', 'strongly_supported', 'rejected')", name="ck_attribution_claims_4"),
        sa.CheckConstraint('version >= 1', name="ck_attribution_claims_5"),
        sa.CheckConstraint('length(trim(scope_note)) > 0', name="ck_attribution_claims_6"),
        sa.CheckConstraint('valid_from IS NULL OR valid_to IS NULL OR valid_to >= valid_from', name="ck_attribution_claims_7"),
        sa.CheckConstraint('(assessed_at IS NULL AND assessed_by IS NULL) OR (assessed_at IS NOT NULL AND assessed_by IS NOT NULL)', name="ck_attribution_claims_8"),
        sa.CheckConstraint("assessment = 'unassessed' OR (length(trim(assessment_rationale)) > 0 AND assessed_at IS NOT NULL AND assessed_by IS NOT NULL)", name="ck_attribution_claims_9"),
        sa.CheckConstraint("chain != 'ethereum' OR subject_ref = lower(subject_ref)", name="ck_attribution_claims_10"),
        sa.CheckConstraint("chain != 'bitcoin' OR lower(substr(subject_ref,1,3)) != 'bc1' OR subject_ref = lower(subject_ref)", name="ck_attribution_claims_11"),
        sa.UniqueConstraint('subject_type', 'chain', 'subject_ref', 'relationship', 'entity_id', name="uq_attribution_claims_1"),
    )
    op.create_index('ix_attribution_claims_1', 'attribution_claims', ['chain', 'subject_ref', 'archived_at'], unique=False)
    op.create_index('ix_attribution_claims_2', 'attribution_claims', ['entity_id', 'archived_at', 'id'], unique=False)
    op.create_index('ix_attribution_claims_3', 'attribution_claims', ['assessment', 'needs_review', 'updated_at', 'id'], unique=False)

    op.create_table('attribution_evidence',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('evidence_type', sa.String(32), nullable=False),
        sa.Column('title', sa.String(255), nullable=False),
        sa.Column('summary', sa.Text, nullable=False),
        sa.Column('excerpt', sa.Text, nullable=True),
        sa.Column('source_name', sa.String(255), nullable=False),
        sa.Column('source_url', sa.Text, nullable=True),
        sa.Column('source_locator', sa.String(512), nullable=True),
        sa.Column('source_catalog_id', sa.String(128), nullable=True),
        sa.Column('origin', sa.String(32), nullable=False),
        sa.Column('collection_method', sa.String(32), nullable=False),
        sa.Column('published_on', sa.Date, nullable=True),
        sa.Column('observed_on', sa.Date, nullable=True),
        sa.Column('captured_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('captured_by', sa.String(128), nullable=False),
        sa.Column('analyst_note', sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column('source_reliability', sa.String(16), nullable=False, server_default=sa.text("'unassessed'")),
        sa.Column('reliability_rationale', sa.Text, nullable=False, server_default=sa.text("''")),
        sa.Column('origin_group', sa.String(128), nullable=True),
        sa.Column('origin_label_id', sa.String(36), sa.ForeignKey('labels.id', name='fk_attribution_evidence_origin_label_id', ondelete="RESTRICT"), nullable=True),
        sa.Column('origin_match_id', sa.String(36), sa.ForeignKey('kyc_matches.id', name='fk_attribution_evidence_origin_match_id', ondelete="RESTRICT"), nullable=True),
        sa.Column('metadata_json', sa.JSON, nullable=False, server_default=sa.text("'{}'")),
        sa.Column('content_sha256', sa.String(64), nullable=False),
        sa.CheckConstraint("evidence_type IN ('official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'research_snapshot', 'label_snapshot', 'analyst_observation')", name="ck_attribution_evidence_1"),
        sa.CheckConstraint("origin IN ('public_osint', 'analyst_added', 'commercial_proprietary', 'privileged_nonpublic')", name="ck_attribution_evidence_2"),
        sa.CheckConstraint("collection_method IN ('analyst_entry', 'label_snapshot', 'research_snapshot')", name="ck_attribution_evidence_3"),
        sa.CheckConstraint("source_reliability IN ('unassessed', 'reliable', 'uncertain', 'unreliable')", name="ck_attribution_evidence_4"),
        sa.CheckConstraint('length(trim(title)) > 0 AND length(trim(summary)) > 0 AND length(trim(source_name)) > 0', name="ck_attribution_evidence_5"),
        sa.CheckConstraint('length(content_sha256) = 64', name="ck_attribution_evidence_6"),
        sa.CheckConstraint("source_reliability = 'unassessed' OR length(trim(reliability_rationale)) > 0", name="ck_attribution_evidence_7"),
        sa.CheckConstraint("(collection_method = 'analyst_entry' AND origin_label_id IS NULL AND origin_match_id IS NULL AND evidence_type NOT IN ('label_snapshot','research_snapshot')) OR (collection_method = 'label_snapshot' AND origin_label_id IS NOT NULL AND origin_match_id IS NULL AND evidence_type = 'label_snapshot') OR (collection_method = 'research_snapshot' AND origin_match_id IS NOT NULL AND origin_label_id IS NULL AND evidence_type = 'research_snapshot')", name="ck_attribution_evidence_8"),
        sa.CheckConstraint("(evidence_type = 'analyst_observation' AND length(trim(analyst_note)) > 0) OR (evidence_type != 'analyst_observation' AND (length(trim(coalesce(source_url,''))) > 0 OR length(trim(coalesce(source_locator,''))) > 0))", name="ck_attribution_evidence_9"),
    )
    op.create_index('ix_attribution_evidence_1', 'attribution_evidence', ['captured_at', 'id'], unique=False)
    op.create_index('ix_attribution_evidence_2', 'attribution_evidence', ['content_sha256'], unique=False)
    op.create_index('ix_attribution_evidence_3', 'attribution_evidence', ['source_catalog_id', 'captured_at'], unique=False)
    op.create_index('ix_attribution_evidence_4', 'attribution_evidence', ['origin_label_id'], unique=False)
    op.create_index('ix_attribution_evidence_5', 'attribution_evidence', ['origin_match_id'], unique=False)
    op.create_index('ix_attribution_evidence_6', 'attribution_evidence', ['origin_group'], unique=False)

    op.create_table('attribution_claim_evidence',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('claim_id', sa.String(36), sa.ForeignKey('attribution_claims.id', name='fk_attribution_claim_evidence_claim_id', ondelete="RESTRICT"), nullable=False),
        sa.Column('evidence_id', sa.String(36), sa.ForeignKey('attribution_evidence.id', name='fk_attribution_claim_evidence_evidence_id', ondelete="RESTRICT"), nullable=False),
        sa.Column('stance', sa.String(16), nullable=False),
        sa.Column('directness', sa.String(16), nullable=False),
        sa.Column('rationale', sa.Text, nullable=False),
        sa.Column('added_by', sa.String(128), nullable=False),
        sa.Column('added_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('withdrawn_at', sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("stance IN ('supports', 'contradicts', 'context')", name="ck_attribution_claim_evidence_1"),
        sa.CheckConstraint("directness IN ('direct', 'indirect', 'context')", name="ck_attribution_claim_evidence_2"),
        sa.CheckConstraint("stance != 'context' OR directness = 'context'", name="ck_attribution_claim_evidence_3"),
        sa.CheckConstraint('length(trim(rationale)) > 0', name="ck_attribution_claim_evidence_4"),
        sa.UniqueConstraint('claim_id', 'evidence_id', name="uq_attribution_claim_evidence_1"),
    )
    op.create_index('ix_attribution_claim_evidence_1', 'attribution_claim_evidence', ['evidence_id', 'claim_id'], unique=False)
    op.create_index('ix_attribution_claim_evidence_2', 'attribution_claim_evidence', ['claim_id', 'withdrawn_at'], unique=False)

    op.create_table('attribution_events',
        sa.Column('id', sa.String(36), nullable=False, primary_key=True),
        sa.Column('entity_id', sa.String(36), sa.ForeignKey('attribution_entities.id', name='fk_attribution_events_entity_id', ondelete="RESTRICT"), nullable=True),
        sa.Column('claim_id', sa.String(36), sa.ForeignKey('attribution_claims.id', name='fk_attribution_events_claim_id', ondelete="RESTRICT"), nullable=True),
        sa.Column('evidence_id', sa.String(36), sa.ForeignKey('attribution_evidence.id', name='fk_attribution_events_evidence_id', ondelete="RESTRICT"), nullable=True),
        sa.Column('sequence', sa.Integer, nullable=False),
        sa.Column('event_type', sa.String(32), nullable=False),
        sa.Column('actor_kind', sa.String(16), nullable=False),
        sa.Column('actor_ref', sa.String(128), nullable=False),
        sa.Column('occurred_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('reason', sa.Text, nullable=False),
        sa.Column('payload', sa.JSON, nullable=False),
        sa.CheckConstraint('sequence >= 1', name="ck_attribution_events_1"),
        sa.CheckConstraint("event_type IN ('created', 'descriptor_changed', 'scope_changed', 'evidence_linked', 'evidence_changed', 'evidence_withdrawn', 'evidence_restored', 'assessment_changed', 'review_required', 'archived', 'restored')", name="ck_attribution_events_2"),
        sa.CheckConstraint("actor_kind IN ('analyst', 'system')", name="ck_attribution_events_3"),
        sa.CheckConstraint('(CASE WHEN entity_id IS NULL THEN 0 ELSE 1 END + CASE WHEN claim_id IS NULL THEN 0 ELSE 1 END + CASE WHEN evidence_id IS NULL THEN 0 ELSE 1 END) = 1', name="ck_attribution_events_4"),
        sa.CheckConstraint('length(trim(reason)) > 0', name="ck_attribution_events_5"),
        sa.CheckConstraint("evidence_id IS NULL OR (event_type = 'created' AND sequence = 1)", name="ck_attribution_events_6"),
        sa.CheckConstraint("entity_id IS NULL OR event_type IN ('created','descriptor_changed','archived','restored')", name="ck_attribution_events_7"),
        sa.UniqueConstraint('entity_id', 'sequence', name="uq_attribution_events_1"),
        sa.UniqueConstraint('claim_id', 'sequence', name="uq_attribution_events_2"),
        sa.UniqueConstraint('evidence_id', 'sequence', name="uq_attribution_events_3"),
    )
    op.create_index('ix_attribution_events_1', 'attribution_events', ['occurred_at', 'id'], unique=False)

    op.execute("CREATE TRIGGER attribution_evidence_no_update BEFORE UPDATE ON attribution_evidence BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END")
    op.execute("CREATE TRIGGER attribution_evidence_no_delete BEFORE DELETE ON attribution_evidence BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END")
    op.execute("CREATE TRIGGER attribution_evidence_no_replace BEFORE INSERT ON attribution_evidence WHEN EXISTS (SELECT 1 FROM attribution_evidence WHERE id = NEW.id) BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END")
    op.execute("CREATE TRIGGER attribution_events_no_update BEFORE UPDATE ON attribution_events BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END")
    op.execute("CREATE TRIGGER attribution_events_no_delete BEFORE DELETE ON attribution_events BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END")
    op.execute("CREATE TRIGGER attribution_events_no_replace BEFORE INSERT ON attribution_events WHEN EXISTS (SELECT 1 FROM attribution_events WHERE id = NEW.id OR (sequence = NEW.sequence AND (entity_id = NEW.entity_id OR claim_id = NEW.claim_id OR evidence_id = NEW.evidence_id))) BEGIN SELECT RAISE(ABORT, 'Attribution evidence and events are immutable'); END")


def downgrade():
    connection = op.get_bind()
    for table in ['attribution_entities', 'attribution_claims', 'attribution_evidence', 'attribution_claim_evidence', 'attribution_events']:
        if connection.execute(sa.text("SELECT COUNT(*) FROM " + table)).scalar_one():
            raise RuntimeError("Cannot downgrade populated attribution history; use an explicitly approved backup recovery procedure")
    op.execute("DROP TRIGGER IF EXISTS attribution_evidence_no_update")
    op.execute("DROP TRIGGER IF EXISTS attribution_evidence_no_delete")
    op.execute("DROP TRIGGER IF EXISTS attribution_evidence_no_replace")
    op.execute("DROP TRIGGER IF EXISTS attribution_events_no_update")
    op.execute("DROP TRIGGER IF EXISTS attribution_events_no_delete")
    op.execute("DROP TRIGGER IF EXISTS attribution_events_no_replace")
    op.drop_table('attribution_events')
    op.drop_table('attribution_claim_evidence')
    op.drop_table('attribution_evidence')
    op.drop_table('attribution_claims')
    op.drop_table('attribution_entities')
