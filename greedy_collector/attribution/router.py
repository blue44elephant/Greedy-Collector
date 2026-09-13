"""Manual attribution HTTP workflows. No provider, startup write, or UI hooks."""
from typing import Annotated
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ..database import get_db
from . import schemas as s
from .domain import AttributionError, Conflict, NotFound, SchemaUnavailable
from .service import AttributionService
from .handoff import EvidenceHandoffService


def error(status, code, message, existing_id=None):
    return JSONResponse(status_code=status, content=s.ErrorResponse(
        detail=s.ErrorDetail(code=code, message=message, existing_id=existing_id)
    ).model_dump(mode='json', exclude_none=True))


class AttributionRoute(APIRoute):
    """Keep validation inputs, SQL and unexpected exceptions out of HTTP errors.

    Scoped to attribution; existing APIs retain their response contracts.
    """
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def safe_handler(request):
            try:
                return await handler(request)
            except RequestValidationError:
                return error(422, 'invalid_request', 'Invalid attribution request. Check fields, formats and provenance requirements in the API schema.')
            except NotFound:
                return error(404, 'not_found', 'Attribution record not found.')
            except Conflict as exc:
                return error(409, 'conflict', 'Attribution conflict. Reload the current record and its version before retrying; duplicates and incompatible archive/link states are not allowed.', exc.existing_id)
            except SchemaUnavailable:
                return error(503, 'schema_unavailable', 'Attribution schema is unavailable. An explicit database migration is required before use.')
            except AttributionError as exc:
                # AT-1 domain messages are fixed explanations, never supplied values.
                return error(422, 'invalid_request', str(exc))
            except SQLAlchemyError:
                return error(503, 'storage_unavailable', 'Attribution storage is unavailable. Try again later.')
            except Exception:
                return error(500, 'internal_error', 'Attribution request failed unexpectedly.')

        return safe_handler


router = APIRouter(prefix='/attribution', tags=['Attribution'], route_class=AttributionRoute,
                   responses={code: {'model': s.ErrorResponse} for code in (404, 409, 422, 500, 503)})


def get_attribution_service(db: Session = Depends(get_db)):
    # A request-scoped dedicated session; never enable metadata_only in runtime.
    return AttributionService(db)


Service = Annotated[AttributionService, Depends(get_attribution_service)]
Limit = Annotated[int, Query(ge=1, le=200)]
Offset = Annotated[int, Query(ge=0)]


def get_handoff_service(db: Session = Depends(get_db)):
    return EvidenceHandoffService(db)


Handoff = Annotated[EvidenceHandoffService, Depends(get_handoff_service)]


@router.get('/evidence/sources/{source_kind}/{source_id}', response_model=s.SourcePreview)
def preview_source(source_kind: Literal['label','research'], source_id: str, svc: Handoff):
    return svc.preview(source_kind,source_id)


@router.post('/claims/{claim_id}/evidence/from-label/{label_id}', response_model=s.LinkResult, status_code=201)
def handoff_label(claim_id: str, label_id: str, payload: s.SourceHandoff, svc: Handoff):
    return svc.capture_source(claim_id,'label',label_id,payload.link.model_dump(),
        expected_version=payload.expected_version,expected_source_fingerprint=payload.expected_source_fingerprint)


@router.post('/claims/{claim_id}/evidence/from-research/{match_id}', response_model=s.LinkResult, status_code=201)
def handoff_research(claim_id: str, match_id: str, payload: s.SourceHandoff, svc: Handoff):
    return svc.capture_source(claim_id,'research',match_id,payload.link.model_dump(),
        expected_version=payload.expected_version,expected_source_fingerprint=payload.expected_source_fingerprint)


def page(result, limit, offset):
    return {**result, 'limit': limit, 'offset': offset}


@router.post('/entities', response_model=s.EntityRead, status_code=201)
def create_entity(payload: s.EntityCreate, svc: Service):
    return svc.create_entity(payload.model_dump())


@router.get('/entities', response_model=s.Page[s.EntityRead])
def list_entities(svc: Service, limit: Limit = 50, offset: Offset = 0,
                  search: Annotated[str | None, Query(max_length=255)] = None,
                  entity_type: s.EntityType | None = None, include_archived: bool = False):
    return page(svc.list_entities(search=search, entity_type=entity_type, include_archived=include_archived,
                                  limit=limit, offset=offset), limit, offset)


@router.get('/entities/{entity_id}', response_model=s.EntityRead)
def get_entity(entity_id: str, svc: Service):
    return svc.get_entity(entity_id)


@router.patch('/entities/{entity_id}', response_model=s.EntityRead)
def update_entity(entity_id: str, payload: s.EntityUpdate, svc: Service):
    return svc.update_entity(entity_id, payload.descriptor.model_dump(),
                             expected_version=payload.expected_version, reason=payload.reason)


@router.post('/entities/{entity_id}/archive', response_model=s.EntityRead)
def archive_entity(entity_id: str, payload: s.VersionAction, svc: Service):
    return svc.archive_entity(entity_id, **payload.model_dump())


@router.post('/entities/{entity_id}/restore', response_model=s.EntityRead)
def restore_entity(entity_id: str, payload: s.VersionAction, svc: Service):
    return svc.archive_entity(entity_id, restore=True, **payload.model_dump())


@router.post('/claims', response_model=s.ClaimDetail, status_code=201)
def create_claim(payload: s.ClaimCreate, svc: Service):
    claim = svc.create_claim(payload.model_dump())
    return svc.claim_detail(claim['id'])


