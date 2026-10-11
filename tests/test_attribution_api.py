"""Manual HTTP workflows over real AT-1 services and migrated temporary SQLite.

Only tests contain synthetic attribution/provider material. External HTTP is blocked.
"""
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import shutil
import os
import subprocess
import sys
from unittest.mock import AsyncMock

from alembic import command
from alembic.config import Config
import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

import main
from greedy_collector.attribution.service import AttributionService
from greedy_collector.chains import BitcoinAdapter
from greedy_collector.database import create_fk_enabled_engine, get_db
from greedy_collector.models import (AttributionEntity, AttributionClaim, AttributionEvidence,
                                     AttributionClaimEvidence, AttributionEvent, Address, Label, RiskResult)
from greedy_collector.schemas import NormalizedTransaction
from tests.test_research_ui import research_provider

ROOT = Path(__file__).resolve().parents[1]
API = '/api/greedy-collector'
P = API + '/attribution'
ETH = '0x' + 'aB' * 20
BTC = '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'


@pytest.fixture(scope='module')
def migrated_template(tmp_path_factory):
    target = tmp_path_factory.mktemp('at2-schema')/'template.db'
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv('GREEDY_COLLECTOR_DATABASE_URL', 'sqlite:///' + target.as_posix())
        cfg = Config(str(ROOT/'alembic.ini'), stdout=StringIO())
        cfg.set_main_option('script_location', str(ROOT/'migrations'))
        command.upgrade(cfg, 'head')
    return target


@pytest.fixture
def api(migrated_template, tmp_path, monkeypatch):
    target = tmp_path/'api.db'
    shutil.copyfile(migrated_template, target)
    engine = create_fk_enabled_engine('sqlite:///' + target.as_posix(), connect_args={'check_same_thread': False})

    def database():
        with Session(engine) as session:
            yield session

    def no_external(*args, **kwargs):
        raise AssertionError('Attribution must not request external HTTP')

    monkeypatch.setattr(httpx.HTTPTransport, 'handle_request', no_external)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, 'handle_async_request', no_external)
    monkeypatch.setattr(main, 'start_monitoring', lambda: None)
    monkeypatch.setattr(main, 'stop_monitoring', lambda: None)
    old = main.app.dependency_overrides.copy()
    main.app.dependency_overrides[get_db] = database
    try:
        with TestClient(main.app) as client:
            yield client, engine
    finally:
        main.app.dependency_overrides.clear()
        main.app.dependency_overrides.update(old)
        engine.dispose()


def ok(response, status=200):
    assert response.status_code == status, response.text
    return response.json()


def entity(client, **values):
    return ok(client.post(P+'/entities', json={'canonical_name': 'Synthetic AT-2 service', 'entity_type': 'service',
                                               'aliases': ['Synthetic alias'], **values}), 201)


def claim(client, **values):
    payload = {'entity_id': values.pop('entity_id', None) or entity(client)['id'], 'chain': 'ethereum',
               'subject_ref': ETH, 'relationship': 'operated_by', 'scope_note': 'Synthetic test proposition only', **values}
    return ok(client.post(P+'/claims', json=payload), 201)


def material(**values):
    return {'evidence_type': 'official_disclosure', 'title': 'Synthetic test citation', 'summary': 'Test-only material',
            'source_name': 'Synthetic source', 'source_url': 'https://source.example/record', 'origin': 'public_osint',
            'source_reliability': 'reliable', 'reliability_rationale': 'Synthetic verification rationale', **values}


def evidence(client, **values):
    return ok(client.post(P+'/evidence', json=material(**values)), 201)


def role(stance='supports'):
    return {'stance': stance, 'directness': 'context' if stance == 'context' else 'direct', 'rationale': 'Explicit test relevance'}


def attach(client, row, stance='supports', evidence_id=None):
    return ok(client.post(P+f"/claims/{row['id']}/evidence", json={
        'expected_version': row['version'], 'evidence_id': evidence_id or evidence(client)['id'], 'link': role(stance)}), 201)


