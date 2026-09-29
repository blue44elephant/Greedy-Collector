"""Register capture routes on Discovery's same-origin, safe-error boundary."""
from typing import Literal
from pydantic import Field, field_validator
from ..domain import Input
from .service import CaptureService
from . import network

class Confirm(Input):
    confirmed:Literal[True]
class ReviewInput(Input):
    status:Literal['unreviewed','relevant','irrelevant']
    note:str=Field(min_length=1,max_length=2000)
    expected_version:int=Field(strict=True,ge=0)
    @field_validator('note')
    @classmethod
    def nonblank(cls,v):
        if not v.strip():raise ValueError('Review note required')
        return v
class ExcerptInput(Input):
    excerpt:str=Field(min_length=1,max_length=8000)
    expected_source_fingerprint:str=Field(pattern=r'^[a-f0-9]{64}$')
class PromoteInput(ExcerptInput):
    claim_id:str=Field(min_length=1,max_length=36)
    expected_claim_version:int=Field(strict=True,ge=1)
    link:dict
    confirmed:Literal[True]

def install(router,Runtime,Limit,Offset):
    @router.post('/observations/{observation_id}/public-captures',status_code=201)
    async def capture(observation_id:str,payload:Confirm,runtime:Runtime) -> dict:
        # Close the read transaction before network I/O; store only a terminal,
        # immutable outcome. The request cannot choose URLs or transport options.
        with runtime.sessions() as db:origin=CaptureService(db).origin(observation_id)
        retrieved=await network.retrieve(origin['requested_url'])
        with runtime.sessions() as db:return CaptureService(db).store(origin,retrieved)
    @router.get('/observations/{observation_id}/public-captures')
    def history(observation_id:str,runtime:Runtime,limit:Limit=10,offset:Offset=0) -> dict:
        with runtime.sessions() as db:return CaptureService(db).page(observation_id,limit,offset)
    @router.get('/public-captures/{capture_id}')
    def read(capture_id:str,runtime:Runtime) -> dict:
        with runtime.sessions() as db:return CaptureService(db).read(capture_id)
    @router.post('/public-captures/{capture_id}/review')
    def review(capture_id:str,payload:ReviewInput,runtime:Runtime) -> dict:
        with runtime.sessions() as db:return CaptureService(db).review(capture_id,payload)
    @router.get('/public-captures/{capture_id}/promotion-preview')
    def preview(capture_id:str,runtime:Runtime) -> dict:
        with runtime.sessions() as db:return CaptureService(db).preview(capture_id)
    @router.post('/public-captures/{capture_id}/promote',status_code=201)
    def promote(capture_id:str,payload:PromoteInput,runtime:Runtime) -> dict:
        with runtime.sessions() as db:return CaptureService(db).promote(capture_id,payload)
    @router.post('/public-captures/{capture_id}/cases/{case_id}/pin',status_code=201)
    def pin(capture_id:str,case_id:str,payload:ExcerptInput,runtime:Runtime) -> dict:
        with runtime.sessions() as db:return CaptureService(db).pin(capture_id,case_id,payload)
