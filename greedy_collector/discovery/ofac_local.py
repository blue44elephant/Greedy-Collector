"""Read-only Discovery pivot over locally synchronized OFAC SDN snapshots."""
from datetime import datetime,timezone
from ..sanctions.service import screen,current_snapshot
from .domain import canonical_subject


def verified_material(db, result, observation, source, subject):
    """Accept only a recorded local OFAC association, never an ordinary web tag."""
    if (source.transform_id, source.source_id, observation.kind, result.predicate) != (
            'wallet.ofac_sdn_match', 'ofac_sdn', 'verified_page_observation', 'publicly_listed_by'):
        return False
    from ..models import SanctionsSnapshot, SanctionsEntity, SanctionsIdentifier
    from ..sanctions.service import _row

    snapshot = observation.source_snapshot
    entity = snapshot.get('entity') or {}
    identifier = snapshot.get('identifier') or {}
    if snapshot.get('source_id') != 'ofac_sdn' or subject.kind != 'blockchain_address':
        return False
    if snapshot.get('listing_state') not in ('CURRENTLY_LISTED', 'HISTORICALLY_LISTED'):
        return False
    if snapshot.get('match_type') not in ('DIRECT_CHAIN_MATCH', 'EXACT_TEXT_MATCH_CHAIN_UNRESOLVED', 'TEXT_MATCH_OTHER_CHAIN'):
        return False
    if not all(isinstance(value, str) and value for value in (snapshot.get('snapshot_id'), entity.get('id'), identifier.get('id'))):
        return False
    stored = db.get(SanctionsSnapshot, snapshot['snapshot_id'])
    stored_entity = db.get(SanctionsEntity, entity['id'])
    stored_identifier = db.get(SanctionsIdentifier, identifier['id'])
    return bool(stored and stored.sha256 == snapshot.get('snapshot_sha256')
        and stored_entity and stored_identifier
        and stored_entity.snapshot_id == stored.id and stored_identifier.snapshot_id == stored.id
        and stored_identifier.entity_id == stored_entity.id
        and _row(stored_entity) == entity and _row(stored_identifier) == identifier
        and result.fact_key == {'source_entity_id': entity['source_entity_id'],
            'source_field': identifier['source_field'], 'raw_value': identifier['raw_value'], 'snapshot_id': stored.id})

class OfacLocalExecutor:
    def __init__(self,sessions):self.sessions=sessions
    async def execute(self,context):
        context.checkpoint()
        chain=context.subject['namespace'];address=context.subject['canonical_value']
        with self.sessions() as db:
            result=screen(db,chain,address)
            records=[]
            if result['match_type'] not in ('NO_MATCH','UNAVAILABLE'):
                for association in result['associations'][:context.parameters['max_results']]:
                    context.checkpoint()
                    entity=association['entity'];identifier=association['identifier']
                    key={'source_entity_id':entity['source_entity_id'],'source_field':identifier['source_field'],
                         'raw_value':identifier['raw_value'],'snapshot_id':association['snapshot_id']}
                    records.append({'kind':'candidate_evidence','predicate':'publicly_listed_by',
                        'from':{'kind':'blockchain_address','namespace':chain,'value':address},
                        'to':{'kind':'url','namespace':'web','value':'https://sanctionssearch.ofac.treas.gov/'},
                        'fact_key':key,'observation':{
                            'kind':'verified_page_observation','source_record_key':'ofac:'+entity['source_entity_id']+':'+identifier['id'],
                            'source_locator':'ofac-sdn:'+entity['source_entity_id'],
                            'source_url':'https://sanctionssearch.ofac.treas.gov/',
                            'title':'OFAC SDN association: '+entity['name'],
                            'summary':'OFAC SDN associates this digital-currency identifier with the listed source record. No ownership inference.',
                            'verification':'technical_verified','match_context':{'source_field':identifier['source_field'],'raw_value':identifier['raw_value'],'match_type':result['match_type']},'source_class':'authoritative_local_snapshot',
                            'observed_at':association['snapshot_retrieved_at'],
                            'retrieved_at':datetime.now(timezone.utc),
                            'source_snapshot':{'source_id':'ofac_sdn','schema_version':1,
                                'snapshot_id':association['snapshot_id'],'snapshot_sha256':association['snapshot_sha256'],
                                'match_type':result['match_type'],'listing_state':result['listing_state'],
                                'entity':entity,'identifier':identifier}}})
            return {'records':records,
                    'coverage':'limit_reached' if len(result['associations'])>context.parameters['max_results'] else 'bounded'}
