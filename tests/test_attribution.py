"""AT-1 service/DB regressions; all subjects and evidence are synthetic test data."""
from copy import deepcopy
from datetime import date, datetime, timezone
import json

import pytest
from sqlalchemy import delete, func, insert, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from greedy_collector.database import create_fk_enabled_engine
from greedy_collector.models import (Base, AttributionEntity as Entity, AttributionClaim as Claim,
    AttributionEvidence as Evidence, AttributionClaimEvidence as Link, AttributionEvent as Event, new_id)
from greedy_collector.attribution.service import AttributionService
from greedy_collector.attribution.domain import AttributionError, Conflict, NotFound, SchemaUnavailable, normalize_subject
from greedy_collector.attribution.enums import RELATIONSHIPS, ASSESSMENTS, STANCES, ENTITY_TYPES

ETH = '0x' + 'aB' * 20
BTC = '1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa'
BECH = 'bc1qw508d6qejxtdg4y5r3zarvary0c5xw7kv8f3t4'


@pytest.fixture
def svc(tmp_path, monkeypatch):
    def no_http(*args, **kwargs): raise AssertionError('Attribution must not request a provider')
    monkeypatch.setattr('httpx.AsyncClient.request', no_http)
    monkeypatch.setattr('httpx.Client.request', no_http)
    engine = create_fk_enabled_engine('sqlite:///' + (tmp_path / 'attribution.db').as_posix())
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield AttributionService(db, metadata_only=True)
    engine.dispose()


def entity(svc, **overrides):
    return svc.create_entity({'canonical_name': 'Synthetic Example Service', 'entity_type': 'service', 'aliases': ['Synthetic Alias'], **overrides})


def claim(svc, target=None, **overrides):
    return svc.create_claim({'entity_id': target or entity(svc)['id'], 'chain': 'ethereum', 'subject_ref': ETH,
                             'relationship': 'operated_by', 'scope_note': 'Test-only operation claim; period unknown', **overrides})


def material(**overrides):
    return {'evidence_type': 'official_disclosure', 'title': 'Synthetic source citation',
            'summary': 'Synthetic test statement about a public address', 'source_name': 'Example test publisher',
            'source_url': 'https://source.example/record/1', 'origin': 'public_osint',
            'source_reliability': 'reliable', 'reliability_rationale': 'Synthetic origin verification in this test', **overrides}


def attach(svc, row, stance='supports', **overrides):
    evidence = svc.create_evidence(material(**overrides))
    result = svc.link_evidence(row['id'], evidence['id'], {'stance': stance,
        'directness': 'context' if stance == 'context' else 'direct', 'rationale': 'Test-only evidential connection'}, expected_version=row['version'])
    return result['claim'], result['link'], evidence


def assess(svc, row, assessment='supported', **overrides):
    links = svc.list_claim_evidence(row['id'])['items']
    args = {'expected_version': row['version'], 'reviewed_link_ids': [link['id'] for link in links],
            'acknowledged_contradictions': [link['id'] for link in links if link['stance'] == 'contradicts'],
            'conflict_discussion': 'Synthetic contradiction reviewed for scoped meaning',
            'source_verification': 'Synthetic direct primary citation verified for exact subject and scope'}
    args.update(overrides)
    return svc.change_assessment(row['id'], assessment, 'Test analyst rationale', **args)


@pytest.mark.parametrize('kind', ENTITY_TYPES)
def test_entity_types_create_retrieve_aliases_no_name_uniqueness(svc, kind):
    first = entity(svc, entity_type=kind, canonical_name='  Synthetic   Example  ')
    second = entity(svc, entity_type=kind, canonical_name='Synthetic Example')
    assert first['id'] != second['id'] and first['name_key'] == second['name_key']
    assert svc.get_entity(first['id'])['aliases'] == ['Synthetic Alias']
    assert svc.list_entities(search='SYNTHETIC', entity_type=kind)['total'] == 2
    assert first['created_by'] == 'local_analyst'


@pytest.mark.parametrize('relationship', RELATIONSHIPS)
def test_claim_creation_and_entity_reuse(svc, relationship):
    target = entity(svc)
    row = claim(svc, target['id'], relationship=relationship)
    assert row['assessment'] == 'unassessed' and row['needs_review'] is True
    assert row['version'] == 1 and row['subject_ref'] == ETH.lower()
    assert svc.get_claim(row['id'])['entity_id'] == target['id']
    assert svc.list_entities()['total'] == 1
    event = svc.event_history(claim_id=row['id'])['items'][0]
    assert event['event_type'] == 'created' and event['sequence'] == 1


