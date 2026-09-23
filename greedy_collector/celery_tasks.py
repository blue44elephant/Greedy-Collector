"""Optional distributed monitoring entry point.

Install requirements-greedy-collector-scale.txt before importing this module.
"""

import asyncio

from celery import Celery

from .config import get_settings
from .monitoring import monitor_chain
from .chains import list_chains,Capability

settings = get_settings()
celery_app = Celery(
    "greedy_collector",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.beat_schedule = {
    'greedy-collector-'+d.chain_id: {'task':'greedy_collector.monitor_chain',
        'schedule':d.adapter().monitoring_interval(settings)*60,'args':(d.chain_id,)}
    for d in reversed(list_chains()) if Capability.MONITORING in d.capabilities
}
celery_app.conf.timezone = "UTC"


@celery_app.task(name="greedy_collector.monitor_chain")
def monitor_chain_task(chain: str) -> dict:
    return asyncio.run(monitor_chain(chain))
