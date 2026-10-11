"""Read-only Discovery pivot over locally synchronized OFAC SDN snapshots."""
from datetime import datetime,timezone
from ..sanctions.service import screen,current_snapshot
from .domain import canonical_subject

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
