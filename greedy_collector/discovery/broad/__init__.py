"""Broad web provider identities shared by persistence and presentation."""
WEB_PROVIDERS = {'wallet.broad_web': 'brave_search', 'wallet.web_search.tavily': 'tavily_search'}

def is_web_source(transform_id, source_id):
    return WEB_PROVIDERS.get(transform_id) == source_id
