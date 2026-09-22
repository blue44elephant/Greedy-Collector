"""Analyst-supplied source observations. No source transport or file access."""
from datetime import datetime,timedelta,timezone
import ipaddress
import re
import unicodedata
from typing import Literal
from urllib.parse import urlsplit,parse_qsl,unquote

from pydantic import BaseModel,JsonValue,Field,field_validator,model_validator
from sqlalchemy import inspect,select
from ..models import Case,CaseEntity,DiscoveryResult,DiscoveryRun
from ..migration_state import supports_revision
from ..attribution.domain import fingerprint
from ..attribution.handoff import private_key
from .schemas import Input,SubjectInput,ObservationRead
from .domain import DiscoveryError,Conflict,SchemaUnavailable,clean,public_url
from .execution_service import ExecutionService
from .service import atomic,utcnow

TRANSFORM_ID='wallet.manual_source_observation'
SOURCE_ID='manual_source'
REVISION='20260922_01'
SOURCE_TYPES=('webpage','marketplace_listing','marketplace_vendor_page','forum_post','document','other')
SourceType=Literal['webpage','marketplace_listing','marketplace_vendor_page','forum_post','document','other']


def safe_url(value):
    """Local syntax only, including inert v3 onion names. Never resolve a host."""
    if not isinstance(value,str) or not value or len(value)>2048 or '\\' in value or any(c.isspace() or unicodedata.category(c).startswith('C') for c in value):
        raise DiscoveryError('A bounded HTTP(S) source reference is required')
    try:
        parsed=urlsplit(value)
        if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username is not None or parsed.password is not None:raise ValueError()
        host=parsed.hostname.encode('idna').decode('ascii').lower().rstrip('.')
        if host=='localhost' or host.endswith(('.localhost','.local')):raise ValueError()
        try:
            address=ipaddress.ip_address(host)
        except ValueError:
            if len(host)>253 or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?',part) for part in host.rstrip('.').split('.')):raise ValueError()
            # Browser URL parsers reinterpret numeric/short IPv4 forms and
            # single-label hosts. They are not public source hostnames here.
            if '.' not in host or host.split('.')[-1].isdigit():raise ValueError()
            if host.endswith('.onion') and not re.fullmatch(r'[a-z2-7]{56}',host.split('.')[-2]):raise ValueError()
        else:
            if not address.is_global:raise ValueError()
        if any(ord(c)<32 or ord(c)==127 for c in unquote(value)):raise ValueError()
        for key,_ in parse_qsl(parsed.query,keep_blank_values=True)+parse_qsl(parsed.fragment,keep_blank_values=True):
            if private_key(key) or re.search(r'(?i)(?:token|session|cookie|credential|signature|password|secret|authorization)',key) or key.lower() in ('auth','sid','jwt','ticket'):
                raise ValueError()
        return public_url(value)
    except (ValueError,UnicodeError):
        raise DiscoveryError('Unsafe or malformed source URL') from None


def safe_text(value):
    if value is None:return None
    if any((ord(c)<32 and c not in '\n\r\t') or ord(c)==127 for c in value):raise ValueError('Unsupported control character')
    if re.search(r'(?im)(?:^|\n)\s*(?:authorization|proxy-authorization|cookie|set-cookie|x-api-key|api[_-]?key)\s*[:=]|\bBearer\s+\S+',value):
        raise ValueError('Do not paste credentials or session headers')
    if re.search(r'(?i)(?:^|\s)(?:[a-z]:[\\/]|file:|\\\\|/(?:users|home|tmp|etc|var|mnt)/)',value):
        raise ValueError('Do not paste local filesystem paths')
    for match in re.finditer(r'https?://[^\s<>"\']+',value):safe_url(match.group())
    if clean(value)!=value:raise ValueError('Sensitive material must be removed before capture')
    return value