def assessment_payload(client, row, assessment='supported', **values):
    links = ok(client.get(P+f"/claims/{row['id']}/evidence"))['items']
    return {'expected_version': row['version'], 'assessment': assessment, 'rationale': 'Synthetic reviewed conclusion',
            'reviewed_link_ids': [link['id'] for link in links],
            'acknowledged_contradictions': [link['id'] for link in links if link['stance'] == 'contradicts'],
            'conflict_discussion': 'Synthetic contradictions reviewed explicitly',
            'source_verification': 'Synthetic source verification rationale', **values}


def assess(client, row, category='supported', **values):
    return client.post(P+f"/claims/{row['id']}/assessment", json=assessment_payload(client, row, category, **values))


def action(row):
    return {'expected_version': row['version'], 'reason': 'Explicit test lifecycle decision'}


def counts(engine):
    with Session(engine) as db:
        return [db.scalar(select(func.count()).select_from(model)) for model in
                (AttributionEntity, AttributionClaim, AttributionEvidence, AttributionClaimEvidence, AttributionEvent)]


def test_entity_create_get_and_explicit_fields(api):
    client, _ = api
    row = entity(client)
    assert row == ok(client.get(P+'/entities/'+row['id']))
    assert row['version'] == 1 and row['created_by'] == 'local_analyst'
    assert row['aliases'] == ['Synthetic alias'] and row['archived_at'] is None
    assert 'name_key' not in row
    assert datetime.fromisoformat(row['created_at']).tzinfo is not None


def test_entity_pagination_filters_and_literal_search(api):
    client, _ = api
    a = entity(client, canonical_name='Synthetic % underscore_', entity_type='organization')
    b = entity(client, canonical_name='Second Synthetic')
    first = ok(client.get(P+'/entities?limit=1'))
    assert first == {'items': [a], 'limit': 1, 'offset': 0, 'total': 2, 'next_offset': 1}
    assert ok(client.get(P+'/entities?limit=1&offset=1'))['items'] == [b]
    assert ok(client.get(P+'/entities?entity_type=organization'))['items'] == [a]
    assert ok(client.get(P+'/entities', params={'search': '%'}))['items'] == [a]
    assert ok(client.get(P+'/entities?offset=99'))['next_offset'] is None


def test_entity_descriptor_concurrency_and_review_invalidation(api):
    client, _ = api
    row = claim(client)
    row = ok(assess(client, attach(client, row)['claim']))
    target = row['entity_id']
    payload = {'expected_version': 1, 'reason': 'Correct descriptor', 'descriptor': {'canonical_name': 'Revised synthetic entity'}}
    edited = ok(client.patch(P+'/entities/'+target, json=payload))
    assert edited['version'] == 2 and edited['aliases'] == []
    assert client.patch(P+'/entities/'+target, json=payload).status_code == 409
    current = ok(client.get(P+'/claims/'+row['id']))
    assert current['assessment'] == 'supported' and current['needs_review']
    assert current['version'] == row['version']+1


@pytest.mark.parametrize('resource', ['entities', 'claims'])
def test_archive_restore_preserves_material(api, resource):
    client, engine = api
    row = claim(client)
    attached = attach(client, row)
    row = attached['claim'] if resource == 'claims' else ok(client.get(P+'/entities/'+row['entity_id']))
    before = counts(engine)
    archived = ok(client.post(P+f"/{resource}/{row['id']}/archive", json=action(row)))
    assert archived['archived_at'] and archived['version'] == row['version']+1
    assert client.post(P+f"/{resource}/{row['id']}/archive", json=action(archived)).status_code == 409
    assert ok(client.get(P+'/'+resource))['total'] == 0
    assert ok(client.get(P+'/'+resource+'?include_archived=true'))['total'] == 1
    assert ok(client.get(P+'/claims'))['total'] == 0
    restored = ok(client.post(P+f"/{resource}/{row['id']}/restore", json=action(archived)))
    assert restored['archived_at'] is None
    assert counts(engine)[:4] == before[:4]
    assert ok(client.get(P+'/claims/'+attached['claim']['id']))['needs_review']