@pytest.mark.parametrize('overrides', [{'relationship':'owned_by'}, {'relationship':'associated_with'}, {'subject_type':'domain'},
    {'chain':'any'}, {'subject_ref':'arbitrary'}, {'assessment':'supported'}, {'confidence':.9}, {'created_by':'someone'},
    {'scope_note':' '}, {'valid_from':'2026-09-12','valid_to':'2026-09-01'}])
def test_invalid_claim_fields_rejected(svc, overrides):
    with pytest.raises(AttributionError): claim(svc, **overrides)
    assert svc.list_claims(include_archived=True)['total'] == 0


def test_subject_normalization_preserves_base58_and_normalizes_supported_bech32(svc):
    assert normalize_subject('bitcoin', ' '+BTC+' ') == BTC
    assert normalize_subject('bitcoin', BECH.upper()) == BECH
    target = entity(svc)['id']
    row = claim(svc, target, chain='bitcoin', subject_ref=BTC)
    assert row['subject_ref'] == BTC
    with pytest.raises(AttributionError):
        claim(svc, target, chain='bitcoin', subject_ref=BTC.lower())
    b = claim(svc, target, chain='bitcoin', subject_ref=BECH)
    with pytest.raises(Conflict) as error: claim(svc, target, chain='bitcoin', subject_ref=BECH.upper())
    assert error.value.existing_id == b['id']


def test_duplicate_claim_case_variants_rejected_even_archived(svc):
    row = claim(svc)
    for address in [ETH, ETH.lower(), ' '+ETH+' ']:
        with pytest.raises(Conflict) as error: claim(svc, row['entity_id'], subject_ref=address)
        assert error.value.existing_id == row['id']
    svc.archive_claim(row['id'], expected_version=1, reason='Synthetic archive')
    with pytest.raises(Conflict): claim(svc, row['entity_id'])
    assert claim(svc, row['entity_id'], relationship='controlled_by')['id'] != row['id']


@pytest.mark.parametrize('assessment', ASSESSMENTS)
def test_explicit_assessments_and_event_history(svc, assessment):
    row, link, evidence = attach(svc, claim(svc))
    reviewed = assess(svc, row, assessment)
    assert reviewed['assessment'] == assessment and reviewed['needs_review'] is False
    assert reviewed['assessed_by'] == 'local_analyst' and reviewed['version'] == 3
    events = svc.event_history(claim_id=row['id'])['items']
    assert [event['sequence'] for event in events] == [1,2,3]
    assert [event['event_type'] for event in events] == ['created','evidence_linked','assessment_changed']
    assert events[-1]['payload']['reviewed_links'][0]['evidence_id'] == evidence['id']
    assert events[-1]['payload']['before']['assessment'] == 'unassessed'


@pytest.mark.parametrize('assessment', ['possible','supported','strongly_supported','confirmed'])
def test_assessment_cannot_skip_support(svc, assessment):
    with pytest.raises(AttributionError): assess(svc, claim(svc), assessment)


def test_strong_assessment_requires_reliability_and_verification(svc):
    row, _, _ = attach(svc, claim(svc), source_reliability='unassessed', reliability_rationale='')
    with pytest.raises(AttributionError): assess(svc, row)
    with pytest.raises(AttributionError): assess(svc, row, 'strongly_supported')
    row2, _, _ = attach(svc, claim(svc))
    with pytest.raises(AttributionError): assess(svc, row2, 'strongly_supported', source_verification='')


def test_contradiction_preserves_assessment_and_requires_explicit_review(svc):
    row, _, _ = attach(svc, claim(svc)); row = assess(svc, row)
    row, contradiction, _ = attach(svc, row, 'contradicts')
    assert row['assessment'] == 'supported' and row['needs_review'] is True
    with pytest.raises(AttributionError): assess(svc, row, acknowledged_contradictions=[])
    with pytest.raises(AttributionError): assess(svc, row, conflict_discussion='')
    with pytest.raises(Conflict): assess(svc, row, reviewed_link_ids=[])
    rejected = assess(svc, row, 'rejected')
    assert rejected['assessment'] == 'rejected' and not rejected['needs_review']
    assert svc.event_history(claim_id=row['id'])['items'][-1]['payload']['before']['assessment'] == 'supported'


@pytest.mark.parametrize('stance', STANCES)
def test_reusable_evidence_and_duplicate_link_semantics(svc, stance):
    row, link, evidence = attach(svc, claim(svc), stance)
    second = claim(svc)
    linked = svc.link_evidence(second['id'], evidence['id'], {'stance':'context','directness':'context','rationale':'Different contextual role'},expected_version=1)
    assert linked['link']['evidence_id'] == link['evidence_id']
    with pytest.raises(Conflict): svc.link_evidence(row['id'], evidence['id'], {'stance':'contradicts','directness':'direct','rationale':'Duplicate'},expected_version=2)
    assert svc.list_evidence()['total'] == 1


