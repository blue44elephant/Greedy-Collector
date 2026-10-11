"""OFAC SLS XML namespace fixture; no OFAC or blockchain network calls."""
from hashlib import sha256
from datetime import datetime,timedelta,timezone
import pytest
from sqlalchemy import select,func
from sqlalchemy.orm import sessionmaker
from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import (Base,Case,Label,RiskResult,WatchlistWallet,SanctionsSnapshot,
    SanctionsIdentifier,SanctionsSyncEvent)
from greedy_collector.sanctions.ofac import NAMESPACE,SOURCE_URL,SanctionsError,parse_sdn_xml,map_identifier
from greedy_collector.sanctions.service import SanctionsRegistry,screen,pin_to_case,current_snapshot

BTC='1BoatSLRHtKNngkdXEeobR76b53LETtpyT'
ETH='0x'+'ab'*20
OTHER='0x'+'cd'*20

def source(entries=None):
    entries=entries or [(1,'Listed One',['CYBER2','SDGT'],[('ETH',ETH),('XBT',BTC),('USDT',ETH)]),
                        (2,'Listed Two',['CYBER2'],[('ETH',ETH),('XRP','rExample')])]
    rows=[]
    for uid,name,programs,ids in entries:
        rows.append(f'<sdnEntry><uid>{uid}</uid><lastName>{name}</lastName><sdnType>Entity</sdnType>'+
            '<programList>'+''.join(f'<program>{p}</program>' for p in programs)+'</programList>'+
            '<akaList><aka><type>aka</type><lastName>Alias '+str(uid)+'</lastName></aka></akaList>'+
            '<idList>'+''.join(f'<id><idType>Digital Currency Address - {asset}</idType><idNumber>{address}</idNumber></id>' for asset,address in ids)+'</idList></sdnEntry>')
    return ('<?xml version="1.0"?><sdnList xmlns="'+NAMESPACE+'"><publshInformation><publishDate>2026-10-01</publishDate></publshInformation>'+''.join(rows)+'</sdnList>').encode()

class FixtureSource:
    url=SOURCE_URL
    parser_version='sdn-xml-2024-v1'
    def __init__(self,data):self.data=data;self.calls=0;self.fail=None
    def fetch(self):
        self.calls+=1
        if self.fail:raise SanctionsError(self.fail)
        return self.data,None
    def parse(self,data):return parse_sdn_xml(data,minimum_entities=1)

@pytest.fixture
def registry_db(tmp_path):
    engine=create_fk_enabled_engine('sqlite:///'+(tmp_path/'sanctions.db').as_posix())
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:yield db
    engine.dispose()

def test_parse_preserves_entity_alias_program_and_raw():
    raw=source();parsed=parse_sdn_xml(raw,minimum_entities=1)
    assert parsed.sha256==sha256(raw).hexdigest() and parsed.published_at=='2026-10-01'
    assert len(parsed.entities)==2 and len(parsed.identifiers)==5
    assert parsed.entities[0]['source_entity_id']=='1'
    assert parsed.entities[0]['programs']==['CYBER2','SDGT']
    assert parsed.entities[0]['aliases']==[{'name':'Alias 1','type':'aka'}]
    assert parsed.identifiers[0]['raw_value']==ETH
    assert parsed.identifiers[0]['chain']=='ethereum'
    assert parsed.identifiers[2]['mapping_status']=='ambiguous_asset'
    assert parsed.identifiers[-1]['mapping_status']=='unsupported_asset'

@pytest.mark.parametrize('asset,chain', [('XBT','bitcoin'),('BTC','bitcoin'),('ETH','ethereum'),('LTC','litecoin'),('TRX','tron'),('SOL','solana'),('XMR','monero')])
def test_explicit_asset_mapping_uses_validator(asset,chain):
    resolved,canonical,status=map_identifier(asset,'not-a-valid-address')
    assert (resolved,canonical,status)==(chain,None,'invalid_address')

@pytest.mark.parametrize('raw,reason',[(b'<!DOCTYPE a><sdnList/>','unsupported_schema'),(b'<broken','parse_error'),
    (b'<sdnList/>','unsupported_schema'),(b'','validation_failed')])
def test_reject_unusable_source(raw,reason):
    with pytest.raises(SanctionsError,match=reason):parse_sdn_xml(raw,minimum_entities=1)