@pytest.mark.parametrize('path', ['/entities/missing', '/claims/missing', '/evidence/missing',
                                  '/claims/missing/evidence', '/claims/missing/events', '/entities/missing/events', '/evidence/missing/events'])
def test_missing_records(api, path):
    assert api[0].get(P+path).status_code == 404


@pytest.mark.parametrize('chain,address', [('ethereum', '  '+ETH+'  '), ('bitcoin', BTC)])
def test_claim_normalization_and_detail(api, chain, address):
    client, engine = api
    row = claim(client, chain=chain, subject_ref=address)
    assert row['subject_ref'] == (ETH.lower() if chain == 'ethereum' else BTC)
    assert row['entity']['id'] == row['entity_id']
    assert row['assessment'] == 'unassessed' and row['needs_review']
    assert row['active_evidence']['items'] == [] and row['active_evidence_counts']['contradicts'] == 0
    assert ok(client.get(P+'/claims/'+row['id'])) == row
    with Session(engine) as db:
        assert db.query(Address).count() == 0


@pytest.mark.parametrize('archived', [False, True])
def test_duplicate_normalized_claim_conflicts(api, archived):
    client, _ = api
    row = claim(client)
    if archived:
        ok(client.post(P+f"/claims/{row['id']}/archive", json=action(row)))
    result = client.post(P+'/claims', json={'entity_id': row['entity_id'], 'chain': 'ethereum', 'subject_ref': ETH.lower(),
                                          'relationship': row['relationship'], 'scope_note': 'Same logical proposition'})
    assert result.status_code == 409
    assert result.json()['detail']['existing_id'] == row['id']
    assert 'UNIQUE' not in result.text and 'sqlite' not in result.text


@pytest.mark.parametrize('field,value', [('relationship', 'owned_by'), ('relationship', 'associated_with'),
                                       ('subject_ref', 'malformed'), ('chain', 'any'), ('subject_type', 'transaction'),
                                       ('assessment', 'supported'), ('created_by', 'verified-admin')])
def test_claim_creation_rejects_invalid_or_server_fields(api, field, value):
    client, _ = api
    payload = {'entity_id': entity(client)['id'], 'chain': 'ethereum', 'subject_ref': ETH,
               'relationship': 'operated_by', 'scope_note': 'Synthetic scope', field: value}
    assert client.post(P+'/claims', json=payload).status_code == 422


def test_missing_parent_and_claim_filtering(api):
    client, _ = api
    data = {'entity_id': 'missing', 'chain': 'ethereum', 'subject_ref': ETH, 'relationship': 'operated_by', 'scope_note': 'Test scope'}
    assert client.post(P+'/claims', json=data).status_code == 404
    row = claim(client)
    other = claim(client, entity_id=row['entity_id'], relationship='controlled_by')
    filters = {'chain': 'ethereum', 'subject_ref': ETH, 'entity_id': row['entity_id'], 'relationship': 'controlled_by',
               'assessment': 'unassessed', 'needs_review': True, 'limit': 1}
    result = ok(client.get(P+'/claims', params=filters))
    assert result['total'] == 1 and result['items'][0]['id'] == other['id']
    assert client.get(P+'/claims', params={'subject_ref': ETH}).status_code == 422
    assert ok(client.get(P+'/claims?limit=1'))['next_offset'] == 1


def test_scope_update_is_narrow_and_versioned(api):
    client, _ = api
    row = claim(client)
    body = {**action(row), 'scope': {'scope_note': 'Revised scope', 'valid_from': '2026-01-01'}}
    revised = ok(client.patch(P+f"/claims/{row['id']}/scope", json=body))
    assert revised['valid_from'] == '2026-01-01' and revised['needs_review']
    assert client.patch(P+f"/claims/{row['id']}/scope", json=body).status_code == 409
    body['scope']['relationship'] = 'controlled_by'
    assert client.patch(P+f"/claims/{row['id']}/scope", json=body).status_code == 422


