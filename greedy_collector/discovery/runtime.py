"""Single-process, one-active-run Discovery orchestration with local/manual pivots."""
import asyncio
from contextlib import contextmanager
from datetime import datetime,timedelta,timezone
import os
from uuid import uuid4
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError
from . import schemas as s,enums as e
from .domain import canonical_subject,query_fingerprint,Conflict,SchemaUnavailable,DiscoveryError
from ..attribution.domain import fingerprint,canonical_json
from .executors import production_executors,ExecutionContext,ExecutionSignal
from .execution_service import ExecutionService

class DiscoveryRuntime:
    def __init__(self,sessions,executors=None,*,metadata_only=False):
        if executors is None:executors=production_executors(sessions)
        self.sessions=sessions;self.executors=executors;self.registry=executors.descriptors
        self.metadata_only=metadata_only;self._gate=asyncio.Lock();self._tasks={};self._cancel={};self._stopping=False

    @contextmanager
    def service(self):
        with self.sessions() as db:
            yield ExecutionService(db,registry=self.registry,metadata_only=self.metadata_only)

    def _configured(self,source):
        checks=[b.available for b in self.executors._bindings.values() if b.source_id==source.id and b.available is not None]
        if checks:return all(check() for check in checks)
        return bool(os.getenv(source.credential_env,'')) if source.credential_env else True

    def eligibility(self,transform,source,budget):
        manual=self.executors.manual(transform.id,source.id) or self.executors.capture(transform.id,source.id)
        if manual:
            if (manual.transform_version,manual.source_version)!=(transform.version,source.version):return 'not_implemented'
            return 'eligible' if budget.allow_free_local else 'budget_exhausted'
        binding=self.executors.get(transform.id,source.id)
        if not binding:return 'not_implemented'
        if (binding.transform_version,binding.source_version)!=(transform.version,source.version):return 'not_implemented'
        if not binding.quota.enabled:return 'disabled'
        if not self._configured(source):return 'configuration_unavailable'
        if not source.storage_allowed:return 'retention_not_permitted'
        allowed={'FREE_LOCAL':budget.allow_free_local,'FREE_REMOTE':budget.allow_free_remote,
                 'LIMITED_FREE':budget.allow_limited_free,'PAID':budget.paid_units.get(source.id,0)>0}
        if not allowed[source.cost_class]:return 'budget_exhausted'
        if source.cost_class=='PAID' and budget.paid_units.get(source.id,0)<transform.max_requests*binding.quota.units_per_request:return 'budget_exhausted'
        return 'eligible'

    def capabilities(self):
        sources=[];transforms=[]
        for source in self.registry.sources.values():
            executable=any(self.eligibility(t,source,s.Budget())=='eligible' for t in self.registry.transforms.values() if source.id in t.source_ids)
            sources.append(s.SourceCapability(**source.model_dump(exclude={'credential_env'}),configured=self._configured(source),credential_required=bool(source.credential_env),executable=executable).model_dump(mode='json'))
        for t in self.registry.transforms.values():
            states=[self.eligibility(t,self.registry.sources[x],s.Budget()) for x in t.source_ids]
            values=t.model_dump();values.update(implemented=any(self.executors.get(t.id,x) is not None or self.executors.manual(t.id,x) is not None or self.executors.capture(t.id,x) is not None for x in t.source_ids),executable='eligible' in states,
                configured=all(self._configured(self.registry.sources[x]) for x in t.source_ids),unavailable_reason=None if 'eligible' in states else states[0])
            transforms.append(s.TransformCapability.model_validate(values).model_dump(mode='json'))
        return {'sources':sources,'transforms':transforms}

    def _intent(self,request):return fingerprint(s.PlanRequest.model_validate(request.model_dump(exclude={'expected_plan_fingerprint'})).model_dump(mode='json'))

    def plan(self,request):
        request=s.PlanRequest.model_validate(request.model_dump(exclude={'expected_plan_fingerprint'}) if isinstance(request,s.RunCreate) else request)
        subject=canonical_subject('blockchain_address',request.subject.chain,request.subject.address)
        selected=[];seen=set()
        # Configuration identity is code/operator-owned, never selection-owned.
        config={source_id:{t.id:(binding.quota.model_dump() if (binding:=self.executors.get(t.id,source_id)) else {'manual_version':manual.transform_version} if (manual:=self.executors.manual(t.id,source_id)) else {'unimplemented':True})
            for t in self.registry.transforms.values() if source_id in t.source_ids} for source_id in self.registry.sources}
        for item in request.selections:
            transform=self.registry.transforms.get(item.transform_id)
            if not transform:raise DiscoveryError('Unknown transform')
            if transform.capture_only:raise DiscoveryError('Use manual source preview and explicit capture')
            source_id=item.source_id or (transform.source_ids[0] if len(transform.source_ids)==1 else None)
            transform,source=self.registry.pair(item.transform_id,source_id)
            if request.subject.chain not in transform.chains:raise DiscoveryError('Unsupported transform subject')
            if (transform.id,source.id) in seen:raise DiscoveryError('Duplicate transform selection')
            seen.add((transform.id,source.id))
            maximum=item.parameters.max_results or transform.max_results
            if maximum>transform.max_results:raise DiscoveryError('Result limit exceeds descriptor')
            binding=self.executors.get(transform.id,source.id)
            selected.append((transform,source,maximum,binding))
        if set(request.budget.paid_units)-{source.id for _,source,_,_ in selected}:raise DiscoveryError('Budget source was not selected')
        generation=fingerprint(config)
        pairs=[s.PlannedSource(transform_id=t.id,source_id=source.id,transform_version=t.version,source_version=source.version,
            parameters={'max_results':maximum},query_fingerprint=query_fingerprint(subject,t,source,{'max_results':maximum},config_generation=generation),
            eligibility=self.eligibility(t,source,request.budget),cost_class=t.cost_class,cost_unit=source.cost_unit,max_requests=t.max_requests,
            max_units=t.max_requests*binding.quota.units_per_request if binding else 0,cache_seconds=t.cache_seconds) for t,source,maximum,binding in selected]
        now=datetime.now(timezone.utc);window=int(now.timestamp())//60
        digest=fingerprint({'intent':self._intent(request),'pairs':[p.model_dump(mode='json') for p in pairs],
            'descriptors':[(t.model_dump(mode='json'),source.model_dump(mode='json')) for t,source,_,_ in selected], 'config':config,'window':window})
        return s.PlanRead(subject=subject,selections=pairs,budget=request.budget,refresh=request.refresh,fingerprint=digest,
            expires_at=datetime.fromtimestamp((window+1)*60,timezone.utc)),generation

    async def create_and_execute_run(self,request,key=None):
        request=s.RunCreate.model_validate(request);key=key or str(uuid4())
        async with self._gate:
            if self._stopping:raise SchemaUnavailable('Discovery executor is stopping')
            intent=self._intent(request)
            with self.service() as svc:
                existing=svc.existing_intent(key,intent)
                if existing:return svc.read_run(existing['id'])
            if any(not task.done() for task in self._tasks.values()):raise Conflict('A Discovery executor is still active')
            plan,generation=self.plan(request)
            if request.expected_plan_fingerprint!=plan.fingerprint:raise Conflict('Plan changed or expired; plan again')
            policy={'intent':intent,'budget':request.budget.model_dump(mode='json'),'plan_fingerprint':plan.fingerprint,
                'selections':[p.model_dump(mode='json') for p in plan.selections]}
            selections=[{'transform_id':p.transform_id,'source_id':p.source_id,'parameters':p.parameters.model_dump(exclude_none=True)} for p in plan.selections]
            with self.service() as svc:
                row=svc.define(request.subject.model_dump(),selections,key,request.refresh,policy,generation)
                response=svc.read_run(row['id'])
            event=asyncio.Event();self._cancel[row['id']]=event
            task=asyncio.create_task(self.execute_run(row['id'],event),name='discovery-run')
            self._tasks[row['id']]=task
            task.add_done_callback(lambda done,identifier=row['id']:self._finished(identifier,done))
            return response

    def _finished(self,identifier,task):
        self._tasks.pop(identifier,None);self._cancel.pop(identifier,None)
        # Exceptions are handled into persisted interruption; never log payloads.
        if not task.cancelled():task.exception()

    async def execute_run(self,run_id,event):
        try:
            with self.service() as svc:
                row=svc.get_run(run_id)
                if row['status']!='queued':return
                row=svc.transition_run(run_id,'running',expected_version=row['version'])
                subject=svc.get_subject(row['subject_id'])
            budget=s.Budget.model_validate(row['request_snapshot']['execution_policy']['budget'])
            for source in row['sources']:
                if event.is_set():break
                await self._source(run_id,source,subject,budget,event)
            with self.service() as svc:svc.finalize(run_id)
        except asyncio.CancelledError:
            self._interrupt(run_id)
        except Exception:
            self._interrupt(run_id)

    def _interrupt(self,run_id):
        try:
            with self.service() as svc:
                row=svc.get_run(run_id)
                if row['status'] in ('queued','running'):svc.transition_run(run_id,'interrupted',expected_version=row['version'])
        except Exception:
            # An unavailable database is recovered on the next normal startup.
            pass

    async def _source(self,run_id,source,subject,budget,event):
        sid=source['id'];t,descriptor=self.registry.pair(source['transform_id'],source['source_id'])
        eligible=self.eligibility(t,descriptor,budget)
        if eligible!='eligible':
            category={'budget_exhausted':'budget_exhausted','retention_not_permitted':'retention_not_permitted'}.get(eligible,'configuration_unavailable')
            with self.service() as svc:svc.fail_source(sid,category,eligibility=eligible)
            return
        binding=self.executors.get(t.id,descriptor.id)
        try:
            manual=self.executors.manual(t.id,descriptor.id)
            if manual:
                actions=[s.ManualAction.model_validate(a).model_dump(mode='json') for a in manual.actions(subject)]
                if len(actions)!=1 or any(a['source_id']!=descriptor.id for a in actions):raise ExecutionSignal('invalid_provider_response')
                if event.is_set():raise asyncio.CancelledError()
                with self.service() as svc:
                    row=svc.get_run(run_id)
                    svc.transition_source(sid,'manual_ready',expected_run_version=row['version'],quota_snapshot={'manual_actions':actions})
                return
            with self.service() as svc:
                row=svc.get_run(run_id)
                if svc.cache_candidate(sid):
                    svc.reuse_cache(sid,expected_run_version=row['version']);return
                svc.reserve_source(sid,binding.quota,budget.paid_units.get(descriptor.id,0))
                deadline=datetime.fromisoformat(row['deadline_at'])
            def charge(request_class):
                with self.service() as svc:svc.charge_attempt(sid,request_class)
            context=ExecutionContext(subject,source['parameters'],descriptor.id,deadline,event,charge)
            remaining=min(t.deadline_seconds,(deadline-datetime.now(timezone.utc)).total_seconds())
            if remaining<=0:raise ExecutionSignal('timeout')
            # Async implementations must propagate cancellation and bound their I/O.
            async with asyncio.timeout(remaining):output=await binding.executor.execute(context)
            context.checkpoint()
            if not isinstance(output,(dict,s.Batch)):raise ExecutionSignal('invalid_provider_response')
            raw=output.model_dump(mode='json',by_alias=True) if isinstance(output,s.Batch) else output
            # Reject oversized batches in full; never silently drop output records.
            if len(canonical_json(raw).encode('utf-8'))>t.max_bytes:raise ExecutionSignal('invalid_provider_response')
            batch=s.Batch.model_validate(raw)
            if len(batch.records)>source['parameters']['max_results']:raise ExecutionSignal('invalid_provider_response')
            with self.service() as svc:
                row=svc.get_run(run_id)
                svc.record_execution_batch(sid,batch,row['version'])
        except asyncio.CancelledError:raise
        except TimeoutError:
            with self.service() as svc:svc.fail_source(sid,'timeout')
        except ExecutionSignal as exc:
            with self.service() as svc:svc.fail_source(sid,exc.category,quota=exc.quota)
        except (SQLAlchemyError,Conflict):
            with self.service() as svc:svc.fail_source(sid,'storage_unavailable')
        except (DiscoveryError,ValidationError,ValueError,TypeError):
            with self.service() as svc:svc.fail_source(sid,'invalid_provider_response')
        except Exception:
            with self.service() as svc:svc.fail_source(sid,'transport_failed')

    async def cancel(self,run_id,version):
        async with self._gate:
            with self.service() as svc:
                svc.transition_run(run_id,'cancelled',expected_version=version)
                response=svc.read_run(run_id)
            if run_id in self._cancel:self._cancel[run_id].set()
            if run_id in self._tasks:self._tasks[run_id].cancel()
            return response

    async def start(self):
        self._stopping=False
        try:
            with self.service() as svc:svc.interrupt_orphans()
        except SchemaUnavailable:pass

    async def stop(self):
        self._stopping=True
        for event in self._cancel.values():event.set()
        owned=dict(self._tasks)
        tasks=list(owned.values())
        for task in tasks:task.cancel()
        if tasks:
            await asyncio.wait(tasks,timeout=2)
            # Cancellation before the coroutine's first instruction never enters
            # execute_run's finally/error path. Persist every owned run here too.
            for identifier in owned:self._interrupt(identifier)
            # No thread kill or replay. Non-cooperative code is unsupported and
            # cannot write terminal-run material through the service boundary.

async def start_discovery(app):
    from ..database import SessionLocal
    runtime=DiscoveryRuntime(SessionLocal)
    app.state.discovery=runtime
    await runtime.start()

async def stop_discovery(app):
    runtime=getattr(app.state,'discovery',None)
    if runtime:await runtime.stop()
