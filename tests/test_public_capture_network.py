"""All source retrieval is mocked at DNS and HTTP; no internet access."""
import asyncio
import hashlib
import socket
from types import SimpleNamespace
import httpx
import pytest
from greedy_collector.discovery.capture import network as n
BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'

class Bytes(httpx.AsyncByteStream):
    def __init__(self,data):self.data=data
    async def __aiter__(self):
        for pos in range(0,len(self.data),4096):yield self.data[pos:pos+4096]

@pytest.fixture
def wire(monkeypatch):
    state=SimpleNamespace(calls=[],dns=[],ip='93.184.215.14',status=200,headers={'content-type':'text/html'},body=('<title>Source title</title><h1>Notice</h1><p>'+BTC+'</p><script>BAD SCRIPT</script><style>BAD STYLE</style><noscript>BAD NOSCRIPT</noscript><iframe>BAD FRAME</iframe><a href="http://127.0.0.1/">Link text</a>').encode(),responses=[],error=None)
    async def dns(host,port,**kwargs):
        state.dns.append(host)
        if state.ip=='error':raise socket.gaierror('secret DNS failure')
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(state.ip,port))]
    async def handler(req):
        state.calls.append(req)
        assert req.url.host=='93.184.215.14', 'Transport must connect to the validated IP, never resolve a hostname twice'
        assert req.headers['User-Agent']=='GreedyCollector/1 PublicSourceCapture'
        assert 'authorization' not in req.headers and 'cookie' not in req.headers and 'proxy-authorization' not in req.headers
        if state.error:raise state.error
        if state.responses:
            code,headers,body=state.responses.pop(0)
        else:code,headers,body=state.status,state.headers,state.body
        return httpx.Response(code,headers=headers,stream=Bytes(body))
    # Patch the actual event-loop resolver rather than bypassing IP validation.
    import asyncio.base_events
    monkeypatch.setattr(asyncio.base_events.BaseEventLoop,'getaddrinfo',lambda self,*a,**k:dns(*a,**k))
    actual=httpx.AsyncClient
    def client(**kw):
        assert kw['trust_env'] is False and kw['follow_redirects'] is False
        return actual(transport=httpx.MockTransport(handler),**kw)
    monkeypatch.setattr(n,'httpx',SimpleNamespace(AsyncClient=client,URL=httpx.URL,Timeout=httpx.Timeout,TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError,RemoteProtocolError=httpx.RemoteProtocolError))
    return state

@pytest.mark.parametrize('url,code',[
    ('http://localhost/','blocked_private_address'),('http://127.0.0.1/','blocked_private_address'),
    ('http://10.0.0.1/','blocked_private_address'),('http://172.16.0.1/','blocked_private_address'),('http://192.168.1.1/','blocked_private_address'),
    ('http://[::1]/','blocked_private_address'),('http://[fc00::1]/','blocked_private_address'),('http://[fe80::1]/','blocked_private_address'),
    ('http://169.254.169.254/','blocked_private_address'),('http://100.100.100.200/','blocked_private_address'),('http://0.0.0.0/','blocked_private_address'),
    ('http://224.0.0.1/','blocked_private_address'),('http://[ff02::1]/','blocked_private_address'),('http://[::ffff:127.0.0.1]/','blocked_private_address'),
    ('http://hidden.onion/','blocked_onion'),('https://Hidden.OnIoN./','blocked_onion'),
    ('file:///tmp/a','blocked_scheme'),('data:text/plain,hello','blocked_scheme'),('ftp://example.org/','blocked_scheme'),
    ('javascript:alert(1)','blocked_scheme'),('ws://example.org/','blocked_scheme'),('wss://example.org/','blocked_scheme'),
    ('chrome://settings','blocked_scheme'),('about:blank','blocked_scheme'),
    ('https://user:password@example.org/','authentication_required'),('http://example.org:8080/','blocked_private_address'),
])
@pytest.mark.asyncio
async def test_blocked_targets_before_dns_or_transport(wire,url,code):
    value=await n.retrieve(url)
    assert value.failure_reason==code and not wire.calls and not wire.dns

@pytest.mark.asyncio
async def test_public_hostname_resolving_private_ip(wire):
    wire.ip='192.168.1.1';value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='blocked_private_address' and not wire.calls

@pytest.mark.asyncio
async def test_dns_failure(wire):
    wire.ip='error';value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='dns_failure' and not wire.calls

@pytest.mark.asyncio
async def test_html_hash_extraction_and_pinned_tls(wire):
    value=await n.retrieve('https://example.org/page')
    assert value.status=='captured' and value.body_sha256==hashlib.sha256(wire.body).hexdigest()
    assert value.body==wire.body and value.byte_count==len(wire.body) and value.title=='Source title'
    assert BTC in value.text and 'Link text' in value.text and 'BAD' not in value.text
    assert len(wire.calls)==len(wire.dns)==1
    req=wire.calls[0];assert req.headers['Host']=='example.org' and req.extensions['sni_hostname']=='example.org'

