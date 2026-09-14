"""Strict local identities and sanitized material. No transport or execution."""
from datetime import date,datetime,timezone
import os,re,unicodedata
from urllib.parse import urlsplit,urlunsplit,quote,quote_plus
from pydantic import BaseModel,ConfigDict,Field,field_validator,model_validator
from ..attribution.domain import normalize_subject,json_safe,canonical_json,fingerprint,AttributionError
from ..attribution.handoff import safe_snapshot
from . import enums as e

class DiscoveryError(ValueError):pass
class Conflict(DiscoveryError):pass
class NotFound(DiscoveryError):pass
class SchemaUnavailable(DiscoveryError):pass

def choice(value,values):
    if value not in values:raise DiscoveryError('Unsupported Discovery value')
    return value

def clean(value):
    try:
        result=safe_snapshot(value)
        secret=os.getenv('DISCOVERY_GITHUB_TOKEN','').strip()
        def redact(item):
            if isinstance(item,str) and secret:
                for variant in sorted({secret,quote(secret,safe=''),quote_plus(secret,safe='')},key=len,reverse=True):
                    item=item.replace(variant,'[redacted]')
                return item
            if isinstance(item,dict):return {k:redact(v) for k,v in item.items()}
            if isinstance(item,list):return [redact(v) for v in item]
            return item
        result=redact(result)
        if len(canonical_json(result).encode('utf-8'))>16384:raise DiscoveryError('Discovery snapshot exceeds 16 KiB')
        return result
    except AttributionError:raise DiscoveryError('Discovery material must contain bounded finite JSON') from None

def public_url(value):
    if not isinstance(value,str) or len(value)>2048 or any(ord(c)<33 for c in value):raise DiscoveryError('A safe public citation URL is required')
    safe=clean(value)
    if safe!=value:raise DiscoveryError('Unsafe citation URL')
    try:
        parts=urlsplit(value)
        if parts.scheme not in ('http','https') or not parts.hostname or parts.username or parts.password:raise ValueError()
        host=parts.hostname.encode('idna').decode('ascii').lower()
        if ':' in host:host='['+host+']'
        port=parts.port
        netloc=host+((':'+str(port)) if port and (parts.scheme,port) not in (('http',80),('https',443)) else '')
        return urlunsplit((parts.scheme.lower(),netloc,parts.path or '/',parts.query,parts.fragment))
    except (ValueError,UnicodeError):raise DiscoveryError('A safe public citation URL is required') from None

def canonical_subject(kind,namespace,value):
    choice(kind,e.SUBJECT_KINDS)
    if not isinstance(value,str) or not isinstance(namespace,str):raise DiscoveryError('Invalid subject')
    value=value.strip();namespace=namespace.strip()
    if not value or len(value)>2048 or not namespace or len(namespace)>128 or any(unicodedata.category(c).startswith('C') for c in value+namespace):raise DiscoveryError('Invalid subject')
    if kind=='blockchain_address':
        try:value=normalize_subject(namespace,value)
        except AttributionError:raise DiscoveryError('Address does not match the supported chain format') from None
    elif kind=='url':
        value=public_url(value);namespace=urlsplit(value).scheme
    elif kind=='domain':
        from ..schemas import KycQuery
        try:value=KycQuery.validate_research_domain(value)
        except ValueError:raise DiscoveryError('Invalid domain subject') from None
        namespace='dns'
    elif kind=='repository':
        if namespace!='github' or not re.fullmatch(r'[1-9][0-9]{0,19}',value):raise DiscoveryError('Repository subject requires stable GitHub numeric ID')
    elif kind=='annotation':
        if namespace not in ('gc-label','explorer') or not re.fullmatch(r'[a-zA-Z0-9:_-]{1,255}',value):raise DiscoveryError('Invalid annotation reference')
    identity={'kind':kind,'namespace':namespace,'canonical_value':value}
    return {**identity,'display_value':value,'normalization_version':1,'identity_sha256':fingerprint(identity)}

def subject_identity(row):return {k:row[k] for k in ('kind','namespace','canonical_value')}

