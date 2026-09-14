SUBJECT_KINDS = ('blockchain_address','url','domain','repository','annotation')
RESULT_KINDS = ('candidate_evidence','candidate_identifier','candidate_relationship')
PREDICATES = ('mentioned_at','repository_contains','explorer_labeled_as','locally_labeled_as','publicly_listed_by','reverse_name_record','resolves_to','registration_record_for','certificate_names','observed_at','archived_at','uses_tracking_id','advertises_at')
RUN_STATES = ('queued','running','completed','partial','failed','cancelled','interrupted')
SOURCE_STATES = ('queued','running','succeeded','cache_hit','manual_ready','unavailable','rate_limited','budget_exhausted','timeout','failed','cancelled','interrupted')
REVIEWS = ('unreviewed','relevant','irrelevant')
COSTS = ('FREE_LOCAL','FREE_REMOTE','LIMITED_FREE','PAID')
OBSERVATION_KINDS = ('search_result','code_search_result','local_label_snapshot','verified_page_observation','explorer_annotation','name_service_record','research_result','archive_index_record','analyst_capture')
VERIFICATIONS = ('not_checked','exact_in_excerpt','exact_in_document','technical_verified','mismatch','not_applicable')
COVERAGE = ('bounded','provider_incomplete','limit_reached','unknown')
ERRORS = ('configuration_unavailable','entitlement_unavailable','retention_not_permitted','rate_limited','budget_exhausted','timeout','transport_failed','invalid_provider_response','unsupported_input','cancelled','interrupted','storage_unavailable')
TERMINAL_RUNS = frozenset(RUN_STATES)-{'queued','running'}
TERMINAL_SOURCES = frozenset(SOURCE_STATES)-{'queued','running'}
# Future predicates are reserved in the schema; only these type pairs are active.
PAIRS = {'mentioned_at':(('blockchain_address','url'),),
         'publicly_listed_by':(('blockchain_address','url'),),
         'repository_contains':(('repository','blockchain_address'),),
         'locally_labeled_as':(('blockchain_address','annotation'),),
         'explorer_labeled_as':(('blockchain_address','annotation'),)}
