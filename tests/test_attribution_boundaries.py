"""Existing real service/API operations must remain independent of attribution."""
from unittest.mock import AsyncMock
from sqlalchemy import select,func
from sqlalchemy.orm import Session

from tests.test_ui import ui_client,no_monitoring
from tests.test_research_ui import research_provider
from tests.test_attribution import claim,attach,assess
from greedy_collector.models import AttributionEntity,AttributionClaim,AttributionEvidence,AttributionClaimEvidence,AttributionEvent,RiskResult,Label,Address
from greedy_collector.attribution.service import AttributionService
from greedy_collector.chains import BitcoinAdapter
from greedy_collector.schemas import NormalizedTransaction

PREFIX='/api/greedy-collector'
BTC='1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'


def counts(engine):
    with Session(engine) as db:
        return [db.scalar(select(func.count()).select_from(model)) for model in [AttributionEntity,AttributionClaim,AttributionEvidence,AttributionClaimEvidence,AttributionEvent]]


def test_label_creation_produces_no_attribution(ui_client):
    client,engine=ui_client
    assert client.post(PREFIX+'/labels/manual',json={'chain':'bitcoin','address':BTC,'label':'Synthetic annotation','type':'Unknown'}).status_code==200
    assert counts(engine)==[0]*5


def test_research_screening_produces_no_attribution(ui_client,research_provider):
    client,engine=ui_client
    result=client.post(PREFIX+'/kyc/screen',json={'name':'Test Company'})
    assert result.status_code==200 and result.json()['matches']
    assert counts(engine)==[0]*5


def test_lookup_and_risk_remain_independent(ui_client,monkeypatch):
    client,engine=ui_client
    monkeypatch.setattr(BitcoinAdapter,'lookup_address',AsyncMock(return_value={'balance_native':'1','source_api':'test-only'}))
    monkeypatch.setattr(BitcoinAdapter,'transactions',AsyncMock(return_value=[NormalizedTransaction(chain='bitcoin',tx_hash='a'*64,
        from_address='1BoatSLRHtKNngkdXEeobR76b53LETtpyT',to_address=BTC,value_native='1',token_symbol='BTC',direction='incoming',source_api='test-only')]))
    before=client.post(PREFIX+'/lookup/address',json={'chain':'bitcoin','address':BTC})
    assert before.status_code==200 and counts(engine)==[0]*5
    with Session(engine) as db:
        svc=AttributionService(db,metadata_only=True)
        row=claim(svc,chain='bitcoin',subject_ref=BTC)
        row,_,_=attach(svc,row);assess(svc,row,'strongly_supported')
        assert db.scalar(select(func.count()).select_from(RiskResult))==1
        assert db.scalar(select(func.count()).select_from(Label))==0
        assert db.scalar(select(func.count()).select_from(Address))==1
    after=client.post(PREFIX+'/lookup/address',json={'chain':'bitcoin','address':BTC})
    assert after.status_code==200
    before_risk,after_risk=before.json()['risk'],after.json()['risk']
    assert before_risk['calculated_at'] != after_risk['calculated_at']
    assert {key:value for key,value in before_risk.items() if key!='calculated_at'}=={key:value for key,value in after_risk.items() if key!='calculated_at'}
    assert counts(engine)[1]==1
