"""Bounded public HTTP retrieval with DNS validation and IP-pinned connections."""
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from html.parser import HTMLParser
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlunsplit, urljoin, unquote
import httpx
from ..domain import clean, DiscoveryError

MAX_BYTES = 5 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT = 20
VERSION = 'gc-public-capture-1'
FAILURES = ('dns_failure','blocked_private_address','blocked_scheme','blocked_onion',
    'redirect_blocked','too_many_redirects','timeout','response_too_large',
    'unsupported_content_type','authentication_required','rate_limited','http_error',
    'invalid_response','network_error')

class CaptureFailure(Exception):
    def __init__(self, code):
        assert code in FAILURES
        self.code = code
        super().__init__(code)


def public_ip(value):
    try:
        ip = ipaddress.ip_address(value)
    except ValueError:
        raise CaptureFailure('blocked_private_address') from None
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        raise CaptureFailure('blocked_private_address')
    if isinstance(ip, ipaddress.IPv6Address):
        if ip.ipv4_mapped or ip.sixtofour or ip.teredo or ip in ipaddress.ip_network('64:ff9b::/96') or ip in ipaddress.ip_network('64:ff9b:1::/48'):
            raise CaptureFailure('blocked_private_address')
    return str(ip)


def safe_url(value):
    if not isinstance(value,str) or len(value)>2048 or '\\' in value or any(ord(c)<33 or ord(c)==127 for c in value):
        raise CaptureFailure('invalid_response')
    try:
        p=urlsplit(value)
        if p.scheme not in ('http','https'):raise CaptureFailure('blocked_scheme')
        host=p.hostname
        if not host or p.username is not None or p.password is not None:raise CaptureFailure('authentication_required' if p.username is not None else 'invalid_response')
        if '%' in host:raise CaptureFailure('blocked_private_address')
        host=host.rstrip('.').encode('idna').decode('ascii').lower()
        if host=='onion' or host.endswith('.onion'):raise CaptureFailure('blocked_onion')
        if host in ('localhost','metadata','metadata.google.internal') or host.endswith(('.localhost','.local','.internal','.lan','.home')) or '.' not in host and ':' not in host:
            raise CaptureFailure('blocked_private_address')
        port=p.port or (443 if p.scheme=='https' else 80)
        if port not in (80,443):raise CaptureFailure('blocked_private_address')
        try:ipaddress.ip_address(host)
        except ValueError:
            if not re.fullmatch(r'[a-z0-9.-]+',host):raise CaptureFailure('invalid_response')
        else:public_ip(host)
        authority=('['+host+']' if ':' in host else host)
        if port != (443 if p.scheme=='https' else 80):authority+=':'+str(port)
        result=urlunsplit((p.scheme,authority,p.path or '/',p.query,''))
        if clean(result)!=result or clean(unquote(result))!=unquote(result):raise CaptureFailure('authentication_required')
        return result,host,port
    except (ValueError,UnicodeError,DiscoveryError):
        raise CaptureFailure('invalid_response') from None


async def resolve(host,port):
    try:
        rows=await asyncio.get_running_loop().getaddrinfo(host,port,type=socket.SOCK_STREAM,proto=socket.IPPROTO_TCP)
    except (OSError,UnicodeError):raise CaptureFailure('dns_failure') from None
    addresses=sorted({public_ip(row[4][0]) for row in rows})
    if not addresses:raise CaptureFailure('dns_failure')
    return addresses


