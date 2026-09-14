"""ED-5 browser-only providers/annotations, never imported by production."""
from datetime import datetime, timezone
from functools import partial
import json
from unittest.mock import AsyncMock


def install(app, work):
    from greedy_collector.chains import BitcoinAdapter, EthereumAdapter
    from greedy_collector.schemas import NormalizedTransaction
    from greedy_collector.models import Label
    from greedy_collector.database import SessionLocal
    def charge():
        path=work/'handoff-provider-calls'
        path.write_text(str(int(path.read_text())+1 if path.exists() else 1))
    async def profile(address,chain):
        charge()
        return {'balance_native':'1','source_api':'blockstream' if chain=='bitcoin' else 'etherscan'}
    async def transactions(address,chain):
        charge()
        return [NormalizedTransaction(chain=chain,tx_hash='1'*64 if chain=='bitcoin' else '0x'+'1'*64,
            from_address='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa' if chain=='bitcoin' else '0x'+'22'*20,
            to_address=address,value_native='1',token_symbol='BTC' if chain=='bitcoin' else 'ETH',
            timestamp=datetime(2026,9,14,tzinfo=timezone.utc),block_number='123',direction='incoming',source_api='blockstream' if chain=='bitcoin' else 'etherscan')]
    async def transaction(tx_hash,chain):
        rows=await transactions('1BoatSLRHtKNngkdXEeobR76b53LETtpyT' if chain=='bitcoin' else '0x'+'ab'*20,chain)
        return rows[0].model_copy(update={'tx_hash':tx_hash})
    for adapter in (BitcoinAdapter,EthereumAdapter):
        adapter.lookup_address=AsyncMock(side_effect=partial(profile,chain=adapter.chain))
        adapter.transactions=AsyncMock(side_effect=partial(transactions,chain=adapter.chain))
        adapter.lookup_transaction=AsyncMock(side_effect=partial(transaction,chain=adapter.chain))
    def labels():
        with SessionLocal() as db:
            db.add(Label(chain='ethereum',address='0x'+'ab'*20,label='ED-5 test annotation',type='Unknown',source='Isolated browser fixture',confidence=.5))
            db.commit()
    app.router.add_event_handler('startup',labels)
