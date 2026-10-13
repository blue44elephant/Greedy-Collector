"""Cases contracts against real isolated SQLite/API/report paths, never live providers."""
from unittest.mock import AsyncMock
import pytest
from sqlalchemy.orm import Session

from tests.test_ui import ui_client, no_monitoring
from greedy_collector.models import WalletAlert

PREFIX = '/api/greedy-collector'
ADDRESS = '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'

@pytest.fixture(autouse=True)
def no_providers(monkeypatch):
    monkeypatch.setattr('httpx.AsyncClient.request', AsyncMock(side_effect=AssertionError('No external requests')))

def create(client):
    response = client.post(PREFIX+'/cases', json={'title':'Investigation <script>test</script>', 'description':'Analyst-selected references'})
    assert response.status_code == 200
    return response.json()

def test_cases_navigation_and_integrations(ui_client):
    client, _ = ui_client
    assert 'data-workspace="cases"' in client.get('/').text
    assert 'id="cases-workspace"' in client.get('/').text
    for module in ['cases', 'case_actions']:
        assert client.get(f'/static/js/{module}.js').status_code == 200
    for module in ['wallet', 'graph']:
        assert 'addToCaseButton(' in client.get(f'/static/js/{module}.js').text
    wallet = client.get('/static/js/wallet.js').text
    assert 'addToCaseButton("transaction", record.chain||tx.chain' in wallet
    assert "event_key:record.event_key" in wallet
    assert 'listCases()' in client.get('/static/js/monitoring.js').text
    assert 'openCase(alert.case_id)' in client.get('/static/js/alerts.js').text

def test_case_empty_create_list_detail(ui_client):
    client, _ = ui_client
    assert client.get(PREFIX+'/cases').json() == {'cases':[]}
    row = create(client)
    assert row['created_at'] and row['updated_at'] and row['status'] == 'Open'
    assert client.get(PREFIX+'/cases').json()['cases'] == [row]
    detail = client.get(PREFIX+'/cases/'+row['id']).json()
    assert {k: detail[k] for k in row} == row
    assert detail['entities'] == detail['notes'] == detail['alerts'] == detail['reports'] == detail['sanctions_pins'] == []
    assert [e['kind'] for e in detail['timeline']] == ['case_created']

@pytest.mark.parametrize('kind,reference,chain', [('wallet',ADDRESS,'bitcoin'), ('transaction','0x'+'b'*64,'ethereum')])
def test_case_entity_references_are_persisted_without_collection(ui_client, kind, reference, chain):
    client, _ = ui_client
    row = create(client)
    metadata = {'chain':chain, 'address' if kind == 'wallet' else 'tx_hash':reference}
    result = client.post(PREFIX+f"/cases/{row['id']}/entities", json={'entity_type':kind,'entity_ref':reference,'metadata':metadata})
    assert result.status_code == 200
    entity = result.json()
    assert entity['entity_ref'] == reference
    assert all(entity['metadata_json'][key] == value for key, value in metadata.items())
    assert entity['metadata_json']['display_address' if kind == 'wallet' else 'display_tx_hash'] == reference
    assert client.get(PREFIX+f"/cases/{row['id']}").json()['entities'] == [entity]

def test_case_note_and_exact_alert_association(ui_client):
    client, engine = ui_client
    row, other = create(client), create(client)
    note = client.post(PREFIX+f"/cases/{row['id']}/notes",json={'body':'Public record requires review.'})
    assert note.status_code == 200
    assert note.json()['author'] == 'analyst' and note.json()['created_at']
    with Session(engine) as db:
        for index, case_id in enumerate([row['id'],other['id'],None]):
            db.add(WalletAlert(wallet=ADDRESS,chain='bitcoin',case_id=case_id,severity='Medium',
                trigger_type='Stored indicator',explanation='Test-only alert',dedupe_key=f'case-test-{index}'))
        db.commit()
    detail = client.get(PREFIX+f"/cases/{row['id']}").json()
    assert detail['notes'] == [note.json()]
    assert len(detail['alerts']) == 1 and detail['alerts'][0]['case_id'] == row['id']
    assert detail['alerts'][0]['tx_hash'] is None