def test_withdraw_restore_replace_preserve_snapshots(svc):
    row, link, evidence = attach(svc, claim(svc)); row = assess(svc, row)
    result = svc.withdraw_evidence(row['id'], link['id'], expected_version=row['version'], reason='Retain but withdraw')
    assert result['claim']['assessment'] == 'supported' and result['claim']['needs_review']
    assert svc.list_claim_evidence(row['id'])['total'] == 0
    assert svc.list_claim_evidence(row['id'],include_withdrawn=True)['total'] == 1
    restored = svc.withdraw_evidence(row['id'], link['id'], expected_version=result['claim']['version'], reason='Restore citation', restore=True)
    replaced = svc.replace_evidence(row['id'],link['id'],material(summary='Corrected synthetic citation'),
        {'stance':'context','directness':'context','rationale':'Correction'},expected_version=restored['claim']['version'],reason='Explicit correction')
    assert replaced['claim']['version'] == restored['claim']['version'] + 1
    assert replaced['withdrawn_link']['withdrawn_at'] and svc.get_evidence(evidence['id']) == evidence
    assert svc.list_evidence()['total'] == 2


def test_archive_restore_entity_claim_and_review_invalidation(svc):
    row, _, _ = attach(svc, claim(svc)); row = assess(svc,row)
    archived = svc.archive_entity(row['entity_id'],expected_version=1,reason='Archive entity')
    assert svc.list_claims()['total'] == svc.list_entities()['total'] == 0
    assert svc.get_claim(row['id'])['assessment'] == 'supported'
    with pytest.raises(Conflict): assess(svc,row)
    svc.archive_entity(row['entity_id'],expected_version=archived['version'],reason='Restore entity',restore=True)
    row = svc.get_claim(row['id']); assert row['needs_review']
    archived_claim = svc.archive_claim(row['id'],expected_version=row['version'],reason='Archive claim')
    restored = svc.archive_claim(row['id'],expected_version=archived_claim['version'],reason='Restore claim',restore=True)
    assert restored['needs_review'] and restored['assessment'] == 'supported'
    assert svc.event_history(claim_id=row['id'])['items'][-2]['event_type'] == 'archived'


def test_scope_and_entity_descriptor_changes_are_audited(svc):
    row = claim(svc)
    updated = svc.update_claim_scope(row['id'],{'scope_note':'Revised unknown scope'},expected_version=1,reason='Clarify scope')
    assert updated['version'] == 2
    svc.update_entity(row['entity_id'],{'canonical_name':'Revised synthetic entity'},expected_version=1,reason='Revise descriptor')
    assert svc.get_claim(row['id'])['version'] == 3
    event = svc.event_history(claim_id=row['id'])['items'][-1]
    assert event['event_type'] == 'review_required' and event['actor_kind'] == 'system'


def test_two_sessions_stale_version_cannot_overwrite(svc):
    row = claim(svc)
    with Session(svc.db.get_bind()) as second_db:
        other = AttributionService(second_db,metadata_only=True)
        old = other.get_claim(row['id'])
        winner = svc.update_claim_scope(row['id'],{'scope_note':'Winning version'},expected_version=1,reason='First session')
        with pytest.raises(Conflict): other.update_claim_scope(row['id'],{'scope_note':'Stale overwrite'},expected_version=old['version'],reason='Second session')
        assert other.get_claim(row['id'])['scope_note'] == 'Winning version'
        assert winner['version'] == 2
    assert svc.event_history(claim_id=row['id'])['total'] == 2


@pytest.mark.parametrize('operation', ['assessment','capture_link','entity_revision'])
def test_event_failure_rolls_back_all_material_state(svc,monkeypatch,operation):
    row = claim(svc); before_claim = svc.get_claim(row['id']); before_entity = svc.get_entity(row['entity_id'])
    counts = [svc.db.scalar(select(func.count()).select_from(model)) for model in [Entity,Claim,Evidence,Link,Event]]
    def fail(*args,**kwargs): raise RuntimeError('Synthetic audit insert failure')
    monkeypatch.setattr(svc,'_event',fail)
    with pytest.raises(RuntimeError):
        if operation == 'assessment': assess(svc,row,'rejected')
        elif operation == 'capture_link': svc.create_and_link_evidence(row['id'],material(),{'stance':'supports','directness':'direct','rationale':'Synthetic'},expected_version=1)
        else: svc.update_entity(row['entity_id'],{'canonical_name':'Rolled back'},expected_version=1,reason='Rollback test')
    assert svc.get_claim(row['id']) == before_claim and svc.get_entity(row['entity_id']) == before_entity
    assert [svc.db.scalar(select(func.count()).select_from(model)) for model in [Entity,Claim,Evidence,Link,Event]] == counts