def query_fingerprint(subject,transform,source,parameters,*,config_generation='1'):
    return fingerprint({'subject':subject_identity(subject),'transform_id':transform.id,'transform_version':transform.version,
        'source_id':source.id,'source_version':source.version,'parameters':parameters,
        'limits':{'max_results':transform.max_results,'max_requests':transform.max_requests,'deadline_seconds':transform.deadline_seconds,'max_bytes':transform.max_bytes},
        'matching_version':transform.matching_version,'policy':source.retention_policy_id,'config_generation':config_generation})

def result_identity(query,kind,predicate,start,end,fact_key):
    choice(kind,e.RESULT_KINDS);choice(predicate,e.PREDICATES)
    if (start['kind'],end['kind'] if end else None) not in e.PAIRS.get(predicate,()):raise DiscoveryError('Unsupported Discovery relationship type pair')
    fact=clean(fact_key)
    if not isinstance(fact,dict):raise DiscoveryError('Result fact key must be an object')
    identity={'query':subject_identity(query),'kind':kind,'predicate':predicate,'from':subject_identity(start),'to':subject_identity(end) if end else None,'fact_key':fact}
    return fact,fingerprint(identity)

def observation_fingerprint(payload,source):
    # Generated identities, retrieval clocks and provider ranking are not source content.
    excluded={'id','created_at','retrieved_at','result_id','execution_id','rank'}
    material={k:v for k,v in payload.items() if k not in excluded}
    if material.get('kind')=='code_search_result' and isinstance(material.get('source_snapshot'),dict):
        material['source_snapshot']={k:v for k,v in material['source_snapshot'].items() if k!='github_search_score'}
    return fingerprint({'source':source,'material':clean(material)})

class Input(BaseModel):model_config=ConfigDict(extra='forbid')

class ObservationInput(Input):
    source_record_key:str=Field(min_length=1,max_length=512)
    kind:str
    source_url:str|None=None
    source_locator:str|None=Field(default=None,max_length=512)
    title:str=Field(min_length=1,max_length=255)
    summary:str=Field(min_length=1,max_length=4000)
    excerpt:str|None=Field(default=None,max_length=4000)
    excerpt_complete:bool=False
    verification:str='not_checked'
    match_context:dict=Field(default_factory=dict)
    source_class:str='unknown'
    observed_at:datetime|None=None
    observed_on:date|None=None
    published_at:datetime|None=None
    published_on:date|None=None
    retrieved_at:datetime
    source_snapshot:dict
    origin_label_id:str|None=None
    origin_match_id:str|None=None
    @model_validator(mode='after')
    def validate_material(self):
        choice(self.kind,e.OBSERVATION_KINDS);choice(self.verification,e.VERIFICATIONS)
        if not self.title.strip() or not self.summary.strip():raise DiscoveryError('Nonblank observation material required')
        if self.source_url:self.source_url=public_url(self.source_url)
        if not self.source_url and not self.source_locator:raise DiscoveryError('A source locator is required')
        if self.observed_at and self.observed_on or self.published_at and self.published_on:raise DiscoveryError('Source date precision must be explicit')
        if self.origin_label_id and self.origin_match_id:raise DiscoveryError('Observation has conflicting local origins')
        if self.kind=='local_label_snapshot' and not self.origin_label_id:raise DiscoveryError('Label observation requires actual Label ID')
        if self.origin_label_id and self.kind!='local_label_snapshot':raise DiscoveryError('Invalid Label origin')
        if self.origin_match_id and self.kind!='research_result':raise DiscoveryError('Invalid Research origin')
        if self.verification in ('exact_in_excerpt','exact_in_document','technical_verified') and not self.match_context:raise DiscoveryError('Verification requires source context')
        if self.kind=='search_result' and self.verification in ('exact_in_document','technical_verified'):raise DiscoveryError('Search snippets are not verified documents')
        for field in ('observed_at','published_at','retrieved_at'):
            value=getattr(self,field)
            if value:setattr(self,field,value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc))
        return self