@pytest.mark.parametrize('category', ['unassessed', 'possible', 'supported', 'strongly_supported', 'rejected'])
def test_all_assessment_categories_and_event(api, category):
    client, _ = api
    row = attach(client, claim(client))['claim']
    updated = ok(assess(client, row, category))
    assert updated['assessment'] == category and not updated['needs_review']
    assert updated['assessed_by'] == 'local_analyst' and updated['version'] == row['version']+1
    events = ok(client.get(P+f"/claims/{row['id']}/events"))['items']
    assert events[-1]['event_type'] == 'assessment_changed'
    assert events[-1]['payload']['after']['assessment'] == category
    assert events[-1]['payload']['reviewed_links']
    assert client.post(P+f"/claims/{row['id']}/assessment", json=assessment_payload(client, row, category)).status_code == 409


def test_contradiction_requires_explicit_ack_and_discussion(api):
    client, _ = api
    row = ok(assess(client, attach(client, claim(client))['claim']))
    linked = attach(client, row, 'contradicts')
    current = linked['claim']
    assert current['assessment'] == 'supported' and current['needs_review']
    detail = ok(client.get(P+'/claims/'+row['id']))
    assert detail['active_evidence_counts'] == {'supports': 1, 'contradicts': 1, 'context': 0}
    assert assess(client, current, acknowledged_contradictions=[]).status_code == 422
    assert assess(client, current, conflict_discussion='').status_code == 422
    assert assess(client, current, reviewed_link_ids=[]).status_code == 409
    assert ok(client.get(P+'/claims/'+row['id']))['version'] == current['version']
    assert not ok(assess(client, current))['needs_review']


@pytest.mark.parametrize('category', ['possible', 'supported', 'strongly_supported'])
def test_positive_assessment_needs_evidence(api, category):
    client, _ = api
    assert assess(client, claim(client), category).status_code == 422


def test_strong_assessment_requires_source_verification(api):
    client, _ = api
    row = attach(client, claim(client))['claim']
    assert assess(client, row, 'strongly_supported', source_verification='').status_code == 422
    assert ok(assess(client, row, 'strongly_supported'))['assessment'] == 'strongly_supported'


@pytest.mark.parametrize('origin', ['public_osint', 'analyst_added'])
def test_evidence_capture_detail_and_filters(api, origin):
    client, _ = api
    row = evidence(client, origin=origin, source_catalog_id='synthetic-source', published_on='2026-09-12',
                   metadata_json={'seen': '2026-09-12T10:00:00+05:30', 'nested': {'unknown': None}})
    assert ok(client.get(P+'/evidence/'+row['id'])) == row
    assert row['captured_by'] == 'local_analyst' and row['collection_method'] == 'analyst_entry'
    assert row['published_on'] == '2026-09-12' and len(row['content_sha256']) == 64
    assert row['metadata_json']['seen'] == '2026-09-12T10:00:00+05:30'
    assert datetime.fromisoformat(row['captured_at']).utcoffset().total_seconds() == 0
    assert ok(client.get(P+'/evidence', params={'origin': origin, 'source_catalog_id': 'synthetic-source'}))['items'] == [row]
    assert ok(client.get(P+'/evidence?source_catalog_id=missing'))['total'] == 0


def test_internal_datetime_capture_is_json_safe_over_http(api):
    client, engine = api
    with Session(engine) as db:
        row = AttributionService(db).create_evidence(material(metadata_json={'nested': [datetime(2026, 9, 12, 8, tzinfo=timezone.utc)]}))
    result = ok(client.get(P+'/evidence/'+row['id']))
    assert result['metadata_json'] == {'nested': ['2026-09-12T08:00:00+00:00']}


