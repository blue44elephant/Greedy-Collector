"""Label API/UI contracts using real isolated SQLite and no live providers."""
import csv
from io import StringIO
from unittest.mock import AsyncMock
import pytest
from tests.test_ui import ui_client, no_monitoring

PREFIX='/api/greedy-collector'
BTC='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'
ETH='0x'+'1'*40

@pytest.fixture(autouse=True)
def no_provider_requests(monkeypatch):
    monkeypatch.setattr('httpx.AsyncClient.request',AsyncMock(side_effect=AssertionError('Labels must not call providers')))

def payload(**values):
    return {'chain':'bitcoin','address':BTC,'label':'Test annotation','type':'Exchange',**values}

def upload(client,rows,header='chain,address,label,type,source,confidence'):
    stream=StringIO();writer=csv.writer(stream);writer.writerow(header.split(','));writer.writerows(rows)
    return client.post(PREFIX+'/labels/import',files={'file':('labels.csv',stream.getvalue().encode(),'text/csv')})

def test_duplicate_manual_label_returns_conflict_not_database_error(ui_client):
    client,_=ui_client
    first=client.post(PREFIX+'/labels/manual',json=payload()).json()
    result=client.post(PREFIX+'/labels/manual',json=payload(confidence=0.9,type='Bridge'))
    assert result.status_code==409
    assert client.get(PREFIX+'/labels').json()['labels']==[first]

@pytest.mark.parametrize('kind,confidence',[('Invented','0.5'),('Exchange','2'),('Scam','nan'),('Mixer','bad')])
def test_csv_rejects_invalid_types_and_confidence_atomically(ui_client,kind,confidence):
    client,_=ui_client
    result=upload(client,[['bitcoin',BTC,'Good','Exchange','Test source','0.5'],['bitcoin',BTC,'Bad',kind,'Test source',confidence]])
    assert result.status_code==422
    assert client.get(PREFIX+'/labels').json()=={'labels':[]}

@pytest.mark.parametrize('chain,address',[('ethereum','bad-address'),('bitcoin',ETH),('unsupported',BTC)])
def test_manual_label_validates_supported_chain_and_address(ui_client,chain,address):
    client,_=ui_client
    response=client.post(PREFIX+'/labels/manual',json=payload(chain=chain,address=address))
    assert response.status_code==422

@pytest.mark.parametrize('chain,address',[('bitcoin',BTC),('ethereum',ETH),('any','stored-reference')])
def test_create_manual_label_defaults_and_provenance(ui_client,chain,address):
    client,_=ui_client
    response=client.post(PREFIX+'/labels/manual',json=payload(chain=chain,address=address))
    assert response.status_code==200
    row=response.json()
    assert row['source']=='Manual analyst label' and row['confidence']==0.7 and row['last_updated']
    assert row['chain']==chain and row['address']==address


def test_litecoin_uppercase_bech32_label_keeps_explicit_chain_context(ui_client):
    client,_=ui_client
    address='LTC1QQQQSYQCYQ5RQWZQFPG9SCRGWPUGPZYSN3S44DY'
    response=client.post(PREFIX+'/labels/manual',json=payload(chain='litecoin',address=address,label='Litecoin fixture'))
    assert response.status_code==200,response.text
    assert response.json()['chain']=='litecoin' and response.json()['address']==address

def test_csv_upsert_key_count_and_export(ui_client):
    client,_=ui_client
    assert client.get(PREFIX+'/labels').json()=={'labels':[]}
    first=client.post(PREFIX+'/labels/manual',json=payload(source='Test source')).json()
    result=upload(client,[['bitcoin',BTC,'Test annotation','Bridge','Test source','0.85'],['bitcoin',BTC,'Test annotation','Unknown','Other source','0.35']])
    assert result.status_code==200 and result.json()=={'imported':2}
    rows=client.get(PREFIX+'/labels').json()['labels']
    assert len(rows)==2
    updated=next(r for r in rows if r['id']==first['id'])
    assert updated['type']=='Bridge' and updated['confidence']==0.85
    response=client.get(PREFIX+'/labels/export')
    assert response.status_code==200 and 'text/csv' in response.headers['content-type']
    exported=list(csv.DictReader(StringIO(response.text)))
    assert len(exported)==2 and {'chain','address','label','type','source','confidence','last_updated'}==set(exported[0])
    assert next(r for r in exported if r['source']=='Test source')['confidence']=='0.85'

