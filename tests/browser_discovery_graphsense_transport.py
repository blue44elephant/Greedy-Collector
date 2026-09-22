"""Browser-only official GitHub API fixture. Production executor is unchanged."""
from types import SimpleNamespace
import httpx
from greedy_collector.discovery import github
from tests.graphsense_fixture import pack,material,search,REPO

def install(work):
    actual=httpx.AsyncClient
    state={}
    async def handler(request):
        assert request.url.host=='api.github.com' and request.method=='GET'
        calls=work/'graphsense-calls'
        calls.write_text(str(int(calls.read_text())+1 if calls.exists() else 1))
        modefile=work/'graphsense-mode';mode=modefile.read_text() if modefile.exists() else 'success'
        if request.url.path=='/search/code':
            query=request.url.params['q'];address=query.split('"')[1]
            assert query=='"'+address+'" repo:'+REPO+' path:packs in:file'
            currency='ETH' if address.startswith('0x') else 'BTC'
            files=[] if mode=='empty' else [material(pack(address,currency,confidence='forensic' if mode=='changed' else 'service_data'),'packs/a.yaml'),material(pack(address,currency,label='Synthetic service B'),'packs/b.yaml')]
            state.update({item['sha']:blob for item,blob in files})
            return httpx.Response(200,json=search([item for item,_ in files]),headers={'x-ratelimit-resource':'code_search','x-ratelimit-remaining':'8'})
        assert request.url.path.startswith('/repos/'+REPO+'/git/blobs/')
        return httpx.Response(200,json=state[request.url.path.rsplit('/',1)[1]],headers={'x-ratelimit-resource':'core','x-ratelimit-remaining':'100'})
    github.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError)