@pytest.mark.asyncio
async def test_plain_text(wire):
    wire.headers={'content-type':'text/plain; charset=utf-8'};wire.body=b'First line\nSecond line'
    value=await n.retrieve('http://example.org/')
    assert value.text=='First line\nSecond line' and value.title is None and value.status=='captured'

@pytest.mark.parametrize('location',['http://127.0.0.1/','http://hidden.onion/','file:///tmp/a','http://user:password@example.org/'])
@pytest.mark.asyncio
async def test_redirect_blocked(wire,location):
    wire.responses=[(302,{'location':location},b'')]
    value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='redirect_blocked' and len(wire.calls)==1
    assert value.redirects[-1]['to'] is None and 'password' not in str(value.redirects)

@pytest.mark.asyncio
async def test_redirect_dns_checked_again_and_no_cookie_forwarding(wire):
    wire.responses=[(302,{'location':'https://other.org/end','set-cookie':'secret=yes'},b'')]
    value=await n.retrieve('https://example.org/')
    assert value.status=='captured' and wire.dns==['example.org','other.org'] and len(wire.calls)==2
    assert wire.calls[-1].headers['Host']=='other.org' and 'cookie' not in wire.calls[-1].headers

@pytest.mark.asyncio
async def test_redirect_limit(wire):
    wire.status=302;wire.headers={'location':'/next'}
    value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='too_many_redirects' and len(wire.calls)==6

@pytest.mark.parametrize('declared',[False,True])
@pytest.mark.asyncio
async def test_body_cap(wire,monkeypatch,declared):
    monkeypatch.setattr(n,'MAX_BYTES',100)
    wire.body=b'x'*101
    if declared:wire.headers['content-length']='101'
    value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='response_too_large' and value.truncated and value.body is None and value.body_sha256 is None

@pytest.mark.parametrize('error,code',[(httpx.ReadTimeout('secret timeout'),'timeout'),(httpx.ConnectError('secret'),'network_error'),(httpx.RemoteProtocolError('secret'),'invalid_response')])
@pytest.mark.asyncio
async def test_transport_errors(wire,error,code):
    wire.error=error;value=await n.retrieve('https://example.org/')
    assert value.failure_reason==code and 'secret' not in str(value)

@pytest.mark.parametrize('status,code',[(401,'authentication_required'),(403,'authentication_required'),(407,'authentication_required'),(429,'rate_limited'),(500,'http_error')])
@pytest.mark.asyncio
async def test_status_errors(wire,status,code):
    wire.status=status;value=await n.retrieve('https://example.org/')
    assert value.failure_reason==code and value.http_status==status and value.body is None

@pytest.mark.parametrize('mime',['application/pdf','image/png','application/xhtml+xml','application/octet-stream'])
@pytest.mark.asyncio
async def test_unsupported_content(wire,mime):
    wire.headers={'content-type':mime};value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='unsupported_content_type' and value.byte_count==0

@pytest.mark.asyncio
async def test_compressed_response_not_decompressed_unbounded(wire):
    wire.headers['content-encoding']='gzip';value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='unsupported_content_type'

@pytest.mark.asyncio
async def test_overall_timeout_includes_dns(wire,monkeypatch):
    async def slow(*args):await asyncio.sleep(1)
    monkeypatch.setattr(n,'resolve',slow);monkeypatch.setattr(n,'TIMEOUT',0.001)
    value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='timeout' and not wire.calls

@pytest.mark.asyncio
async def test_redirect_public_host_resolving_private(wire,monkeypatch):
    original=n.resolve
    async def resolve(host,port):
        if host=='second.org':wire.ip='10.0.0.2'
        return await original(host,port)
    monkeypatch.setattr(n,'resolve',resolve)
    wire.responses=[(302,{'location':'https://second.org/'},b'')]
    value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='redirect_blocked' and len(wire.calls)==1
    assert value.redirects[-1]['blocked_reason']=='blocked_private_address'

@pytest.mark.asyncio
async def test_mixed_dns_answers_rejected_before_connect(wire,monkeypatch):
    import asyncio.base_events
    async def mixed(*a,**k):return [(2,1,6,'',('93.184.215.14',443)),(2,1,6,'',('127.0.0.1',443))]
    monkeypatch.setattr(asyncio.base_events.BaseEventLoop,'getaddrinfo',mixed)
    value=await n.retrieve('https://example.org/')
    assert value.failure_reason=='blocked_private_address' and not wire.calls