def test_snapshot_history_and_exact_chain_scope(registry_db):
    db=registry_db;adapter=FixtureSource(source());registry=SanctionsRegistry(db,adapter)
    assert screen(db,'ethereum',ETH)['listing_state']=='REGISTRY_NOT_SYNCED'
    first=registry.sync()['snapshot'];assert first['entity_count']==2 and first['identifier_count']==5
    found=screen(db,'ethereum',ETH)
    assert found['listing_state']=='CURRENTLY_LISTED' and found['match_type']=='DIRECT_CHAIN_MATCH'
    assert found['first_seen_snapshot']==first['id'] and found['last_seen_snapshot']==first['id']
    assert len(found['associations'])==3 and {r['entity']['source_entity_id'] for r in found['associations']}=={'1','2'}
    assert screen(db,'base',ETH)['match_type']=='EXACT_TEXT_MATCH_CHAIN_UNRESOLVED'
    assert screen(db,'ethereum',OTHER)['match_type']=='NO_MATCH'
    case=Case(title='Local screening case');db.add(case);db.commit()
    pin=pin_to_case(db,case.id,'ethereum',ETH)
    adapter.data=source([(3,'New One',['CYBER2'],[('ETH',OTHER)])])
    second=registry.sync()['snapshot'];assert second['id']!=first['id']
    assert second['change_counts']['removed']==4
    historical=screen(db,'ethereum',ETH)
    assert historical['listing_state']=='HISTORICALLY_LISTED' and historical['observed_removed_at']
    assert historical['first_seen_snapshot']==first['id'] and historical['last_seen_snapshot']==first['id']
    assert pin['record']['screening']['listing_state']=='CURRENTLY_LISTED'
    assert db.scalar(select(func.count()).select_from(Label))==0
    assert db.scalar(select(func.count()).select_from(RiskResult))==0
    assert db.scalar(select(func.count()).select_from(WatchlistWallet))==0
    adapter.fail='network_error'
    with pytest.raises(SanctionsError,match='network_error'):registry.sync()
    assert current_snapshot(db).id==second['id']
    assert db.scalar(select(func.count()).select_from(SanctionsSnapshot))==2
    assert db.scalar(select(func.count()).select_from(SanctionsSyncEvent))==3

def test_official_checksum_mismatch_keeps_prior(registry_db):
    db=registry_db;fixture=FixtureSource(source());registry=SanctionsRegistry(db,fixture)
    old=registry.sync()['snapshot']['id']
    with pytest.raises(SanctionsError,match='integrity_failed'):
        registry.sync(official_sha256='0'*64)
    assert current_snapshot(db).id==old
    checked=registry.sync(official_sha256=sha256(fixture.data).hexdigest())['snapshot']
    assert checked['integrity_status']=='verified'


def test_official_redirect_is_narrowly_pinned(monkeypatch):
    from greedy_collector.sanctions import ofac
    redirects=[]
    class Response:
        headers={}
        def __init__(self,status,location=None):
            self.status_code=status
            self.headers={'Location':location} if location else {}
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def iter_content(self,size):yield source()
    class Client:
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def get(self,url,**kwargs):
            redirects.append(url)
            assert kwargs['allow_redirects'] is False
            return Response(302,target) if len(redirects)==1 else Response(200)
    monkeypatch.setattr(ofac.requests,'Session',Client)
    target='https://'+ofac.OFAC_BUCKET+'/Published/release/SDN.XML?X-Amz-Signature=test'
    assert ofac.OfacSdnSource().fetch()[0]==source()
    assert redirects[1]==target
    redirects.clear()
    target='https://untrusted.example/Published/SDN.XML'
    with pytest.raises(SanctionsError,match='source_unavailable'):ofac.OfacSdnSource().fetch()
    assert len(redirects)==1
    redirects.clear()
    target='https://'+ofac.OFAC_BUCKET+'/other/SDN.XML'
    with pytest.raises(SanctionsError,match='source_unavailable'):ofac.OfacSdnSource().fetch()


def test_stale_absence_timestamp_and_sync_conflict(registry_db):
    from greedy_collector.models import SanctionsRegistryState
    db=registry_db;fixture=FixtureSource(source());registry=SanctionsRegistry(db,fixture)
    registry.sync()
    fixture.data=source([(3,'Replacement',['CYBER2'],[('ETH',OTHER)])])
    second=registry.sync()['snapshot']
    fixture.data=source([(4,'Later',['CYBER2'],[('ETH',OTHER)])])
    registry.sync()
    result=screen(db,'ethereum',ETH)
    assert result['listing_state']=='HISTORICALLY_LISTED'
    assert datetime.fromisoformat(result['observed_removed_at']).replace(tzinfo=None)==datetime.fromisoformat(second['retrieved_at']).replace(tzinfo=None)
    state=db.get(SanctionsRegistryState,'ofac_sdn')
    state.sync_lease_until=datetime.now(timezone.utc)+timedelta(minutes=2);db.commit()
    with pytest.raises(SanctionsError,match='sync_already_running'):registry.sync()
    assert fixture.calls==3
    state.sync_lease_until=None
    current=current_snapshot(db);current.retrieved_at=datetime.now(timezone.utc)-timedelta(days=4);db.commit()
    assert screen(db,'ethereum',ETH)['stale'] is True
    assert screen(db,'ethereum','0x'+'ef'*20)['listing_state']=='REGISTRY_STALE'
