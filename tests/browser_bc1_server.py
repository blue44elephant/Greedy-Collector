"""BC-1 browser fixtures: real routers, normalization and isolated SQLite."""
import os
import sys
import tempfile
from pathlib import Path
work=Path.cwd().resolve()
assert work.is_relative_to(Path(tempfile.gettempdir()).resolve()), "Browser DB must be temporary"
os.environ["PYTHON_DOTENV_DISABLED"]="1"
os.environ["GREEDY_COLLECTOR_DATABASE_URL"]="sqlite:///"+(work/"bc1.db").as_posix()
os.environ["GREEDY_COLLECTOR_GRAPH_BACKEND"]="sqlite"
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import httpx
import main
from greedy_collector.chains.bitcoin import BitcoinAdapter
from greedy_collector.chains.ethereum import EthereumAdapter
from greedy_collector.chains.base import ChainDataError
from greedy_collector.chains.etherscan_v2 import EtherscanV2Adapter
main.start_monitoring=lambda:None
main.stop_monitoring=lambda:None

def forbidden(*args,**kwargs):raise AssertionError("Unexpected external provider request")
httpx.AsyncHTTPTransport.handle_async_request=forbidden
httpx.HTTPTransport.handle_request=forbidden
A="0x"+"1"*40
B="0x"+"2"*40
C="0x"+"3"*40
BTC="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
OTHER="1BoatSLRHtKNngkdXEeobR76b53LETtpyT"
async def evm(self,params):
    action=params["action"]
    if action=="balance":return {"result":"1000000000000000001"}
    if action=="eth_getTransactionByHash":return {"result":{"hash":params["txhash"],"from":A,"to":B,"value":"0x1","blockNumber":"0x1","gas":"0x5208","gasPrice":"0x1"}}
    if action=="tokentx":
        if params["address"]==B:raise ChainDataError("rate_limited")
        return {"result":[{"hash":"0x"+"c"*64,"from":A,"to":B,"contractAddress":C,
            "value":"123456789012345678901234567890123456789","tokenDecimal":"18","tokenSymbol":"FIXTURE","logIndex":"1","blockNumber":"1","timeStamp":"1700000000"}]}
    return {"result":[{"hash":"0x"+"b"*64,"from":A,"to":B,"value":"1","isError":"1","blockNumber":"1","timeStamp":"1700000000"}]}
EtherscanV2Adapter._etherscan=evm
async def btc_fetch(self,path):
    return {"chain_stats":{"funded_txo_sum":100000001,"spent_txo_sum":0,"tx_count":1},"mempool_stats":{"funded_txo_sum":0,"spent_txo_sum":0,"tx_count":0}},"fixture-esplora"
async def btc_history(self,*args):
    return [{"txid":"a"*64,"vin":[{"prevout":{"scriptpubkey_address":BTC,"value":100000001}}],
        "vout":[{"scriptpubkey_address":OTHER,"value":100000000},{"scriptpubkey_address":BTC,"value":1}],
        "status":{"confirmed":True,"block_time":1700000000,"block_height":1},"fee":0}]
BitcoinAdapter._fetch=btc_fetch
BitcoinAdapter._fetch_from_provider=btc_history
if __name__=="__main__":
    import uvicorn
    uvicorn.run(main.app,host="127.0.0.1",port=int(sys.argv[1]),log_level="warning")