def test_failed_link_after_capture_leaves_no_orphans(svc):
    row = claim(svc)
    with pytest.raises(Conflict): svc.create_and_link_evidence(row['id'],material(),{'stance':'supports','directness':'direct','rationale':'Synthetic'},expected_version=99)
    assert svc.list_evidence()['total'] == 0
    assert svc.event_history(claim_id=row['id'])['total'] == 1


@pytest.mark.parametrize('model,field', [(Claim,'entity_id'),(Link,'claim_id'),(Link,'evidence_id')])
def test_invalid_foreign_keys_fail(svc,model,field):
    row, link, _ = attach(svc, claim(svc))
    source = svc.db.get(model,row['id'] if model is Claim else link['id'])
    values = {column.name:deepcopy(getattr(source,column.name)) for column in model.__table__.columns}
    values.update(id=new_id(),**{field:'missing-reference'})
    with pytest.raises(IntegrityError):
        svc.db.execute(insert(model).values(**values)); svc.db.commit()
    svc.db.rollback()
    assert svc.db.execute(text('PRAGMA foreign_key_check')).all() == []


@pytest.mark.parametrize('model,operation', [(Evidence,'update'),(Evidence,'delete'),(Event,'update'),(Event,'delete')])
def test_immutable_database_and_orm_rows(svc,model,operation):
    item = svc.create_evidence(material())
    row = svc.db.get(Evidence,item['id']) if model is Evidence else svc.db.scalar(select(Event).where(Event.evidence_id==item['id']))
    identifier = row.id
    with pytest.raises(ValueError,match='immutable'):
        if operation == 'delete': svc.db.delete(row)
        else: setattr(row,'summary' if model is Evidence else 'reason','Rewritten')
        svc.db.flush()
    svc.db.rollback()
    with pytest.raises(IntegrityError,match='immutable'):
        statement = delete(model).where(model.id==identifier) if operation=='delete' else update(model).where(model.id==identifier).values(**{'summary' if model is Evidence else 'reason':'Rewritten'})
        svc.db.execute(statement); svc.db.commit()
    svc.db.rollback()
    assert svc.db.get(model,identifier) is not None


def test_nested_datetime_metadata_and_fingerprint_are_json_safe(svc):
    stamp = datetime(2026,9,12,8,tzinfo=timezone.utc)
    payload = material(published_on=date(2026,9,1),metadata_json={'nested':[{'at':stamp,'day':date(2026,9,2)}],'unknown':None})
    first=svc.create_evidence(payload); second=svc.create_evidence(payload)
    assert first['metadata_json']['nested'][0]['at'] == stamp.isoformat()
    assert first['published_on'] == '2026-09-01' and first['content_sha256'] == second['content_sha256']
    assert first['id'] != second['id'] and first['captured_at'].endswith('+00:00')
    assert json.loads(json.dumps(svc.get_evidence(first['id']))) == first


@pytest.mark.parametrize('overrides', [{'source_url':'javascript:alert(1)'},{'source_url':'https://user:pass@source.example/'},
    {'source_url':'https://source.example/?api_key=test-only-secret'},{'origin':'privileged_nonpublic'},
    {'origin':'commercial_proprietary'},{'evidence_type':'label_snapshot'},{'collection_method':'research_snapshot'},
    {'metadata_json':{'bad':float('nan')}},{'metadata_json':{'bad':object()}},{'metadata_json':{'large':'x'*32769}},
    {'source_url':None,'source_locator':'C:\\private\\source.txt'},{'source_url':None},
    {'evidence_type':'analyst_observation','analyst_note':''},{'captured_by':'forged actor'}])
def test_evidence_validation_rejects_unsafe_or_unsupported_capture(svc,overrides):
    with pytest.raises(AttributionError) as error: svc.create_evidence(material(**overrides))
    assert 'test-only-secret' not in str(error.value)
    assert svc.list_evidence()['total'] == 0


