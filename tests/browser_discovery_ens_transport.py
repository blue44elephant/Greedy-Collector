"""Isolated browser fixture. No mocked data is installed by production startup."""
import json
from types import SimpleNamespace
import httpx
from greedy_collector.chains import base
from tests.ens_rpc_fixture import reply

def install(work):
    actual=httpx.AsyncClient
    async def handler(request):
        assert request.url.host=='eth-mainnet.g.alchemy.com' and request.url.path=='/v2/ed8a-browser-test-only'
        data=json.loads(request.content)
        assert request.method=='POST' and data['method']=='eth_call'
        assert data['params'][0]['to']=='0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe'
        assert data['params'][0]['data'].startswith('0x5d78a217') and data['params'][1]=='latest'
        file=work/'ens-calls';file.write_text(str(int(file.read_text())+1 if file.exists() else 1))
        modefile=work/'ens-mode';mode=modefile.read_text() if modefile.exists() else 'success'
        if mode=='mismatch':body={'jsonrpc':'2.0','id':1,'error':{'code':3,'message':'test only rejected material','data':'0xef9c03ce'+'00'*64}}
        elif mode=='empty':body=reply('')
        else:body=reply('alice2.eth' if mode=='changed' else 'alice.eth')
        return httpx.Response(200,json=body)
    base.httpx=SimpleNamespace(AsyncClient=lambda **kw:actual(transport=httpx.MockTransport(handler),**kw),TimeoutException=httpx.TimeoutException,HTTPError=httpx.HTTPError)