@pytest.mark.parametrize('extra', [
    {'origin': 'commercial_proprietary'}, {'origin': 'privileged_nonpublic'}, {'evidence_type': 'label_snapshot'},
    {'evidence_type': 'research_snapshot'}, {'captured_by': 'admin'}, {'origin_label_id': 'forged'},
    {'source_url': 'https://source.example/?api_key=secret-canary'}, {'source_url': 'https://user:secret-canary@source.example'},
    {'source_locator': 'C:\\private\\secret-canary', 'source_url': None}, {'metadata_json': {'large': 'x'*32769}},
    {'metadata_json': ['not-an-object']}, {'content_sha256': 'forged'},
])
def test_capture_restrictions_and_safe_errors(api, extra):
    client, engine = api
    response = client.post(P+'/evidence', json=material(**extra))
    assert response.status_code == 422 and 'secret-canary' not in response.text
    assert counts(engine) == [0]*5


@pytest.mark.parametrize('stance', ['supports', 'contradicts', 'context'])
def test_link_roles_duplicate_and_inspection(api, stance):
    client, _ = api
    row = claim(client)
    result = attach(client, row, stance)
    link = result['link']
    page = ok(client.get(P+f"/claims/{row['id']}/evidence", params={'stance': stance}))
    assert page['items'][0]['id'] == link['id'] and page['items'][0]['evidence']['title']
    assert page['items'][0]['stance'] == stance
    response = client.post(P+f"/claims/{row['id']}/evidence", json={
        'expected_version': result['claim']['version'], 'evidence_id': link['evidence_id'], 'link': role()})
    assert response.status_code == 409 and response.json()['detail']['existing_id'] == link['id']


def test_withdraw_restore_edit_and_replace_preserve_evidence(api):
    client, _ = api
    linked = attach(client, claim(client))
    row, link = linked['claim'], linked['link']
    path = P+f"/claims/{row['id']}/evidence/{link['id']}"
    original = ok(client.get(P+'/evidence/'+link['evidence_id']))
    withdrawn = ok(client.post(path+'/withdraw', json=action(row)))
    assert withdrawn['link']['withdrawn_at']
    assert ok(client.get(P+f"/claims/{row['id']}/evidence"))['total'] == 0
    assert ok(client.get(P+f"/claims/{row['id']}/evidence?include_withdrawn=true"))['total'] == 1
    restored = ok(client.post(path+'/restore', json=action(withdrawn['claim'])))
    assert restored['link']['withdrawn_at'] is None
    edited = ok(client.patch(path, json={**action(restored['claim']), 'link': role('contradicts')}))
    assert edited['link']['stance'] == 'contradicts'
    replaced = ok(client.post(path+'/replace', json={**action(edited['claim']), 'evidence': material(title='Replacement snapshot'), 'link': role()}))
    assert replaced['withdrawn_link']['id'] == link['id'] and replaced['withdrawn_link']['withdrawn_at']
    assert replaced['link']['evidence_id'] != link['evidence_id']
    assert ok(client.get(P+'/evidence/'+link['evidence_id'])) == original


def test_atomic_capture_link_and_stale_rollback(api):
    client, engine = api
    row = claim(client)
    path = P+f"/claims/{row['id']}/evidence/capture"
    body = {'expected_version': row['version'], 'evidence': material(), 'link': role()}
    linked = ok(client.post(path, json=body), 201)
    assert linked['claim']['version'] == 2
    before = counts(engine)
    assert client.post(path, json=body).status_code == 409
    assert counts(engine) == before


