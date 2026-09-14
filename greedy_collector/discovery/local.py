"""Read-only persisted Label pivot and local manual-action generation. No HTTP."""
from datetime import datetime,timezone
from urllib.parse import urlencode
from sqlalchemy import select,func
from ..models import Label
from .domain import canonical_subject,clean,public_url,DiscoveryError

class LocalLabelsExecutor:
    def __init__(self,sessions):self.sessions=sessions

    async def execute(self,context):
        context.checkpoint()
        subject=context.subject;chain=subject['namespace'];address=subject['canonical_value']
        maximum=context.parameters['max_results']
        stored=func.trim(Label.address,' \t\r\n\v\f')
        # ETH and accepted Bech32 use the shared canonical case convention;
        # Base58 is case-sensitive. Chain=any is retained as annotation scope.
        comparison=func.lower(stored)==address if chain=='ethereum' or address.startswith('bc1') else stored==address
        with self.sessions() as db:
            rows=db.scalars(select(Label).where(Label.chain.in_((chain,'any')),comparison).order_by(Label.id).limit(maximum+1)).all()
            records=[]
            for row in rows[:maximum]:
                context.checkpoint()
                if canonical_subject('blockchain_address',chain,row.address)['canonical_value']!=address:
                    raise DiscoveryError('Local annotation canonical match failed')
                snapshot=clean({c.name:getattr(row,c.name) for c in Label.__table__.columns})
                try:url=public_url(snapshot['source'])
                except DiscoveryError:url=None
                records.append({'kind':'candidate_evidence','predicate':'locally_labeled_as',
                    'from':{'kind':'blockchain_address','namespace':chain,'value':address},
                    'to':{'kind':'annotation','namespace':'gc-label','value':row.id},
                    # Stable Label identity; changed material remains a new immutable
                    # observation under this candidate, with renewed review attention.
                    'fact_key':{'label_id':row.id},
                    'observation':{'kind':'local_label_snapshot','source_record_key':'label:'+row.id,
                        'origin_label_id':row.id,'source_locator':'label:'+row.id,'source_url':url,
                        'title':snapshot['label'],'summary':f"Stored annotation: {snapshot['label']}. Original annotation source: {snapshot['source']}. Confidence is annotation metadata, not identity probability.",
                        'verification':'not_applicable','source_class':'local_annotation',
                        'observed_at':row.last_updated,'retrieved_at':datetime.now(timezone.utc),
                        'source_snapshot':{'schema_version':1,'source_subsystem':'Greedy Collector Labels','record':snapshot,
                            'scope_note':'Chain-unspecified annotation; matched to this canonical wallet.' if row.chain=='any' else 'Chain-specific stored annotation.'}}})
        return {'records':records,'coverage':'limit_reached' if len(rows)>maximum else 'bounded'}

def exact_web_actions(subject):
    canonical=canonical_subject('blockchain_address',subject['namespace'],subject['canonical_value'])
    query='"'+canonical['canonical_value']+'"'
    return [{'source_id':'google','source_name':'Google','query':query,
             'url':'https://www.google.com/search?'+urlencode({'q':query}),
             'status':'manual_action_available',
             'note':'The search engine was not queried by Greedy Collector. Open this link explicitly to search on the external site. Quoted search intent does not guarantee exact provider matching or coverage.'}]
