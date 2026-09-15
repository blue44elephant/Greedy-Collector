"""Explicit bounded Discovery workflows; no CRUD, promotion or executor injection."""
from typing import Annotated
from urllib.parse import urlsplit
from fastapi import APIRouter,Depends,Query,Request,Header
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from . import schemas as s
from .domain import DiscoveryError,NotFound,Conflict,SchemaUnavailable
from .runtime import DiscoveryRuntime
from .promotion import PromotionService, PromotionUnavailable
from . import promotion_schemas as ps
from ..attribution import domain as ad

def error(status,code,message):
    return JSONResponse(status_code=status,content={'detail':{'code':code,'message':message}})

class DiscoveryRoute(APIRoute):
    def get_route_handler(self):
        handler=super().get_route_handler()
        async def safe(request):
            try:
                if request.method=='POST':
                    origin=request.headers.get('origin')
                    if origin:
                        source=urlsplit(origin);target=request.url
                        if source.scheme!=target.scheme or source.netloc!=target.netloc or source.path or source.query or source.fragment:
                            return error(403,'origin_rejected','Discovery mutations require the same origin.')
                    if request.headers.get('sec-fetch-site')=='cross-site':return error(403,'origin_rejected','Cross-site Discovery mutation rejected.')
                    if request.headers.get('content-type','').split(';')[0]!='application/json':return error(422,'invalid_request','A JSON request is required.')
                    body=bytearray()
                    async for chunk in request.stream():
                        body.extend(chunk)
                        if len(body)>32768:return error(422,'invalid_request','Discovery request exceeds its size limit.')
                    request._body=bytes(body)
                return await handler(request)
            except PromotionUnavailable:return error(503,'promotion_schema_unavailable','Discovery promotion storage is not initialized for this database.')
            except ad.SchemaUnavailable:return error(503,'attribution_schema_unavailable','Attribution storage is not initialized for this database.')
            except ad.NotFound:return error(404,'not_found','Attribution record not found.')
            except ad.Conflict as exc:
                detail={'code':'promotion_conflict','message':'Promotion conflict. Reload and review the selected material and claim; existing promotions remain retained.'}
                if exc.existing_id: detail['existing_id']=exc.existing_id
                return JSONResponse(status_code=409,content={'detail':detail})
            except ad.AttributionError:return error(422,'promotion_ineligible','Promotion requires reviewed eligible material, a compatible claim, and explicit valid link decisions.')
            except NotFound:return error(404,'not_found','Discovery record not found.')
            except Conflict:return error(409,'conflict','Discovery conflict. Reload the record or create a fresh plan; duplicate intent, active runs and stale versions cannot be resubmitted.')
            except SchemaUnavailable:return error(503,'schema_unavailable','Discovery storage or executor is unavailable. Explicit migration may be required.')
            except (RequestValidationError,ValidationError,DiscoveryError):return error(422,'invalid_request','Invalid Discovery request. Check the documented fields, subject, transform, budget and version.')
            except SQLAlchemyError:return error(503,'storage_unavailable','Discovery storage is unavailable.')
            except Exception:return error(500,'internal_error','Discovery request could not be completed.')
        return safe

router=APIRouter(prefix='/discovery',tags=['Discovery'],route_class=DiscoveryRoute,
    responses={code:{'model':s.DiscoveryErrorResponse} for code in (403,404,409,422,500,503)})

def get_runtime(request:Request):
    runtime=getattr(request.app.state,'discovery',None)
    if runtime is None:raise SchemaUnavailable('Discovery runtime not started')
    return runtime

Runtime=Annotated[DiscoveryRuntime,Depends(get_runtime)]
Limit=Annotated[int,Query(ge=1,le=100)]
Offset=Annotated[int,Query(ge=0)]

@router.get('/sources',response_model=list[s.SourceCapability])
def sources(runtime:Runtime):return runtime.capabilities()['sources']

@router.get('/transforms',response_model=list[s.TransformCapability])
def transforms(runtime:Runtime):return runtime.capabilities()['transforms']

@router.post('/plan',response_model=s.PlanRead)
def plan(payload:s.PlanRequest,runtime:Runtime):return runtime.plan(payload)[0]

