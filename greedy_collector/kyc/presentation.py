"""Safe capability metadata and research-only response/persistence sanitization."""
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode, quote, quote_plus
from ..config import get_settings
from .sources import SOURCE_CATALOG

SENSITIVE = {'apikey', 'key', 'authorization', 'password', 'secret', 'token', 'accesstoken', 'signature', 'xapikey', 'xamzsignature'}

def sensitive_name(name):
    return str(name).lower().replace('_','').replace('-','') in SENSITIVE

def source_capabilities():
    settings=get_settings()
    rows=[]
    for source in SOURCE_CATALOG:
        domain=source.mode=='api' and source.category=='domain'
        inputs=['domain'] if domain else ['name']
        if source.mode=='manual':
            inputs=[] if '{query}' not in source.search_url else ['domain','name (fallback)'] if source.category in {'domain','network'} else ['name']
        rows.append({'id':source.id,'name':source.name,'category':source.category,'mode':source.mode,
            'credential_env':source.credential_env,'note':source.note,'input_fields':inputs,'domain_required':domain,
            'credential_required':source.id in {'opensanctions','virustotal'},
            'credential_configured':bool(getattr(settings,source.credential_env.lower(),'')) if source.credential_env else None})
    return {'sources':rows}

def sanitize_research(value):
    settings=get_settings()
    secrets=set()
    for name,secret in settings.model_dump().items():
        if ('api_key' in name or 'password' in name) and isinstance(secret,str) and secret:
            secrets.update([secret,quote(secret,safe=''),quote_plus(secret)])
    def clean(item):
        if isinstance(item,dict):return {key:'[redacted]' if sensitive_name(key) else clean(val) for key,val in item.items()}
        if isinstance(item,(list,tuple)):return [clean(val) for val in item]
        if not isinstance(item,str):return item
        for secret in sorted(secrets,key=len,reverse=True):item=item.replace(secret,'[redacted]')
        if item.lower().startswith(('https://','http://')):
            try:
                url=urlsplit(item)
                query=[(key,'[redacted]' if sensitive_name(key) else val) for key,val in parse_qsl(url.query,keep_blank_values=True)]
                netloc=url.netloc.rsplit('@',1)[-1]
                item=urlunsplit((url.scheme,netloc,url.path,urlencode(query),url.fragment))
            except ValueError:return '[unavailable source URL]'
        return item
    return clean(value)
