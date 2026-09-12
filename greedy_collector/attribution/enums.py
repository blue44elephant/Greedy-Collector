"""Closed AT-1 domain vocabularies; no probability or ownership enum."""

ENTITY_TYPES = ('organization', 'person', 'service', 'protocol', 'public_body', 'online_identity', 'unknown')
RELATIONSHIPS = ('operated_by', 'controlled_by', 'publicly_declared_by')
ASSESSMENTS = ('unassessed', 'possible', 'supported', 'strongly_supported', 'rejected')
EVIDENCE_TYPES = ('official_disclosure', 'public_record', 'explorer_annotation', 'public_post', 'repository_record', 'research_snapshot', 'label_snapshot', 'analyst_observation')
ORIGINS = ('public_osint', 'analyst_added', 'commercial_proprietary', 'privileged_nonpublic')
COLLECTION_METHODS = ('analyst_entry', 'label_snapshot', 'research_snapshot')
RELIABILITIES = ('unassessed', 'reliable', 'uncertain', 'unreliable')
STANCES = ('supports', 'contradicts', 'context')
DIRECTNESS = ('direct', 'indirect', 'context')
EVENT_TYPES = ('created', 'descriptor_changed', 'scope_changed', 'evidence_linked', 'evidence_changed', 'evidence_withdrawn', 'evidence_restored', 'assessment_changed', 'review_required', 'archived', 'restored')
ACTOR_KINDS = ('analyst', 'system')