@router.post('/runs',response_model=s.RunRead,status_code=202)
async def create_run(payload:s.RunCreate,runtime:Runtime,idempotency_key:Annotated[str|None,Header(min_length=1,max_length=128)]=None):
    return await runtime.create_and_execute_run(payload,idempotency_key)

@router.get('/runs',response_model=s.Page[s.RunSummary])
def runs(runtime:Runtime,limit:Limit=20,offset:Offset=0,subject_id:str|None=None,status:s.RunState|None=None,include_archived:bool=False):
    with runtime.service() as svc:return svc.list_runs(subject_id=subject_id,status=status.value if status else None,include_archived=include_archived,limit=limit,offset=offset)

@router.get('/runs/{run_id}',response_model=s.RunRead)
def run(run_id:str,runtime:Runtime):
    with runtime.service() as svc:return svc.read_run(run_id)

@router.post('/runs/{run_id}/cancel',response_model=s.RunRead)
async def cancel(run_id:str,payload:s.VersionInput,runtime:Runtime):return await runtime.cancel(run_id,payload.expected_version)

@router.post('/runs/{run_id}/archive',response_model=s.RunRead)
def archive(run_id:str,payload:s.VersionInput,runtime:Runtime):
    with runtime.service() as svc:
        svc.archive_run(run_id,expected_version=payload.expected_version)
        return svc.read_run(run_id)

@router.post('/runs/{run_id}/restore',response_model=s.RunRead)
def restore(run_id:str,payload:s.VersionInput,runtime:Runtime):
    with runtime.service() as svc:
        svc.archive_run(run_id,expected_version=payload.expected_version,restore=True)
        return svc.read_run(run_id)

@router.get('/runs/{run_id}/results',response_model=s.Page[s.RunResult])
def run_results(run_id:str,runtime:Runtime,limit:Limit=20,offset:Offset=0):
    with runtime.service() as svc:return svc.result_page(run_id,limit=limit,offset=offset)

@router.get('/results/{result_id}',response_model=s.ResultRead)
def result(result_id:str,runtime:Runtime):
    with runtime.service() as svc:return svc.get_result(result_id)

@router.get('/results/{result_id}/observations',response_model=s.Page[s.ObservationSummary])
def observations(result_id:str,runtime:Runtime,limit:Limit=20,offset:Offset=0):
    with runtime.service() as svc:return svc.observation_page(result_id,limit=limit,offset=offset)

@router.get('/observations/{observation_id}',response_model=s.ObservationRead)
def observation(observation_id:str,runtime:Runtime):
    with runtime.service() as svc:return svc.read_observation(observation_id)

@router.get('/results/{result_id}/reviews',response_model=s.Page[s.ReviewRead])
def reviews(result_id:str,runtime:Runtime,limit:Limit=20,offset:Offset=0):
    with runtime.service() as svc:return svc.list_reviews(result_id,limit=limit,offset=offset)

@router.post('/results/{result_id}/review',response_model=s.ReviewResult)
def review(result_id:str,payload:s.ReviewInput,runtime:Runtime):
    with runtime.service() as svc:return svc.review(result_id,payload.observation_id,payload.status.value,payload.reason,expected_version=payload.expected_version,expected_source_fingerprint=payload.expected_source_fingerprint)


@router.get('/observations/{observation_id}/promotion-preview',response_model=ps.PromotionPreview)
def promotion_preview(observation_id:str,runtime:Runtime):
    with runtime.sessions() as db:
        return PromotionService(db,metadata_only=runtime.metadata_only,registry=runtime.registry).preview(observation_id)

@router.post('/observations/{observation_id}/promote',response_model=ps.PromotionResult,status_code=201)
def promote(observation_id:str,payload:ps.PromotionInput,runtime:Runtime):
    with runtime.sessions() as db:
        return PromotionService(db,metadata_only=runtime.metadata_only,registry=runtime.registry).promote(observation_id,payload)

@router.get('/results/{result_id}/promotions',response_model=s.Page[ps.PromotionRead])
def promotions(result_id:str,runtime:Runtime,limit:Limit=20,offset:Offset=0):
    with runtime.sessions() as db:
        return PromotionService(db,metadata_only=runtime.metadata_only,registry=runtime.registry).history(result_id,limit=limit,offset=offset)