class AttachmentReference(Input):
    reference:str=Field(min_length=1,max_length=200)
    sha256:str=Field(pattern=r'^[0-9a-fA-F]{64}$')
    filename:str|None=Field(default=None,max_length=200)
    content_type:str|None=Field(default=None,pattern=r'^[a-zA-Z0-9.+-]+/[a-zA-Z0-9.+-]+$',max_length=100)
    byte_size:int|None=Field(default=None,strict=True,ge=0,le=1073741824)
    @model_validator(mode='after')
    def validate_reference(self):
        safe_text(self.reference);safe_text(self.filename)
        if not self.reference.strip() or self.filename and (self.filename in ('.','..') or re.search(r'[\\/:]',self.filename)):
            raise ValueError('Use an exhibit reference and filename, not a path')
        self.sha256=self.sha256.lower()
        return self


class ManualSourceInput(Input):
    subject:SubjectInput
    source_type:SourceType
    observed_at:datetime
    context:str=Field(min_length=1,max_length=4000)
    analyst_note:str=Field(min_length=1,max_length=2000)
    source_url:str|None=Field(default=None,max_length=2048)
    source_reference:str|None=Field(default=None,max_length=200)
    title:str|None=Field(default=None,max_length=255)
    service_name:str|None=Field(default=None,max_length=200)
    alias:str|None=Field(default=None,max_length=200)
    case_id:str|None=Field(default=None,min_length=1,max_length=36)
    attachments:list[AttachmentReference]=Field(default_factory=list,max_length=5)
    @field_validator('context','analyst_note','source_reference','title','service_name','alias')
    @classmethod
    def private_material(cls,value):return safe_text(value)
    @model_validator(mode='after')
    def validate_capture(self):
        if not self.context.strip() or not self.analyst_note.strip():raise ValueError('Context and analyst rationale are required')
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:raise ValueError('Observed time requires a timezone')
        self.observed_at=self.observed_at.astimezone(timezone.utc)
        if self.observed_at>datetime.now(timezone.utc)+timedelta(minutes=5):raise ValueError('Observed time is in the future')
        if not self.source_url and not (self.source_reference and self.source_reference.strip()):raise ValueError('A URL or stable source reference is required')
        if self.source_url:safe_url(self.source_url)
        clean(self.model_dump(mode='json')) # Existing 16 KiB total material bound.
        return self


class ManualSourceConfirm(Input):
    capture:ManualSourceInput
    expected_preview_fingerprint:str=Field(pattern=r'^[0-9a-f]{64}$')


class ManualSourcePreview(BaseModel):
    capture:dict[str,JsonValue]
    endpoint:dict[str,str]
    case_id:str|None
    preview_fingerprint:str
    notice:str


class ManualSourceCaptured(BaseModel):
    run_id:str
    result_id:str
    observation_id:str
    captured_at:datetime
    duplicate:bool
    case_id:str|None
    observation:ObservationRead


