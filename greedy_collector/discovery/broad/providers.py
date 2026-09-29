"""Typed search provider boundary. No arbitrary URL retrieval or recursion."""
from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol
from datetime import datetime, timezone
from urllib.parse import urlsplit, urlunsplit, unquote
import asyncio, html, ipaddress, os, re
import httpx
from ..domain import canonical_subject, public_url, clean, DiscoveryError
from ..executors import ExecutionSignal
from ..schemas import Batch

class QueryType(str, Enum):
    EXACT_WALLET='EXACT_WALLET'
    EXACT_TXID='EXACT_TXID'
    EXACT_ALIAS='EXACT_ALIAS'
    DOMAIN='DOMAIN'
    URL='URL'
    ENTITY_NAME='ENTITY_NAME'

@dataclass(frozen=True)
class DiscoveryQuery:
    chain:str
    wallet:str
    limit:int=20
    query_type:QueryType=QueryType.EXACT_WALLET
    def __post_init__(self):
        if self.query_type!=QueryType.EXACT_WALLET:raise DiscoveryError('Only exact wallet execution is implemented')
        if type(self.limit) is not int or not 1<=self.limit<=50:raise DiscoveryError('Search bound must be 1 to 50')
        object.__setattr__(self,'wallet',canonical_subject('blockchain_address',self.chain,self.wallet)['canonical_value'])
    @property
    def text(self):return '"'+self.wallet+'"'

@dataclass(frozen=True)
class DiscoveryCandidate:
    kind:str
    value:str
    method:str
    confidence_type:str

@dataclass(frozen=True)
class DiscoveryObservation:
    url:str
    title:str
    snippet:str
    rank:int

@dataclass
class DiscoveryExecutionResult:
    observations:list[DiscoveryObservation]=field(default_factory=list)
    truncated:bool=False
    reason:str|None=None
    metadata:dict=field(default_factory=dict)

class DiscoveryProvider(Protocol):
    id:str
    async def search(self,query:DiscoveryQuery,context)->DiscoveryExecutionResult:...

class ProviderRegistry:
    def __init__(self):self.providers={}
    def register(self,provider):
        if not re.fullmatch(r'[a-z][a-z0-9_]{0,63}',provider.id) or provider.id in self.providers:raise ValueError('Duplicate or invalid provider')
        self.providers[provider.id]=provider
    def get(self,identifier):return self.providers[identifier]

def canonical_url(value):
    value=public_url(value)
    p=urlsplit(value);host=p.hostname
    if host=='localhost' or host.endswith(('.localhost','.local','.internal')):raise DiscoveryError('Nonpublic URL')
    try:address=ipaddress.ip_address(host)
    except ValueError:address=None
    if address is not None and not address.is_global:raise DiscoveryError('Nonpublic URL')
    return urlunsplit((p.scheme,p.netloc,p.path,p.query,''))

def category(host):
    host=host.lower()
    matches=lambda domains:any(host==d or host.endswith('.'+d) for d in domains)
    if matches(['ofac.treasury.gov','sanctionssearch.ofac.treas.gov']):return 'sanctions/watchlist'
    if matches(['courtlistener.com','supremecourt.gov','uscourts.gov']):return 'court/legal'
    if host.endswith(('.gov','.gov.uk','.gov.in','.europa.eu')):return 'government/regulator'
    for kind,domains in [('blockchain explorer',['etherscan.io','basescan.org','arbiscan.io','bscscan.com','polygonscan.com','blockstream.info','solscan.io']),('code repository',['github.com','gitlab.com']),('forum/community',['reddit.com','bitcointalk.org']),('news/media',['reuters.com','apnews.com','bbc.com']),('research/report',['arxiv.org','doi.org']),('social/public profile',['x.com','twitter.com','mastodon.social']),('marketplace reference',['opensea.io'])]:
        if matches(domains):return kind
    return 'other'

