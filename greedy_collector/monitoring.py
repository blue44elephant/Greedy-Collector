import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import logging
from threading import Lock

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from .config import get_settings
from .chains import get_chain_adapter,list_chains,Capability
from .database import SessionLocal
from .models import MonitoringRun, WalletAlert, WatchlistWallet
from .schemas import LookupRequest
from .services import GreedyCollectorService
from .collection import transfer_eligible

logger = logging.getLogger("GreedyCollector.Monitoring")
settings = get_settings()
scheduler = AsyncIOScheduler(timezone="UTC")
_chain_locks = {d.chain_id:Lock() for d in list_chains() if Capability.MONITORING in d.capabilities}
_locks_guard = Lock()


async def monitor_chain(chain: str, wallet_id: str | None = None) -> dict:
    """Scheduled and manual checks share one path, serialized per local chain."""
    get_chain_adapter(chain,Capability.MONITORING)
    with _locks_guard:
        lock = _chain_locks.setdefault(chain,Lock())
    if not lock.acquire(blocking=False):
        return {"chain": chain, "processed": 0, "busy": True, "run_ids": []}
    try:
        return await _monitor_chain(chain, wallet_id)
    finally:
        lock.release()


async def _monitor_chain(chain: str, wallet_id: str | None = None) -> dict:
    adapter = get_chain_adapter(chain,Capability.MONITORING)
    service = GreedyCollectorService()
    db = SessionLocal()
    processed = 0
    run_ids = []
    try:
        query = select(WatchlistWallet).where(
            WatchlistWallet.chain == chain, WatchlistWallet.enabled.is_(True)
        )
        if wallet_id is not None:
            query = query.where(WatchlistWallet.id == wallet_id)
        wallets = db.scalars(query).all()
        for wallet in wallets:
            run = MonitoringRun(wallet_id=wallet.id)
            db.add(run)
            db.flush()
            run_ids.append(run.id)
            previous_tx = wallet.last_seen_tx
            try:
                if previous_tx and hasattr(adapter, "monitoring_delta"):
                    delta = await adapter.monitoring_delta(wallet.address, previous_tx)
                    profile = await adapter.lookup_address(wallet.address)
                    result = await service.lookup_address(
                        db, LookupRequest(chain=chain, address=wallet.address, refresh=True),
                        profile_override=profile, transactions_override=delta["transactions"],
                    )
                    result["_monitor_boundary_found"] = delta["boundary_found"]
                else:
                    result = await service.lookup_address(
                        db, LookupRequest(chain=chain, address=wallet.address, refresh=True)
                    )
                transactions = result["transactions"]
                
                # Incomplete provider streams cannot safely advance an event boundary.
                if result.get("collection", {}).get("partial"):
                    run.status = "continuity_loss"
                    run.error = "Partial provider history; monitoring boundary retained"
                    run.completed_at = datetime.now(timezone.utc)
                    db.commit()
                    processed += 1
                    continue

                # FIRST-RUN DETECTION AND BASELINE ESTABLISHMENT
                # On first observation (last_seen_tx is None), establish stable baseline silently
                if previous_tx is None:
                    # Determine stable baseline for first-run
                    baseline_tx = None
                    
                    baseline_tx = adapter.monitoring_baseline(transactions)

                    # Establish baseline without alerting
                    wallet.last_checked = datetime.now(timezone.utc)
                    if baseline_tx:
                        tx_hash = adapter.transfer_identity(baseline_tx)
                        block_number = baseline_tx.get("block_number") if isinstance(baseline_tx, dict) else baseline_tx.block_number
                        cursor = getattr(adapter, "monitoring_cursor", adapter.transfer_identity)
                        wallet.last_seen_tx = cursor(baseline_tx)
                        wallet.last_seen_block = block_number
                    # If no baseline_tx (e.g., Bitcoin mempool-only), leave last_seen_tx as None
                    
                    run.new_transactions = 0
                    run.status = "completed"
                    run.completed_at = datetime.now(timezone.utc)
                    processed += 1
                    db.commit()
                    continue  # Skip to next wallet, no alert generation
                
                # CONTINUITY LOSS DETECTION
                # Check if previous_tx exists but is absent from current results
                reported_boundary_found = result.pop("_monitor_boundary_found", None)
                boundary_found = reported_boundary_found if reported_boundary_found is not None else True
                if previous_tx is not None:
                    # Previous boundary exists - verify it's in current results
                    if reported_boundary_found is None:
                        boundary_found = any(
                            (adapter.transfer_identity(tx) == previous_tx or tx.get("tx_hash") == previous_tx)
                            for tx in transactions
                        )
                    
                    if not boundary_found:
                        # Continuity loss: stored boundary not in current window
                        # This indicates bounded history or provider change
                        logger.error(
                            "Continuity loss detected for wallet %s (chain %s): "
                            "previous_tx %s not found in %d-transaction window. "
                            "Monitoring cannot safely process this window.",
                            wallet.address, chain, previous_tx, len(transactions)
                        )
                        run.status = "continuity_loss"
                        run.error = (
                            f"Boundary tx {previous_tx[:16]}... not found in "
                            f"{len(transactions)} transactions"
                        )
                        run.completed_at = datetime.now(timezone.utc)
                        db.commit()
                        processed += 1
                        continue  # Skip to next wallet, don't update state
                
                # Normal operation: boundary found or this is first-run
                new_rows = []
                for tx in transactions:
                    if previous_tx and (adapter.transfer_identity(tx) == previous_tx or tx.get("tx_hash") == previous_tx):
                        break
                    new_rows.append(tx)

                triggers = []
                for tx in new_rows:
                    if not transfer_eligible(tx): continue
                    if tx.get("direction") not in ("incoming", "outgoing") or not tx.get("from_address") or not tx.get("to_address"):
                        continue
                    triggers.append(
                        {
                            "name": "New outgoing transaction"
                            if tx["direction"] == "outgoing"
                            else "New incoming transaction",
                            "tx": tx,
                            "severity": "Medium",
                            "explanation": (
                                f"Public-chain monitoring observed a {tx['direction']} "
                                "transaction since the previous check."
                            ),
                        }
                    )
                for finding in result["risk"]["findings"]:
                    trigger_name = {
                        "large_transfer": "Large transfer",
                        "rapid_pass_through": "Rapid pass-through",
                        "many_to_one": "Many-to-one consolidation",
                        "one_to_many": "One-to-many fan-out",
                        "dormant_reactivated": "Dormant wallet becomes active",
                        "high_velocity": "High velocity",
                        "direct_mixer": "Mixer exposure",
                        "direct_sanctioned": "Sanctioned exposure",
                        "direct_scam": "Scam exposure",
                        "cross_chain_bridge": "Cross-chain bridge activity",
                        "exchange_pattern": "Exchange deposit/withdrawal",
                        "fresh_wallet_large_funds": "Fresh wallet receives large funds",
                        "peel_chain": "Peel-chain pattern",
                    }.get(finding["rule_id"])
                    if trigger_name:
                        triggers.append(
                            {
                                "name": trigger_name,
                                "tx": new_rows[0] if new_rows else None,
                                "severity": finding["severity"].title(),
                                "explanation": finding["explanation"],
                            }
                        )
                for trigger in triggers:
                    tx = trigger["tx"] or {}
                    tx_hash = tx.get("tx_hash")
                    
                    # TRANSACTION-BACKED ALERT: Real tx_hash exists
                    if tx_hash:
                        event_identity = adapter.transfer_identity(tx)
                        # Existing BTC/ETH rows used tx-hash logical identity before
                        # stable per-transfer event IDs existed. Preserve that lookup
                        # only when the adapter still uses the hash as its identity.
                        if event_identity == tx_hash and db.scalar(
                            select(WalletAlert.id).where(
                                WalletAlert.wallet == wallet.address,
                                WalletAlert.chain == chain,
                                WalletAlert.tx_hash == tx_hash,
                                WalletAlert.trigger_type == trigger["name"],
                            )
                        ):
                            continue
                        # Compute new stable dedupe_key (excludes mutable risk_score)
                        dedupe = hashlib.sha256(
                            (
                                f"{wallet.id}:{chain}:{event_identity}:"
                                f"{trigger['name']}"
                            ).encode()
                        ).hexdigest()
                        if db.scalar(select(WalletAlert.id).where(WalletAlert.dedupe_key == dedupe)):
                            continue
                    
                    # RISK-ONLY ALERT: No real transaction, falls back to "risk"
                    else:
                        # Preserve pre-Phase-8 semantics: include risk_score for risk-only deduplication
                        dedupe = hashlib.sha256(
                            (
                                f"{wallet.id}:{chain}:risk:"
                                f"{trigger['name']}:{result['risk']['score']}"
                            ).encode()
                        ).hexdigest()
                        
                        # Check dedupe_key (old risk-based formula)
                        if db.scalar(
                            select(WalletAlert.id).where(WalletAlert.dedupe_key == dedupe)
                        ):
                            continue
                    
                    direction = tx.get("direction")
                    db.add(
                        WalletAlert(
                            wallet=wallet.address,
                            chain=chain,
                            tx_hash=tx_hash,
                            trigger_type=trigger["name"],
                            severity=trigger["severity"],
                            risk_score=result["risk"]["score"],
                            explanation=trigger["explanation"],
                            counterparty=tx.get("to_address")
                            if direction == "outgoing"
                            else tx.get("from_address"),
                            amount=tx.get("value_native"),
                            token=tx.get("token_symbol"),
                            case_id=wallet.case_id,
                            dedupe_key=dedupe,
                        )
                    )
                wallet.last_checked = datetime.now(timezone.utc)
                if transactions:
                    cursor = getattr(adapter, "monitoring_cursor", adapter.transfer_identity)
                    wallet.last_seen_tx = cursor(transactions[0])
                    wallet.last_seen_block = transactions[0]["block_number"]
                run.new_transactions = len(new_rows)
                run.status = "completed"
                run.completed_at = datetime.now(timezone.utc)
                processed += 1
            except Exception as exc:
                run.status = "failed"
                run.error = str(exc)
                run.completed_at = datetime.now(timezone.utc)
                logger.warning("Wallet monitoring failed for %s: %s", wallet.address, exc)
            db.commit()
        return {"chain": chain, "processed": processed, "run_ids": run_ids}
    finally:
        db.close()