def test_malformed_csv_and_wrong_extension(ui_client):
    client,_=ui_client
    for filename,content in [('labels.csv',b'address,label\na,b'),('labels.csv',b'address,label,type,source,confidence\nx,y'),('labels.txt',b'Test'),('labels.csv',b'\xff')]:
        response=client.post(PREFIX+'/labels/import',files={'file':(filename,content,'text/csv')})
        assert response.status_code==422
        assert 'Traceback' not in response.text

def test_labels_assets_and_navigation(ui_client):
    client,_=ui_client
    assert 'data-workspace="labels"' in client.get('/').text
    for name in ['labels','label_ui']:
        response=client.get(f'/static/js/{name}.js')
        assert response.status_code==200 and 'innerHTML' not in response.text

def test_label_case_reference_keeps_label_id(ui_client):
    client,_=ui_client
    label=client.post(PREFIX+'/labels/manual',json=payload()).json()
    case=client.post(PREFIX+'/cases',json={'title':'Label test case'}).json()
    response=client.post(PREFIX+f"/cases/{case['id']}/entities",json={'entity_type':'label','entity_ref':label['id'],'metadata':{'chain':label['chain'],'address':label['address']}})
    assert response.status_code==200
    entity=client.get(PREFIX+f"/cases/{case['id']}").json()['entities'][0]
    assert entity['entity_ref']==label['id'] and entity['metadata_json']['address']==BTC

def test_stored_graph_uses_actual_label_and_keeps_address(ui_client,monkeypatch):
    from sqlalchemy.orm import Session
    from greedy_collector.models import Transaction
    from greedy_collector.router import service
    client,engine=ui_client
    monkeypatch.setattr(service.graph_store,'query_graph',lambda *_:None)
    client.post(PREFIX+'/labels/manual',json=payload(label='Stored graph annotation',type='Exchange'))
    with Session(engine) as db:
        db.add(Transaction(chain='bitcoin',tx_hash='b'*64,from_address=BTC,to_address='1BoatSLRHtKNngkdXEeobR76b53LETtpyT',value_native='1',token_symbol='BTC'))
        db.commit()
    response=client.get(PREFIX+f'/address/bitcoin/{BTC}/graph?hops=1')
    assert response.status_code==200
    node=next(row for row in response.json()['nodes'] if row['id']==BTC)
    assert node['label']=='Stored graph annotation' and node['type']=='Exchange'

def test_unknown_label_does_not_add_risk(ui_client,monkeypatch):
    from greedy_collector.chains import EthereumAdapter
    from greedy_collector.schemas import NormalizedTransaction
    from greedy_collector.router import service
    client,_=ui_client
    cp='0x'+'2'*40
    client.post(PREFIX+'/labels/manual',json=payload(chain='ethereum',address=cp,type='Unknown'))
    adapter=EthereumAdapter()
    adapter.lookup_address=AsyncMock(return_value={'balance_native':'1','source_api':'etherscan'})
    adapter.transactions=AsyncMock(return_value=[NormalizedTransaction(chain='ethereum',tx_hash='0x'+'b'*64,from_address=cp,to_address=ETH,value_native='0.1',direction='incoming',token_symbol='ETH',source_api='etherscan')])
    monkeypatch.setattr('greedy_collector.services.get_chain_adapter',lambda _:adapter)
    monkeypatch.setattr(service.graph_store,'store_transactions',lambda _:None)
    response=client.post(PREFIX+'/lookup/address',json={'chain':'ethereum','address':ETH})
    assert response.status_code==200
    assert response.json()['labels'][0]['type']=='Unknown'
    assert response.json()['risk']['score']==0 and response.json()['risk']['findings']==[]