def exact_match(query,text):
    # Case normalization follows the canonical wallet's chain; full token boundaries required.
    fold=query.chain in ('ethereum','base','arbitrum','bsc','polygon') or query.wallet.startswith(('bc1','ltc1'))
    return re.search(r'(?<![A-Za-z0-9])'+re.escape(query.wallet)+r'(?![A-Za-z0-9])',text,re.I if fold else 0) is not None

def candidates(text,host,exact):
    found=[DiscoveryCandidate('domain',host,'URL hostname','STRUCTURED_SOURCE_FIELD')]
    if exact:
        # Explicit labelled source text only. No NER, name guessing or proximity inference.
        for kind,pattern in [('alias',r'(?i)\b(?:alias|handle|username)\s*:\s*(@?[A-Za-z0-9_.-]{2,64})'),('entity',r'(?i)\b(?:organization|organisation|service|project|entity)\s*:\s*([A-Za-z][A-Za-z0-9 &._-]{1,79})(?=[;\n]|$)')]:
            for match in re.finditer(pattern,text):found.append(DiscoveryCandidate(kind,match.group(1).strip(),'Explicit labelled source text','EXPLICIT_SOURCE_TEXT'))
    return list({(c.kind,c.value):c for c in found}.values())[:10]

def normalize_result(provider,query,item,retrieved_at,metadata=None):
    url=canonical_url(item.url);host=urlsplit(url).hostname
    title=html.unescape(re.sub('<[^>]*>','',item.title))[:255] or 'Public search result'
    snippet=html.unescape(re.sub('<[^>]*>','',item.snippet))[:2000]
    text=title+'\n'+snippet+'\n'+unquote(url)
    exact=exact_match(query,text)
    snapshot=clean(dict(schema_version=1,provider=provider,query_type=query.query_type.value,query=query.text,chain=query.chain,wallet=query.wallet,
        canonical_url=url,hostname=host,registrable_domain=None,domain_note='Hostname only; no public-suffix guessing or WHOIS lookup',rank=item.rank,
        exact_match=exact,source_category=category(host),title=title,snippet=snippet,metadata_only=True,
        candidates=[c.__dict__ for c in candidates(title+'\n'+snippet,host,exact)],
        quality={'provenance':'search API metadata','wallet_present':exact,'institutional_host':category(host) in ('government/regulator','court/legal','sanctions/watchlist'),
            'structure':'search result metadata','primary_secondary':'unknown','retrieval_timestamp_available':True,'source_timestamp_available':False,'source_reachability':'not checked'},
        provider_metadata=metadata or {},
        bounds={'max_results':min(query.limit,20) if provider=='tavily_search' else query.limit,'max_requests':1 if provider=='tavily_search' else 3,'timeout_seconds':15}))
    return {'kind':'candidate_evidence' if exact else 'candidate_identifier','predicate':'mentioned_at',
        'from':{'kind':'blockchain_address','namespace':query.chain,'value':query.wallet},
        'to':{'kind':'url','namespace':'https','value':url},'fact_key':{'query_type':'EXACT_WALLET','exact_match':exact},
        'observation':{'kind':'search_result','source_record_key':url[:512], 'source_url':url,'title':title,'summary':snippet or 'Search metadata only; no source content fetched.',
            'excerpt':snippet or None,'excerpt_complete':False,'verification':'exact_in_excerpt' if exact else 'not_checked',
            'match_context':{'exact_match':exact,'method':'canonical wallet token in returned title/snippet/URL'},'source_class':category(host),
            'retrieved_at':retrieved_at,'source_snapshot':snapshot}}