def test_events_order_pagination_scopes_and_snapshot(api):
    client, _ = api
    linked = attach(client, claim(client))
    row = ok(assess(client, linked['claim']))
    path = P+f"/claims/{row['id']}/events"
    first = ok(client.get(path+'?limit=1'))
    assert first['total'] == 3 and first['next_offset'] == 1
    second = ok(client.get(path+'?limit=1&offset=1'))
    assert second['total'] == 3 and second['items'][0]['event_type'] == 'evidence_linked'
    all_events = ok(client.get(path))['items']
    assert [e['sequence'] for e in all_events] == [1, 2, 3]
    assert all_events[-1]['payload']['before']['assessment'] == 'unassessed'
    assert all_events[-1]['payload']['after']['assessment'] == 'supported'
    for resource, identifier in [('entities', row['entity_id']), ('evidence', linked['link']['evidence_id'])]:
        events = ok(client.get(P+f'/{resource}/{identifier}/events'))
        assert events['total'] == 1 and events['items'][0]['event_type'] == 'created'


@pytest.mark.parametrize('resource', ['entities', 'claims', 'evidence', 'claims/missing/evidence', 'claims/missing/events'])
@pytest.mark.parametrize('query', ['limit=0', 'limit=201', 'offset=-1'])
def test_page_bounds(api, resource, query):
    assert api[0].get(P+'/'+resource+'?'+query).status_code == 422


@pytest.mark.parametrize('method,path', [('PATCH', '/evidence/missing'), ('DELETE', '/evidence/missing'),
                                       ('DELETE', '/entities/missing'), ('DELETE', '/claims/missing'),
                                       *[(m, f'/{r}/missing/events') for m in ('POST', 'PATCH', 'DELETE') for r in ('claims', 'entities', 'evidence')]])
def test_forbidden_mutation_surface(api, method, path):
    assert api[0].request(method, P+path, json={}).status_code == 405


@pytest.mark.parametrize('failure,expected', [(IntegrityError('SELECT secret-canary', {}, Exception('private.db')), 409),
                                           (OperationalError('SELECT secret-canary', {}, Exception('private.db')), 409),
                                           (RuntimeError('C:\\private.db secret-canary'), 500)])
def test_late_failure_safe_http_and_atomic_rollback(api, monkeypatch, failure, expected):
    client, engine = api
    def fail(*args, **kwargs):
        raise failure
    monkeypatch.setattr(AttributionService, '_event', fail)
    response = client.post(P+'/entities', json={'canonical_name': 'Synthetic rollback'})
    assert response.status_code == expected
    assert all(value not in response.text for value in ('SELECT', 'secret-canary', 'private.db', 'IntegrityError', 'Traceback'))
    assert counts(engine) == [0]*5


def test_secret_redaction_and_validation_input_not_echoed(api, monkeypatch):
    client, _ = api
    from greedy_collector.config import get_settings
    monkeypatch.setattr(get_settings(), 'etherscan_api_key', 'at2-secret-canary')
    row = evidence(client, summary='Public material with at2-secret-canary', metadata_json={'api_key': 'at2-secret-canary', 'public': 'retained'})
    assert row['metadata_json']['public'] == 'retained'
    assert 'at2-secret-canary' not in str(row)
    assert 'at2-secret-canary' not in client.get(P+'/evidence/'+row['id']+'/events').text
    response = client.post(P+'/entities', json={'canonical_name': 'Synthetic', 'password': 'at2-secret-canary'})
    assert response.status_code == 422 and 'at2-secret-canary' not in response.text
    response = client.post(P+'/entities', content='{"password":"at2-secret-canary",', headers={'content-type': 'application/json'})
    assert response.status_code == 422 and 'at2-secret-canary' not in response.text
    assert 'at2-secret-canary' not in client.get('/openapi.json').text