def test_case_upload_metadata_and_isolated_storage(ui_client, tmp_path, monkeypatch):
    client, _ = ui_client
    monkeypatch.chdir(tmp_path)
    row = create(client)
    response = client.post(PREFIX+f"/cases/{row['id']}/attachments",files={'file':('unique-prefix-note.txt', b'Harmless test attachment','text/plain')})
    assert response.status_code == 200
    entity = response.json()
    assert entity['entity_type'] == 'attachment'
    assert entity['metadata_json']['filename'] == 'unique-prefix-note.txt'
    assert entity['metadata_json']['original_filename'] == 'unique-prefix-note.txt'
    assert entity['metadata_json']['content_type'] == 'text/plain'
    assert entity['metadata_json']['size'] == 24 and len(entity['metadata_json']['sha256']) == 64
    assert (tmp_path/'data'/entity['entity_ref']).read_bytes() == b'Harmless test attachment'
    assert client.get(PREFIX+f"/cases/{row['id']}").json()['entities'] == [entity]
    assert str(tmp_path) not in response.text

@pytest.mark.parametrize('format,content_type', [('markdown','text/markdown'),('html','text/html'),('json','application/json'),('pdf','application/pdf')])
def test_real_case_report_formats_and_secret_safety(ui_client, monkeypatch, format, content_type):
    from greedy_collector.config import get_settings
    settings=get_settings()
    for key in ['etherscan_api_key','alchemy_api_key']:
        monkeypatch.setattr(settings,key,'case-dummy-private-provider-key')
    client, _ = ui_client
    row = create(client)
    client.post(PREFIX+f"/cases/{row['id']}/notes",json={'body':'Stored report note'})
    client.post(PREFIX+f"/cases/{row['id']}/entities",json={'entity_type':'wallet','entity_ref':ADDRESS,'metadata':{'chain':'bitcoin'}})
    response=client.get(PREFIX+f"/reports/{row['id']}?format={format}")
    assert response.status_code == 200 and response.headers['content-type'].startswith(content_type)
    assert b'case-dummy-private-provider-key' not in response.content
    if format == 'pdf': assert response.content.startswith(b'%PDF-')
    else:
        assert ADDRESS in response.text and 'Stored report note' in response.text
        assert 'does not prove' in response.text
    if format == 'html': assert '<script>test</script>' not in response.text and '&lt;script&gt;' in response.text
    if format == 'json': assert response.json()['case']['id'] == row['id']

def test_case_invalid_fields_and_missing_records(ui_client):
    client, _ = ui_client
    assert client.post(PREFIX+'/cases',json={'title':''}).status_code == 422
    row=create(client)
    assert client.post(PREFIX+f"/cases/{row['id']}/entities",json={'entity_type':'person','entity_ref':'unsupported'}).status_code == 422
    assert client.post(PREFIX+f"/cases/{row['id']}/notes",json={'body':''}).status_code == 422
    assert client.get(PREFIX+f"/reports/{row['id']}?format=csv").status_code == 422
    assert client.get(PREFIX+'/cases/missing').status_code == 404
    assert client.get(PREFIX+'/reports/missing').status_code == 404
    assert client.post(PREFIX+'/cases/missing/entities',json={'entity_type':'wallet','entity_ref':ADDRESS}).status_code == 404
    assert client.post(PREFIX+'/cases/missing/notes',json={'body':'Test'}).status_code == 404
    assert client.post(PREFIX+'/cases/missing/attachments',files={'file':('note.txt',b'Test','text/plain')}).status_code == 404

def test_case_openapi_matches_reused_routes(ui_client):
    client,_=ui_client
    paths=client.get('/openapi.json').json()['paths']
    for route, methods in {'/cases':{'get','post'},'/cases/{case_id}':{'get','patch'},'/cases/{case_id}/entities':{'post'},
        '/cases/{case_id}/notes':{'post'},'/cases/{case_id}/attachments':{'post'},'/reports/{case_id}':{'get'}}.items():
        assert set(paths[PREFIX+route]) == methods
    source=client.get('/static/js/cases.js').text
    assert 'innerHTML' not in source and 'const filename=data.file.name' in source
    assert 'link.download=' in source