class BraveProvider:
    id='brave_search'
    async def search(self,query,context):
        key=os.getenv('BRAVE_SEARCH_API_KEY','').strip()
        if not key:raise ExecutionSignal('configuration_unavailable')
        if os.getenv('BRAVE_SEARCH_STORAGE_ALLOWED','').lower() not in ('true','1','yes'):raise ExecutionSignal('entitlement_unavailable')
        result=DiscoveryExecutionResult();count=min(query.limit,20)
        for page in range(3):
            async def request():
                async with httpx.AsyncClient(timeout=15,follow_redirects=False,trust_env=False) as client:
                    async with client.stream('GET','https://api.search.brave.com/res/v1/web/search',params={'q':query.text,'count':count,'offset':page,'text_decorations':'false','spellcheck':'false','result_filter':'web'},headers={'X-Subscription-Token':key,'Accept':'application/json'}) as response:
                        if response.status_code==429:raise ExecutionSignal('rate_limited')
                        if response.status_code in (401,403):raise ExecutionSignal('configuration_unavailable')
                        if response.status_code!=200:raise ExecutionSignal('transport_failed')
                        body=bytearray()
                        async for chunk in response.aiter_bytes():
                            context.checkpoint()
                            body.extend(chunk)
                            if len(body)>1048576:raise ExecutionSignal('invalid_provider_response')
                        import json
                        try:data=json.loads(body)
                        except (ValueError,RecursionError):raise ExecutionSignal('invalid_provider_response') from None
                        if not isinstance(data,dict) or not isinstance(data.get('web',{}),dict) or not isinstance(data.get('web',{}).get('results',[]),list) or not isinstance(data.get('query',{}),dict):raise ExecutionSignal('invalid_provider_response')
                        return data
            try:data=await context.request(request,request_class='query' if page==0 else 'page')
            except (httpx.TimeoutException,asyncio.TimeoutError):
                if result.observations:result.truncated=True;result.reason='later_page_timeout';break
                raise ExecutionSignal('timeout') from None
            except (httpx.HTTPError,ExecutionSignal) as exc:
                if result.observations:result.truncated=True;result.reason='later_page_failed';break
                if isinstance(exc,ExecutionSignal):raise
                raise ExecutionSignal('transport_failed') from None
            if not isinstance(data,dict) or not isinstance(data.get('web',{}),dict):raise ExecutionSignal('invalid_provider_response')
            rows=data.get('web',{}).get('results',[])
            if not isinstance(rows,list):raise ExecutionSignal('invalid_provider_response')
            for index,row in enumerate(rows[:count]):
                if not isinstance(row,dict) or not all(isinstance(row.get(k,''),str) for k in ('url','title','description')):continue
                result.observations.append(DiscoveryObservation(row.get('url',''),row.get('title',''),row.get('description',''),page*count+index+1))
                if len(result.observations)>=query.limit:break
            query_metadata=data.get('query',{})
            if not isinstance(query_metadata,dict):raise ExecutionSignal('invalid_provider_response')
            more=bool(query_metadata.get('more_results_available'))
            if len(result.observations)>=query.limit:
                result.truncated=more or index+1<len(rows);result.reason='result_cap' if result.truncated else None;break
            if not more:break
        else:result.truncated=True;result.reason='request_cap'
        return result

from .tavily import TavilyProvider
from . import is_web_source
PROVIDERS=ProviderRegistry();PROVIDERS.register(BraveProvider());PROVIDERS.register(TavilyProvider())
class WebSearchExecutor:
    async def execute(self,context):
        query=DiscoveryQuery(context.subject['namespace'],context.subject['canonical_value'],context.parameters['max_results'])
        result=await PROVIDERS.get(context.source_id).search(query,context)
        now=datetime.now(timezone.utc);records=[];seen=set();skipped=0
        for item in result.observations[:query.limit]:
            try:record=normalize_result(context.source_id,query,item,now,result.metadata)
            except DiscoveryError:skipped+=1;continue
            url=record['observation']['source_url']
            if url in seen:continue
            seen.add(url);records.append(record)
        return Batch(records=records,coverage='provider_incomplete' if result.truncated or skipped else 'bounded',quota={'diagnostic':result.reason or ('unsafe_results_omitted' if skipped else 'bounded_search')})

def promotable(result,observation,source,subject):
    snap=observation.source_snapshot
    return (is_web_source(source.transform_id,source.source_id) and result.predicate=='mentioned_at' and observation.kind=='search_result'
        and snap.get('exact_match') is True and snap.get('chain')==subject.namespace and snap.get('wallet')==subject.canonical_value
        and observation.verification=='exact_in_excerpt' and observation.source_url==snap.get('canonical_url'))