def test_openapi_explicit_models_enums_and_exact_surface(api):
    client, _ = api
    spec = ok(client.get('/openapi.json'))
    paths = {p: methods for p, methods in spec['paths'].items() if p.startswith(P)}
    legacy_paths = {p for p in spec['paths'] if not p.startswith((API+'/discovery', API+'/clustering', API+'/fund-flow'))}
    assert {p.removeprefix(API+'/clustering') for p in spec['paths'] if p.startswith(API+'/clustering')} == {
        '/capabilities', '/analyze', '/clusters/{cluster_id}', '/clusters/{cluster_id}/graph',
        '/wallet/{chain}/{address}', '/evidence/{evidence_id}/exclude', '/cases/{case_id}/pin',
    }
    assert {p.removeprefix(API+'/fund-flow') for p in spec['paths'] if p.startswith(API+'/fund-flow')} == {
        '/capabilities', '/path', '/neighborhood', '/runs/{run_id}', '/cases/{case_id}/pin',
    }
    assert API+'/chains' in legacy_paths
    assert len(paths) == 25 and len(legacy_paths - {API+'/chains'}) == 64
    assert API+'/risk/observation/{chain}/{address}' in legacy_paths
    assert API+'/labels/{label_id}/state' in legacy_paths
    assert sum(len(methods) for methods in paths.values()) == 31
    for path, methods in paths.items():
        assert 'delete' not in methods
        if path.endswith('/events'):
            assert set(methods) == {'get'}
        for method, operation in methods.items():
            success = [r for code, r in operation['responses'].items() if code.startswith('2')]
            assert success and all(r['content']['application/json']['schema'].get('$ref') for r in success)
            assert operation['responses']['422']['content']['application/json']['schema']['$ref'].endswith('/ErrorResponse')
    schemas = spec['components']['schemas']
    assert schemas['ClaimCreate']['properties']['relationship']['enum'] == ['operated_by', 'controlled_by', 'publicly_declared_by']
    assert schemas['AssessmentUpdate']['properties']['assessment']['enum'] == ['unassessed', 'possible', 'supported', 'strongly_supported', 'rejected']
    assert schemas['EvidenceCreate']['properties']['origin']['enum'] == ['public_osint', 'analyst_added']
    assert 'expected_version' in schemas['AssessmentUpdate']['required']
    assert 'acknowledged_contradictions' in schemas['AssessmentUpdate']['required']
    assert 'metadata_only' not in str(spec) and 'name_key' not in schemas['EntityRead']['properties']


def test_normal_label_and_research_create_no_attribution(api, research_provider):
    client, engine = api
    ok(client.post(API+'/labels/manual', json={'chain': 'bitcoin', 'address': BTC, 'label': 'Synthetic annotation', 'type': 'Unknown'}))
    assert counts(engine) == [0]*5
    result = ok(client.post(API+'/kyc/screen', json={'name': 'Test Company'}))
    assert result['matches'] and counts(engine) == [0]*5


def test_http_attribution_never_changes_wallet_risk(api, monkeypatch):
    client, engine = api
    monkeypatch.setattr(BitcoinAdapter, 'lookup_address', AsyncMock(return_value={'balance_native': '1', 'source_api': 'test-only'}))
    monkeypatch.setattr(BitcoinAdapter, 'transactions', AsyncMock(return_value=[NormalizedTransaction(
        chain='bitcoin', tx_hash='a'*64, from_address='1BoatSLRHtKNngkdXEeobR76b53LETtpyT', to_address=BTC,
        value_native='1', token_symbol='BTC', direction='incoming', source_api='test-only')]))
    before = ok(client.post(API+'/lookup/address', json={'chain': 'bitcoin', 'address': BTC}))
    assert counts(engine) == [0]*5
    row = attach(client, claim(client, chain='bitcoin', subject_ref=BTC))['claim']
    ok(assess(client, row, 'strongly_supported'))
    with Session(engine) as db:
        assert db.query(RiskResult).count() == 1 and db.query(Label).count() == 0 and db.query(Address).count() == 1
    after = ok(client.post(API+'/lookup/address', json={'chain': 'bitcoin', 'address': BTC}))
    assert after['risk']['calculated_at'] != before['risk']['calculated_at']
    assert {key:value for key,value in after['risk'].items() if key!='calculated_at'} == {key:value for key,value in before['risk'].items() if key!='calculated_at'}