@router.get('/claims', response_model=s.Page[s.ClaimRead])
def list_claims(svc: Service, limit: Limit = 50, offset: Offset = 0, chain: s.Chain | None = None,
                subject_ref: Annotated[str | None, Query(max_length=128)] = None,
                entity_id: str | None = None, relationship: s.Relationship | None = None,
                assessment: s.Assessment | None = None, needs_review: bool | None = None,
                include_archived: bool = False):
    return page(svc.list_claims(chain=chain, subject_ref=subject_ref, entity_id=entity_id,
                                relationship=relationship, assessment=assessment, needs_review=needs_review,
                                include_archived=include_archived, limit=limit, offset=offset), limit, offset)


@router.get('/claims/{claim_id}', response_model=s.ClaimDetail)
def get_claim(claim_id: str, svc: Service):
    return svc.claim_detail(claim_id)


@router.patch('/claims/{claim_id}/scope', response_model=s.ClaimRead)
def update_scope(claim_id: str, payload: s.ScopeUpdate, svc: Service):
    return svc.update_claim_scope(claim_id, payload.scope.model_dump(),
                                  expected_version=payload.expected_version, reason=payload.reason)


@router.post('/claims/{claim_id}/assessment', response_model=s.ClaimRead)
def change_assessment(claim_id: str, payload: s.AssessmentUpdate, svc: Service):
    return svc.change_assessment(claim_id, **payload.model_dump())


@router.post('/claims/{claim_id}/archive', response_model=s.ClaimRead)
def archive_claim(claim_id: str, payload: s.VersionAction, svc: Service):
    return svc.archive_claim(claim_id, **payload.model_dump())


@router.post('/claims/{claim_id}/restore', response_model=s.ClaimRead)
def restore_claim(claim_id: str, payload: s.VersionAction, svc: Service):
    return svc.archive_claim(claim_id, restore=True, **payload.model_dump())


@router.post('/evidence', response_model=s.EvidenceRead, status_code=201)
def create_evidence(payload: s.EvidenceCreate, svc: Service):
    return svc.create_evidence(payload.model_dump())


@router.get('/evidence', response_model=s.Page[s.EvidenceRead])
def list_evidence(svc: Service, limit: Limit = 50, offset: Offset = 0,
                  source_catalog_id: Annotated[str | None, Query(max_length=128)] = None,
                  origin: s.Origin | None = None):
    return page(svc.list_evidence(source_catalog_id=source_catalog_id, origin=origin,
                                  limit=limit, offset=offset), limit, offset)


@router.get('/evidence/{evidence_id}', response_model=s.EvidenceRead)
def get_evidence(evidence_id: str, svc: Service):
    return svc.get_evidence(evidence_id)


@router.get('/claims/{claim_id}/evidence', response_model=s.Page[s.LinkDetail])
def list_links(claim_id: str, svc: Service, limit: Limit = 50, offset: Offset = 0,
               include_withdrawn: bool = False, stance: s.Stance | None = None):
    return page(svc.claim_evidence_details(claim_id, include_withdrawn=include_withdrawn,
                                          stance=stance, limit=limit, offset=offset), limit, offset)


@router.post('/claims/{claim_id}/evidence', response_model=s.LinkResult, status_code=201)
def link_evidence(claim_id: str, payload: s.LinkCreate, svc: Service):
    return svc.link_evidence(claim_id, payload.evidence_id, payload.link.model_dump(), expected_version=payload.expected_version)


@router.post('/claims/{claim_id}/evidence/capture', response_model=s.LinkResult, status_code=201)
def capture_and_link(claim_id: str, payload: s.CaptureAndLink, svc: Service):
    return svc.create_and_link_evidence(claim_id, payload.evidence.model_dump(), payload.link.model_dump(),
                                        expected_version=payload.expected_version)


@router.patch('/claims/{claim_id}/evidence/{link_id}', response_model=s.LinkResult)
def update_link(claim_id: str, link_id: str, payload: s.LinkUpdate, svc: Service):
    return svc.update_evidence_link(claim_id, link_id, payload.link.model_dump(),
                                    expected_version=payload.expected_version, reason=payload.reason)


@router.post('/claims/{claim_id}/evidence/{link_id}/withdraw', response_model=s.LinkResult)
def withdraw_link(claim_id: str, link_id: str, payload: s.VersionAction, svc: Service):
    return svc.withdraw_evidence(claim_id, link_id, **payload.model_dump())


@router.post('/claims/{claim_id}/evidence/{link_id}/restore', response_model=s.LinkResult)
def restore_link(claim_id: str, link_id: str, payload: s.VersionAction, svc: Service):
    return svc.withdraw_evidence(claim_id, link_id, restore=True, **payload.model_dump())


@router.post('/claims/{claim_id}/evidence/{link_id}/replace', response_model=s.ReplacementResult)
def replace_evidence(claim_id: str, link_id: str, payload: s.EvidenceReplacement, svc: Service):
    return svc.replace_evidence(claim_id, link_id, payload.evidence.model_dump(), payload.link.model_dump(),
                                expected_version=payload.expected_version, reason=payload.reason)


@router.get('/claims/{claim_id}/events', response_model=s.Page[s.EventRead])
def claim_events(claim_id: str, svc: Service, limit: Limit = 50, offset: Offset = 0):
    return page(svc.event_page(claim_id=claim_id, limit=limit, offset=offset), limit, offset)


@router.get('/entities/{entity_id}/events', response_model=s.Page[s.EventRead])
def entity_events(entity_id: str, svc: Service, limit: Limit = 50, offset: Offset = 0):
    return page(svc.event_page(entity_id=entity_id, limit=limit, offset=offset), limit, offset)


@router.get('/evidence/{evidence_id}/events', response_model=s.Page[s.EventRead])
def evidence_events(evidence_id: str, svc: Service, limit: Limit = 50, offset: Offset = 0):
    return page(svc.event_page(evidence_id=evidence_id, limit=limit, offset=offset), limit, offset)
