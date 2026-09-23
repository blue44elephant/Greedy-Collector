"""Explicit, atomic handoffs of local source records. No source URL retrieval."""
from ..chains import is_supported_chain
import re
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from sqlalchemy import select
from pydantic import ValidationError

from ..models import Label, KycMatch, KycScreeningRun
from ..kyc.sources import SOURCE_CATALOG
from ..kyc.presentation import sanitize_research, sensitive_name
from .domain import AttributionError, Conflict, EvidenceContentInput, LinkInput, fingerprint, json_safe, normalize_subject
from .service import AttributionService, Evidence, Link, ACTOR, atomic, row_data


def private_key(key):
    name=re.sub(r'[^a-z0-9]', '', key.lower())
    return sensitive_name(key) or any(part in name for part in (
        'apikey','password','secret','credential','authorization','accesstoken','refreshtoken',
        'privatekey','cookie','stacktrace','traceback','debug','internal','localpath'))


def public_url(value):
    """Retain public locators, removing credentials rather than retaining unsafe URLs."""
    try:
        url=urlsplit(value); url.port
        if url.scheme not in ('https','http') or not url.hostname or any(ord(c)<33 for c in value):
            return None
        # A configured secret in a path is redacted by sanitize_research; withhold that URL.
        if '[redacted]' in url.path or '%5bredacted%5d' in url.path.lower():return None
        query=urlencode([(k,v) for k,v in parse_qsl(url.query,keep_blank_values=True) if not private_key(k)])
        fragment=urlencode([(k,v) for k,v in parse_qsl(url.fragment,keep_blank_values=True) if not private_key(k)]) if '=' in url.fragment else url.fragment
        return urlunsplit((url.scheme,url.netloc.rsplit('@',1)[-1],url.path,query,fragment))
    except (TypeError,ValueError):return None


def safe_snapshot(value):
    """Reapply Research redaction, then strip credential/debug fields and unsafe locators."""
    value=sanitize_research(json_safe(value))
    def clean(item):
        if isinstance(item,dict):
            return {key:'[redacted]' if private_key(key) else clean(val) for key,val in item.items()}
        if isinstance(item,list):return [clean(val) for val in item]
        if not isinstance(item,str):return item
        if re.match(r'^(?:[a-zA-Z]:[\\/]|file:|/|\\\\)',item):return '[withheld local locator]'
        return re.sub(r'https?://[^\s<>"\']+',lambda m:public_url(m.group()) or '[withheld URL]',item)
    return clean(value)


class EvidenceHandoffService(AttributionService):
    def _source(self,kind,identifier):
        if kind=='label':
            record=row_data(self._get(Label,identifier))
            if record['chain'] != 'any' and not is_supported_chain(record['chain']):
                raise AttributionError('Label chain is not supported for attribution handoff')
            if not isinstance(record['confidence'],(int,float)) or not 0<=record['confidence']<=1:
                raise AttributionError('Malformed source snapshot')
            snapshot={'schema_version':1,'source_subsystem':'Greedy Collector Label','record':record}
            values=dict(evidence_type='label_snapshot',title='GC Label snapshot',summary=record['label'],
                        source_name=record['source'],source_locator='label:'+identifier,origin='analyst_added',
                        source_url=public_url(sanitize_research(record['source'])))
            origin_ids={'origin_label_id':identifier,'origin_match_id':None}
        elif kind=='research':
            record=row_data(self._get(KycMatch,identifier));run=row_data(self._get(KycScreeningRun,record['run_id']))
            source=next((source for source in SOURCE_CATALOG if source.id==record['source'] and source.mode=='api'),None)
            if not source:raise AttributionError('Only persisted automated research matches are eligible')
            if not isinstance(run['checked_sources'],list) or not any(isinstance(item,dict) and item.get('id')==source.id for item in run['checked_sources']):
                raise AttributionError('Research source was not recorded as successfully checked')
            if not isinstance(record['source_data'],dict) or not isinstance(record['categories'],list) or not isinstance(run['query'],dict):
                raise AttributionError('Malformed source snapshot')
            if not isinstance(record['match_score'],(int,float)) or not 0<=record['match_score']<=1:
                raise AttributionError('Malformed source snapshot')
            snapshot={'schema_version':1,'source_subsystem':'Greedy Collector Research','record':record,
                      'run':{key:run[key] for key in ('id','query','created_at')}}
            values=dict(evidence_type='research_snapshot',title='GC Research match snapshot',summary=record['match_rationale'],
                        source_name=source.name,source_catalog_id=source.id,source_locator='research-match:'+identifier,
                        source_url=public_url(sanitize_research(record['source_url'])),origin='public_osint')
            origin_ids={'origin_label_id':None,'origin_match_id':identifier}
        else:raise AttributionError('Unsupported source handoff')
        try:
            # Shared evidence bounds/provenance rules; IDs and method are only assigned here.
            values=EvidenceContentInput.model_validate(safe_snapshot({**values,'metadata_json':snapshot})).model_dump()
        except ValidationError:
            raise AttributionError('Malformed source snapshot') from None
        values.update(collection_method=values['evidence_type'],**origin_ids)
        return values

    def preview(self,kind,identifier):
        values=self._source(kind,identifier)
        return {'source_kind':kind,'source_id':identifier,'source_fingerprint':fingerprint(values),
                'origin':values['origin'],'source_name':values['source_name'],'source_url':values['source_url'],
                'snapshot':values['metadata_json']}

    @atomic
    def capture_source(self,claim_id,kind,identifier,link_payload,*,expected_version,expected_source_fingerprint):
        claim=self._claim(claim_id)
        if type(expected_version) is not int or expected_version!=claim.version:
            raise Conflict('Attribution version changed; reload before writing')
        LinkInput.model_validate(link_payload)
        values=self._source(kind,identifier);digest=fingerprint(values)
        if digest!=expected_source_fingerprint:
            raise Conflict('Source record changed; preview it again before capture')
        if kind=='label':
            record=values['metadata_json']['record']
            if record['chain'] not in ('any',claim.chain):
                raise AttributionError('Label and claim chains differ; choose a compatible claim')
            normalize_subject(claim.chain,record['address'])
        # Exact sanitized source capture is stable across retries, excluding capture time/actor.
        # A withdrawn association must be explicitly restored; do not recreate identical material.
        existing=self.db.scalar(select(Link).join(Evidence,Link.evidence_id==Evidence.id).where(
            Link.claim_id==claim.id,Evidence.content_sha256==digest))
        if existing:raise Conflict('This source snapshot is already linked; inspect or restore its link',existing.id)
        evidence=Evidence(**values,captured_by=ACTOR,content_sha256=digest)
        self.db.add(evidence);self.db.flush()
        self._event(evidence,'created','Immutable local source snapshot explicitly captured')
        return self._link(claim,evidence.id,link_payload,expected_version)
