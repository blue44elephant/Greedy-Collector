"""OSINT-2A browser-only transport fixture; inherits isolated temporary DB setup."""
from browser_osint2_server import *
from greedy_collector.discovery.broad import tavily
os.environ['TAVILY_API_KEY']='osint2a-browser-only-key'
os.environ['TAVILY_KEYLESS_ENABLED']='false'
mode='ready'

def tavily_handler(request):
    calls.append(str(request.url))
    assert str(request.url)=='https://api.tavily.com/search' and request.method=='POST'
    if mode=='quota':return httpx.Response(432,json={'error':'Test quota exhausted'})
    return httpx.Response(200,json={'results':[
        {'url':'https://www.justice.gov/osint2a-fixture','title':'Fixture public notice','content':BTC+'; alias: vendor123; entity: Example Service;'},
        {'url':'https://example.org/unrelated','title':'Fuzzy fixture','content':'No wallet token present'},
    ]})
tavily.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(tavily_handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError)

@main.app.post('/test-osint2a-mode/{value}')
def change_mode(value:str):
    global mode
    assert value in ('ready','missing','quota')
    mode=value
    os.environ['TAVILY_API_KEY']='' if value=='missing' else 'osint2a-browser-only-key'
    return {'mode':value}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(main.app,host='127.0.0.1',port=int(sys.argv[1]),log_level='warning')