class ManualSourceService(ExecutionService):
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        checks={c['name']:' '.join(c['sqltext'].split()).lower() for c in inspect(self.db.connection()).get_check_constraints('discovery_results')}
        required=next(' '.join(str(c.sqltext).split()).lower() for c in DiscoveryResult.__table__.constraints if c.name=='ck_discovery_results_2')
        if checks.get('ck_discovery_results_2') not in (required,required.replace(", 'publicly_labeled_as'",'')) or (not self._metadata_only and not supports_revision(self.db.connection(),REVISION)):
            raise SchemaUnavailable('Manual source capture requires the ED-9A migration')

    def preview(self,payload):
        data=ManualSourceInput.model_validate(payload.model_dump() if isinstance(payload,ManualSourceInput) else payload)
        values=data.model_dump(mode='json',exclude={'case_id'})
        values['attachments']=sorted(values['attachments'],key=lambda item:fingerprint(item))
        canonical=safe_url(data.source_url) if data.source_url else None
        if canonical:
            endpoint={'kind':'url','namespace':urlsplit(canonical).scheme,'value':canonical}
        else:
            endpoint={'kind':'annotation','namespace':'manual-source','value':fingerprint({'reference':data.source_reference,'type':data.source_type})}
        values.update(source_url=canonical,entered_source_url=data.source_url,
                      capture_method='manual_analyst_capture',source_fetched=False,attachment_verification='analyst_supplied_reference')
        if data.case_id:self._get(Case,data.case_id)
        return {'capture':clean(values),'endpoint':endpoint,'case_id':data.case_id,
                'preview_fingerprint':fingerprint({'capture':values,'case_id':data.case_id}),
                'notice':'Manual analyst capture. GC has not fetched or verified the source. This records a wallet mention, not ownership.'}

    @atomic
    def capture(self,payload):
        request=ManualSourceConfirm.model_validate(payload.model_dump() if isinstance(payload,ManualSourceConfirm) else payload)
        preview=self.preview(request.capture)
        if request.expected_preview_fingerprint!=preview['preview_fingerprint']:raise Conflict('Capture preview changed')
        values=preview['capture'];material=fingerprint(values)
        key='manual-source:'+material
        prior=self.db.scalar(select(DiscoveryRun).where(DiscoveryRun.idempotency_key==key))
        duplicate=prior is not None
        if prior:
            if prior.request_snapshot.get('execution_policy',{}).get('material_fingerprint')!=material:raise Conflict('Capture identity conflict')
            row=self.read_run(prior.id)
            items=self.result_page(prior.id)['items']
            if row['status']!='completed' or len(items)!=1:raise Conflict('Existing capture is incomplete')
            ob=items[0]['observation']
        else:
            wallet=values['subject'];subject=self.get_or_create_subject('blockchain_address',wallet['chain'],wallet['address'])
            row=self.create_run(subject['id'],[{'transform_id':TRANSFORM_ID,'source_id':SOURCE_ID}],idempotency_key=key,
                execution_policy={'mode':'manual_capture','material_fingerprint':material,'budget':{'allow_free_local':True}})
            row=self.transition_run(row['id'],'running',expected_version=row['version'])
            self.transition_source(row['sources'][0]['id'],'running',expected_run_version=row['version'])
            row=self.get_run(row['id']);now=utcnow()
            record={'kind':'candidate_relationship','predicate':'mentions_wallet','from':preview['endpoint'],
                'to':{'kind':'blockchain_address','namespace':wallet['chain'],'value':wallet['address']},'fact_key':{},
                'observation':{'kind':'analyst_capture','source_record_key':fingerprint(preview['endpoint']),
                    'source_url':values['source_url'],'source_locator':'manual-source:'+fingerprint(preview['endpoint']),
                    'title':values['title'] or 'Manual source observation',
                    'summary':'The analyst recorded observing this wallet in this source/context. GC did not retrieve or independently verify the source.',
                    'excerpt':values['context'],'excerpt_complete':False,'verification':'not_checked',
                    'source_class':'analyst_supplied','observed_at':request.capture.observed_at,'retrieved_at':now,
                    'source_snapshot':values}}
            stored=self.record_batch(row['sources'][0]['id'],[record],expected_run_version=row['version'])
            ob=self.read_observation(stored['observation_ids'][0]);row=self.get_run(row['id'])
            self.transition_run(row['id'],'completed',expected_version=row['version']);row=self.read_run(row['id'])
        if preview['case_id']:
            # Case reference is explicit, separate from material identity/review.
            # Deleting unrelated Case records cannot cascade into observations.
            existing=self.db.scalar(select(CaseEntity).where(CaseEntity.case_id==preview['case_id'],CaseEntity.entity_type=='discovery_observation',CaseEntity.entity_ref==ob['id']))
            if existing is None:
                self.db.add(CaseEntity(case_id=preview['case_id'],entity_type='discovery_observation',entity_ref=ob['id'],
                    metadata_json={'source_type':values['source_type'],'title':ob['title'],'run_id':row['id'],'result_id':ob['result_id'],'chain':values['subject']['chain'],'address':values['subject']['address'],'meaning':'Manual analyst source observation; not an identity claim'}))
                self.db.flush()
        return {'run_id':row['id'],'result_id':ob['result_id'],'observation_id':ob['id'],'captured_at':ob['created_at'],
                'duplicate':duplicate,'case_id':preview['case_id'],'observation':ob}


def is_manual_material(result,observation,source):
    return ((source.transform_id,source.source_id,source.transform_version,source.source_version)==(TRANSFORM_ID,SOURCE_ID,1,1)
        and (result.predicate,observation.kind,observation.verification)==('mentions_wallet','analyst_capture','not_checked')
        and result.to_subject_id==result.query_subject_id
        and observation.source_snapshot.get('capture_method')=='manual_analyst_capture'
        and observation.source_snapshot.get('source_fetched') is False)