def test_current_routes_and_attribution_workspace_without_seed_records(api):
    client, engine = api
    for path in ('/', '/health', '/docs', '/openapi.json', '/static/js/app.js', '/static/app.css'):
        assert client.get(path).status_code == 200
    html = client.get('/').text
    assert html.count('data-workspace=') == 12 and 'data-workspace="attribution"' in html
    assert counts(engine) == [0]*5


@pytest.mark.parametrize('value', [0, -1, True, '1', 1.5])
def test_expected_version_is_a_positive_integer(api, value):
    client, _ = api
    row = entity(client)
    assert client.post(P+f"/entities/{row['id']}/archive", json={**action(row), 'expected_version': value}).status_code == 422


def test_link_cannot_be_edited_through_another_claim(api):
    client, engine = api
    linked = attach(client, claim(client))
    other = claim(client)
    before = counts(engine)
    path = P+f"/claims/{other['id']}/evidence/{linked['link']['id']}/withdraw"
    assert client.post(path, json=action(other)).status_code == 404
    assert counts(engine) == before


def test_detail_counts_include_links_beyond_first_page(api):
    client, engine = api
    row = claim(client)
    # Efficient setup through the authoritative services; HTTP inspects all pages.
    with Session(engine) as db:
        svc = AttributionService(db)
        for number in range(51):
            result = svc.create_and_link_evidence(row['id'], material(title=f'Synthetic capture {number}'),
                                                  role('contradicts' if number == 50 else 'supports'),
                                                  expected_version=row['version'])
            row = result['claim']
    detail = ok(client.get(P+'/claims/'+row['id']))
    assert len(detail['active_evidence']['items']) == 50
    assert detail['active_evidence']['total'] == 51 and detail['active_evidence']['next_offset'] == 50
    assert detail['active_evidence_counts']['contradicts'] == 1
    last = ok(client.get(P+f"/claims/{row['id']}/evidence?offset=50"))
    assert len(last['items']) == 1 and last['items'][0]['stance'] == 'contradicts'
    assert last['total'] == 51 and last['next_offset'] is None


def test_normal_migrated_scheduler_startup_shutdown_has_no_side_effects(migrated_template, tmp_path):
    target = tmp_path/'normal-startup.db'
    shutil.copyfile(migrated_template, target)
    code = '''
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import text
import httpx
import main
from greedy_collector.database import engine
from greedy_collector.monitoring import scheduler
from greedy_collector.attribution.service import TABLES
with engine.connect() as connection:
    before_revision = connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one()
with patch.object(httpx.AsyncClient, 'request', side_effect=AssertionError('No provider calls')):
    with TestClient(main.app) as client:
        assert scheduler.running
        for path in ['/', '/health', '/docs', '/openapi.json']:
            assert client.get(path).status_code == 200
        assert client.get('/api/greedy-collector/attribution/entities').json()['total'] == 0
        assert client.get('/').text.count('data-workspace=') == 12
assert not scheduler.running
with engine.connect() as connection:
    assert connection.execute(text('SELECT version_num FROM alembic_version')).scalar_one() == before_revision
    for table in TABLES:
        assert connection.execute(text('SELECT COUNT(*) FROM '+table)).scalar_one() == 0
    assert connection.execute(text('PRAGMA foreign_key_check')).all() == []
'''
    env = {**os.environ, 'PYTHONPATH': str(ROOT), 'PYTHON_DOTENV_DISABLED': '1',
           'GREEDY_COLLECTOR_DATABASE_URL': 'sqlite:///'+target.as_posix(),
           'GREEDY_COLLECTOR_GRAPH_BACKEND': 'sqlite', 'GREEDY_COLLECTOR_MONITORING_BACKEND': 'apscheduler'}
    for key in ['ETHERSCAN_API_KEY', 'ALCHEMY_API_KEY', 'OPENSANCTIONS_API_KEY', 'VIRUSTOTAL_API_KEY', 'URLSCAN_API_KEY']:
        env[key] = ''
    result = subprocess.run([sys.executable, '-B', '-c', code], cwd=tmp_path, env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr
