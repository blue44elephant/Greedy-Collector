"""Test-only controlled DNS/HTTP source fixtures. No real internet retrieval."""
from browser_osint2a_server import *
import asyncio.base_events
import socket
from greedy_collector.discovery.capture import network
from greedy_collector.discovery.capture.models import PublicSourceCapture
capture_mode='ready'
capture_calls=[]
original_dns=asyncio.base_events.BaseEventLoop.getaddrinfo
async def test_dns(self,host,port,**kwargs):
    if host in ('www.justice.gov','example.org'):
        ip='127.0.0.1' if capture_mode=='blocked' else '93.184.215.14'
        return [(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,port))]
    assert host in ('127.0.0.1','localhost','::1'), 'No external DNS allowed in browser smoke'
    return await original_dns(self,host,port,**kwargs)
asyncio.base_events.BaseEventLoop.getaddrinfo=test_dns
class SourceBody(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield ('<html><head><title>Controlled public source</title></head><body><h1>Fixture notice</h1><p>'+BTC+'</p><p>'+capture_mode+'</p><script>DO NOT RUN OR DISPLAY</script><a href="http://127.0.0.1/private">No linked fetch</a></body></html>').encode()
async def source_handler(request):
    assert request.url.host=='93.184.215.14' and 'cookie' not in request.headers and 'authorization' not in request.headers
    capture_calls.append(str(request.url))
    return httpx.Response(200,headers={'content-type':'text/html'},stream=SourceBody())
network.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(source_handler),**kw),URL=httpx.URL,Timeout=httpx.Timeout,TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError,RemoteProtocolError=httpx.RemoteProtocolError)
@main.app.post('/test-osint2b-mode/{value}')
def capture_test_mode(value:str):
    global capture_mode
    assert value in ('ready','modified','blocked')
    capture_mode=value
    return {'mode':value}
@main.app.get('/test-osint2b-state')
def capture_test_state():
    with SessionLocal() as db:
        material=[{k:r.material[k] for k in ('id','body_sha256','status','change_state','wallet_present_in_capture','failure_reason')} for r in db.scalars(select(PublicSourceCapture).order_by(PublicSourceCapture.retrieved_at))]
    return {**state(),'capture_calls':capture_calls,'captures':material}
if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