class TextExtractor(HTMLParser):
    excluded={'script','style','noscript','template','iframe','object','embed','svg','canvas'}
    void={'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    blocks={'p','div','section','article','header','footer','h1','h2','h3','h4','h5','h6','tr','td','th','li','br','hr','title'}
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack=[];self.parts=[];self.titles=[]
    def handle_starttag(self,tag,attrs):
        hidden=tag in self.excluded or any(k=='hidden' or k=='aria-hidden' and v=='true' for k,v in attrs)
        hidden=hidden or bool(self.stack and self.stack[-1][1])
        if tag not in self.void:self.stack.append((tag,hidden))
        if not hidden and tag in self.blocks:self.parts.append('\n')
    def handle_startendtag(self,tag,attrs):
        self.handle_starttag(tag,attrs)
        if tag not in self.void:self.handle_endtag(tag)
    def handle_endtag(self,tag):
        for i in range(len(self.stack)-1,-1,-1):
            if self.stack[i][0]==tag:
                self.stack=self.stack[:i];break
        if tag in self.blocks:self.parts.append('\n')
    def handle_data(self,data):
        if self.stack and self.stack[-1][1]:return
        if any(t=='title' for t,_ in self.stack):self.titles.append(data)
        if not any(t=='head' for t,_ in self.stack) or any(t=='title' for t,_ in self.stack):self.parts.append(data)


def extract(body,content_type,charset='utf-8'):
    # A small encoding allowlist avoids stateful/custom Python codecs.
    charset=charset.lower().strip('"').replace('_','-')
    if charset not in ('utf-8','utf8','us-ascii','ascii','iso-8859-1','latin-1','windows-1252'):charset='utf-8'
    decoded=body.decode(charset,errors='replace')
    if content_type=='text/html':
        parser=TextExtractor();parser.feed(decoded);parser.close()
        text=''.join(parser.parts);title=' '.join(''.join(parser.titles).split())[:255] or None
    else:text=decoded;title=None
    text='\n'.join(' '.join(line.split()) for line in text.splitlines())
    text=re.sub(r'\n{3,}','\n\n',text).strip()
    return title,text


@dataclass
class Retrieved:
    final_url:str|None=None
    redirects:list=field(default_factory=list)
    retrieved_at:str=field(default_factory=lambda:datetime.now(timezone.utc).isoformat())
    http_status:int|None=None
    content_type:str|None=None
    declared_length:int|None=None
    byte_count:int=0
    body_sha256:str|None=None
    title:str|None=None
    text:str=''
    status:str='failed'
    truncated:bool=False
    failure_reason:str|None=None
    implementation_version:str=VERSION
    body:bytes|None=None


async def retrieve(url):
    output=Retrieved()
    try:
        async with asyncio.timeout(TIMEOUT):
            current=url
            for hop in range(MAX_REDIRECTS+1):
                try:
                    normalized,host,port=safe_url(current)
                    addresses=await resolve(host,port)
                except CaptureFailure as exc:
                    if hop:
                        output.redirects[-1]['blocked_reason']=exc.code
                        raise CaptureFailure('redirect_blocked') from None
                    raise
                # Pin the validated IP, keeping Host and verified TLS SNI at the
                # original hostname. HTTPX never performs a second hostname lookup.
                target=httpx.URL(normalized).copy_with(host=addresses[0])
                output.final_url=normalized
                headers={'Host':urlsplit(normalized).netloc,'User-Agent':'GreedyCollector/1 PublicSourceCapture',
                         'Accept':'text/html, text/plain','Accept-Encoding':'identity'}
                # Fresh client per hop: Set-Cookie is never replayed. No proxies,
                # ambient auth, browser state, retries or automatic redirects.
                async with httpx.AsyncClient(timeout=httpx.Timeout(10,connect=5),trust_env=False,follow_redirects=False) as client:
                    async with client.stream('GET',target,headers=headers,extensions={'sni_hostname':host}) as response:
                        output.http_status=response.status_code
                        if response.status_code in (301,302,303,307,308):
                            location=response.headers.get('location')
                            if not location:raise CaptureFailure('invalid_response')
                            destination=urljoin(normalized,location)
                            # Record only sanitized URLs. Unsafe raw headers never persist.
                            try:next_url,_,_=safe_url(destination)
                            except CaptureFailure as exc:
                                output.redirects.append({'from':normalized,'status':response.status_code,'to':None,'blocked_reason':exc.code})
                                raise CaptureFailure('redirect_blocked') from None
                            output.redirects.append({'from':normalized,'status':response.status_code,'to':next_url})
                            if hop==MAX_REDIRECTS:raise CaptureFailure('too_many_redirects')
                            current=next_url;continue
                        if response.status_code in (401,403,407):raise CaptureFailure('authentication_required')
                        if response.status_code==429:raise CaptureFailure('rate_limited')
                        if response.status_code!=200:raise CaptureFailure('http_error')
                        mime=response.headers.get('content-type','').split(';')[0].strip().lower()
                        output.content_type=mime[:128]
                        if mime not in ('text/html','text/plain'):raise CaptureFailure('unsupported_content_type')
                        if response.headers.get('content-encoding','identity').lower() not in ('','identity'):raise CaptureFailure('unsupported_content_type')
                        length=response.headers.get('content-length')
                        if length is not None:
                            if not re.fullmatch(r'[0-9]{1,15}',length):raise CaptureFailure('invalid_response')
                            output.declared_length=int(length)
                            if int(length)>MAX_BYTES:
                                output.truncated=True;raise CaptureFailure('response_too_large')
                        body=bytearray()
                        async for chunk in response.aiter_raw(chunk_size=65536):
                            output.byte_count+=len(chunk)
                            if output.byte_count>MAX_BYTES:
                                output.truncated=True;raise CaptureFailure('response_too_large')
                            body.extend(chunk)
                        if output.declared_length is not None and output.byte_count!=output.declared_length:raise CaptureFailure('invalid_response')
                        charset=re.search(r'charset=([^; ]+)',response.headers.get('content-type',''),re.I)
                        output.title,output.text=extract(bytes(body),mime,charset.group(1) if charset else 'utf-8')
                        output.body=bytes(body);output.body_sha256=sha256(body).hexdigest();output.status='captured'
                        return output
    except CaptureFailure as exc:output.failure_reason=exc.code
    except (TimeoutError,httpx.TimeoutException):output.failure_reason='timeout'
    except (httpx.RemoteProtocolError,ValueError):output.failure_reason='invalid_response'
    except (httpx.HTTPError,OSError):output.failure_reason='network_error'
    return output