def start_monitoring() -> None:
    if settings.monitoring_backend == "celery":
        if importlib.util.find_spec("celery") is None:
            logger.warning(
                "Celery monitoring requested but optional scale dependencies are "
                "not installed; using APScheduler fallback"
            )
        else:
            logger.info(
                "Celery monitoring selected; start the external worker and beat processes"
            )
            return
    if scheduler.running:
        return
    for definition in reversed(list_chains()):
        if Capability.MONITORING not in definition.capabilities:continue
        scheduler.add_job(monitor_chain,'interval',minutes=definition.adapter().monitoring_interval(settings),
                          args=[definition.chain_id],id='greedy-collector-'+definition.chain_id,
                          replace_existing=True,max_instances=1,coalesce=True)
    scheduler.start()


def stop_monitoring() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)


def monitoring_status() -> dict:
    celery_installed = importlib.util.find_spec("celery") is not None
    active = settings.monitoring_backend
    configured = True
    if active == "celery":
        if celery_installed and settings.redis_url:
            configured = True
        else:
            active = "apscheduler"
            configured = True
    elif active != "apscheduler":
        active = "disabled"
        configured = False
    return {
        "requested": settings.monitoring_backend,
        "active": active,
        "configured": configured,
        "celery_installed": celery_installed,
        "fallback": "apscheduler",
        "scheduler_running": scheduler.running,
        "ethereum_interval_minutes": settings.ethereum_monitor_minutes,
        "bitcoin_interval_minutes": settings.bitcoin_monitor_minutes,
        "tron_interval_minutes": settings.tron_monitor_minutes,
        "chain_intervals": {
            definition.chain_id: definition.adapter().monitoring_interval(settings)
            for definition in list_chains()
            if Capability.MONITORING in definition.capabilities
        },
    }