def test_analyst_observation_and_credential_redaction(svc,monkeypatch):
    from greedy_collector.config import get_settings
    monkeypatch.setattr(get_settings(),'opensanctions_api_key','synthetic-secret-only')
    evidence=svc.create_evidence(material(evidence_type='analyst_observation',source_url=None,origin='analyst_added',
        analyst_note='Synthetic observation',metadata_json={'api_key':'synthetic-secret-only','public':'Keep citation'},summary='Text synthetic-secret-only'))
    assert 'synthetic-secret-only' not in json.dumps(evidence)
    assert evidence['metadata_json']['public'] == 'Keep citation'


def test_pagination_and_missing_records(svc):
    for _ in range(3): entity(svc)
    first=svc.list_entities(limit=2)
    assert first['total']==3 and first['next_offset']==2 and len(svc.list_entities(limit=2,offset=2)['items'])==1
    with pytest.raises(NotFound): svc.get_evidence('missing')
    with pytest.raises(AttributionError): svc.list_entities(limit=201)
    row=claim(svc); assess(svc,row,'rejected')
    events=svc.event_history(claim_id=row['id'],limit=1)
    assert events['next_sequence']==1
    assert svc.event_history(claim_id=row['id'],after_sequence=1)['items'][0]['sequence']==2


def test_guard_rejects_missing_revision_and_missing_triggers(svc):
    with pytest.raises(SchemaUnavailable): AttributionService(svc.db)
    svc.db.execute(text('DROP TRIGGER attribution_events_no_delete')); svc.db.commit()
    with pytest.raises(SchemaUnavailable): AttributionService(svc.db,metadata_only=True)


@pytest.mark.parametrize('model,replace_id',[(Evidence,False),(Event,False),(Event,True)])
def test_insert_or_replace_cannot_bypass_immutable_history(svc,model,replace_id):
    item=svc.create_evidence(material())
    row=svc.db.get(Evidence,item['id']) if model is Evidence else svc.db.scalar(select(Event).where(Event.evidence_id==item['id']))
    values={column.name:deepcopy(getattr(row,column.name)) for column in model.__table__.columns}
    values['summary' if model is Evidence else 'reason']='Forbidden replacement'
    if replace_id:values['id']=new_id()
    with pytest.raises(IntegrityError,match='immutable'):
        svc.db.execute(insert(model).prefix_with('OR REPLACE').values(**values));svc.db.commit()
    svc.db.rollback()
    assert svc.get_evidence(item['id'])==item


def test_late_claim_event_failure_rolls_back_capture_link_and_version(svc,monkeypatch):
    row=claim(svc);original=svc._event
    def fail_claim(target,*args,**kwargs):
        if isinstance(target,Claim):raise RuntimeError('Synthetic late claim audit failure')
        return original(target,*args,**kwargs)
    monkeypatch.setattr(svc,'_event',fail_claim)
    with pytest.raises(RuntimeError):svc.create_and_link_evidence(row['id'],material(),{'stance':'supports','directness':'direct','rationale':'Synthetic'},expected_version=1)
    assert svc.get_claim(row['id'])['version']==1
    assert svc.list_evidence()['total']==svc.list_claim_evidence(row['id'])['total']==0
    assert svc.db.scalar(select(func.count()).select_from(Event))==2


def test_late_entity_invalidation_failure_rolls_back_all_target_streams(svc,monkeypatch):
    first=claim(svc);second=claim(svc,first['entity_id'],relationship='controlled_by');original=svc._event
    touched=[]
    def fail_second(target,*args,**kwargs):
        if isinstance(target,Claim):
            touched.append(target.id)
            if len(touched)==2:raise RuntimeError('Synthetic second stream failure')
        return original(target,*args,**kwargs)
    monkeypatch.setattr(svc,'_event',fail_second)
    with pytest.raises(RuntimeError):svc.update_entity(first['entity_id'],{'canonical_name':'Should roll back'},expected_version=1,reason='Synthetic transaction test')
    assert len(touched)==2
    assert svc.get_entity(first['entity_id'])['version']==1
    assert svc.get_claim(first['id'])['version']==svc.get_claim(second['id'])['version']==1
    assert svc.db.scalar(select(func.count()).select_from(Event))==3


def test_db_unique_and_enum_constraints_cannot_be_bypassed(svc):
    row,link,_=attach(svc,claim(svc))
    for model,identifier,overrides in [(Claim,row['id'],{}),(Link,link['id'],{}),(Claim,row['id'],{'relationship':'owned_by'})]:
        source=svc.db.get(model,identifier)
        values={column.name:deepcopy(getattr(source,column.name)) for column in model.__table__.columns}
        values.update(id=new_id(),**overrides)
        with pytest.raises(IntegrityError):svc.db.execute(insert(model).values(**values));svc.db.commit()
        svc.db.rollback()
