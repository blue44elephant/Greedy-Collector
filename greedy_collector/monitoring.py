import asyncio
from datetime import datetime, timezone
import hashlib
import importlib.util
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

from .config import get_settings
from .database import SessionLocal
from .models import MonitoringRun, WalletAlert, WatchlistWallet
from .schemas import LookupRequest
from .services import GreedyCollectorService

logger = logging.getLogger("GreedyCollector.Monitoring")
settings = get_settings()
scheduler = AsyncIOScheduler(timezone="UTC")


async def monitor_chain(chain: str) -> dict:
    service = GreedyCollectorService()
    db = SessionLocal()
    processed = 0
    try:
        wallets = db.scalars(
            select(WatchlistWallet).where(
                WatchlistWallet.chain == chain, WatchlistWallet.enabled.is_(True)
            )
        ).all()
        for wallet in wallets:
            run = MonitoringRun(wallet_id=wallet.id)
            db.add(run)
            db.flush()
            previous_tx = wallet.last_seen_tx
            try:
                result = await service.lookup_address(
                    db, LookupRequest(chain=chain, address=wallet.address, refresh=True)
                )
                transactions = result["transactions"]
                
                # FIRST-RUN DETECTION AND BASELINE ESTABLISHMENT
                # On first observation (last_seen_tx is None), establish stable baseline silently
                if previous_tx is None:
                    # Determine stable baseline for first-run
                    baseline_tx = None
                    
                    if chain == "bitcoin":
                        # Bitcoin: use first CONFIRMED transaction as baseline (skip volatile mempool)
                        confirmed = [
                            tx for tx in transactions
                            if (tx.get("timestamp") if isinstance(tx, dict) else tx.timestamp) is not None
                        ]
                        if confirmed:
                            baseline_tx = confirmed[0]  # First confirmed (newest after adapter sorts)
                        # If only mempool txs: baseline_tx remains None (don't persist volatile reference)
                    else:  # ethereum and other chains
                        # Ethereum: all txs are confirmed, use newest
                        if transactions:
                            baseline_tx = transactions[0]
                    
                    # Establish baseline without alerting
                    wallet.last_checked = datetime.now(timezone.utc)
                    if baseline_tx:
                        tx_hash = baseline_tx.get("tx_hash") if isinstance(baseline_tx, dict) else baseline_tx.tx_hash
                        block_number = baseline_tx.get("block_number") if isinstance(baseline_tx, dict) else baseline_tx.block_number
                        wallet.last_seen_tx = tx_hash
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
                boundary_found = True
                if previous_tx is not None:
                    # Previous boundary exists - verify it's in current results
                    boundary_found = any(
                        tx["tx_hash"] == previous_tx
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
                    if previous_tx and tx["tx_hash"] == previous_tx:
                        break
                    new_rows.append(tx)

                triggers = []
                for tx in new_rows:
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
                        # Use logical identity to detect existing alert (catches both old and new hash formats)
                        existing = db.scalar(
                            select(WalletAlert.id).where(
                                WalletAlert.wallet == wallet.address,
                                WalletAlert.chain == chain,
                                WalletAlert.tx_hash == tx_hash,
                                WalletAlert.trigger_type == trigger["name"],
                            )
                        )
                        if existing:
                            continue
                        
                        # Compute new stable dedupe_key (excludes mutable risk_score)
                        dedupe = hashlib.sha256(
                            (
                                f"{wallet.id}:{chain}:{tx_hash}:"
                                f"{trigger['name']}"
                            ).encode()
                        ).hexdigest()
                    
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
                    wallet.last_seen_tx = transactions[0]["tx_hash"]
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
        return {"chain": chain, "processed": processed}
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
    scheduler.add_job(
        monitor_chain,
        "interval",
        minutes=settings.ethereum_monitor_minutes,
        args=["ethereum"],
        id="greedy-collector-ethereum",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        monitor_chain,
        "interval",
        minutes=settings.bitcoin_monitor_minutes,
        args=["bitcoin"],
        id="greedy-collector-bitcoin",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
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
    }
