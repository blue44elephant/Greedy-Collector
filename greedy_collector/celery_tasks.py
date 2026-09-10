"""Optional distributed monitoring entry point.

Install requirements-greedy-collector-scale.txt before importing this module.
"""

import asyncio

from celery import Celery

from .config import get_settings
from .monitoring import monitor_chain

settings = get_settings()
celery_app = Celery(
    "greedy_collector",
    broker=settings.redis_url,
    backend=settings.redis_url,
)
celery_app.conf.beat_schedule = {
    "greedy-collector-ethereum": {
        "task": "greedy_collector.monitor_chain",
        "schedule": settings.ethereum_monitor_minutes * 60,
        "args": ("ethereum",),
    },
    "greedy-collector-bitcoin": {
        "task": "greedy_collector.monitor_chain",
        "schedule": settings.bitcoin_monitor_minutes * 60,
        "args": ("bitcoin",),
    },
}
celery_app.conf.timezone = "UTC"


@celery_app.task(name="greedy_collector.monitor_chain")
def monitor_chain_task(chain: str) -> dict:
    return asyncio.run(monitor_chain(chain))
