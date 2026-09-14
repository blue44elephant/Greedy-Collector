"""Browser-only HTTP fixture; production executor and persistence remain real."""
import json
from types import SimpleNamespace
import httpx
from greedy_collector.discovery import github


def install(work):
    actual=httpx.AsyncClient
    async def handler(request):
        assert request.url.host=='api.github.com' and request.url.path=='/search/code'
        calls=work/'github-calls'
        calls.write_text(str(int(calls.read_text())+1 if calls.exists() else 1))
        modefile=work/'github-mode'
        mode=modefile.read_text() if modefile.exists() else 'success'
        if mode=='slow':
            import asyncio
            await asyncio.sleep(6)
        if mode=='rate':return httpx.Response(429,json={'message':'ed3-test-only-secret'},headers={'retry-after':'60','x-ratelimit-resource':'code_search'})
        if mode=='empty':return httpx.Response(200,json={'total_count':0,'incomplete_results':False,'items':[]})
        address='0x'+'ab'*20
        item={'repository':{'id':321,'full_name':'test/browser-fixture','private':False,'html_url':'https://github.com/test/browser-fixture'},
            'path':'src/wallet.txt','name':'wallet.txt','sha':'b'*40,'html_url':'https://github.com/test/browser-fixture/blob/main/src/wallet.txt','score':4.2,
            'text_matches':[{'property':'content','fragment':('Changed test-only context ' if mode=='changed' else 'Test-only code context ')+address}]}
        return httpx.Response(200,json={'total_count':1,'incomplete_results':False,'items':[item]},headers={'x-ratelimit-limit':'10','x-ratelimit-remaining':'9','x-ratelimit-resource':'code_search'})
    github.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError)
