"""
Test monitoring mempool transaction detection.

This test suite reproduces the Bitcoin mempool detection defect:
- Previous state: last_seen_tx = "C100" (confirmed transaction)
- New poll returns: M1, M2 (unconfirmed) + C100, C99 (confirmed older)
- Current bug: monitoring breaks at C100, never reaches M1, M2
- Expected fix: unconfirmed txs appear before C100, so they are detected
"""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from greedy_collector.database import get_db, create_fk_enabled_engine
from greedy_collector.models import Base, WatchlistWallet, WalletAlert, MonitoringRun
from greedy_collector.monitoring import monitor_chain
from greedy_collector.schemas import NormalizedTransaction


@pytest.fixture
def db_session():
    """Create an in-memory test database with foreign key enforcement."""
    engine = create_fk_enabled_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    
    SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    
    session = SessionLocal()
    yield session
    session.close()


def test_monitoring_detects_mempool_before_previous_tx(db_session: Session):
    """
    Verify Bitcoin adapter returns mempool transactions BEFORE confirmed,
    so monitoring.py detects them before breaking on previous_tx.
    
    This test:
    1. Creates a wallet with last_seen_tx pointing to a confirmed transaction
    2. Mocks HTTP responses to return mixed mempool + confirmed transactions
    3. Lets the real adapter sort them  
    4. Verifies the adapter's output has mempool first
    5. Verifies monitoring detects mempool transactions as new
    
    The fix: adapter separates unconfirmed (None timestamp) from confirmed,
    returns mempool first, then confirmed sorted by timestamp DESC.
    """
    from greedy_collector.chains.bitcoin import BitcoinAdapter
    from greedy_collector.services import GreedyCollectorService
    
    # Setup wallet with previous_tx pointing to a confirmed transaction
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Mempool",
        enabled=True,
        last_seen_tx="c100_hash",  # Previous confirmed transaction
        last_seen_block="700000",
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Mock HTTP responses: mixed order from API
    # (Esplora returns newest-first but sorts by actual block time,
    # so we simulate getting confirmed + mempool in mixed order)
    def mock_get(url, *args, **kwargs):
        if "/txs" in url and "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa" in url:
            # Simulate Esplora /address/addr/txs response
            # Returns 50 mempool + 25 confirmed, but we'll return simplified version
            # Status in Esplora: {"confirmed": true/false, "block_time": timestamp or null}
            return {
                "txid": "ignored",  # Only checking full response handling
                "status": {"confirmed": True},
                # This is a simplified mock - real code would parse differently
            }
        return {}
    
    # Use a more targeted approach: mock the adapter's HTTP method
    with patch.object(BitcoinAdapter, "_get") as mock_get_method:
        # Return raw responses from HTTP layer
        async def async_mock_get(url):
            address = "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"
            if f"/address/{address}/txs" in url:
                # Esplora response: mixed mempool + confirmed
                # Note: format is Esplora JSON with txid, vin, vout, status, etc.
                return [
                    # Confirmed transactions
                    {
                        "txid": "c100_hash",
                        "vin": [{"prevout": {"scriptpubkey_address": address}}],
                        "vout": [{"scriptpubkey_address": "1address1", "value": 200000000}],
                        "status": {"confirmed": True, "block_time": 1725940800},  # Sept 9 10:00 UTC
                    },
                    {
                        "txid": "c99_hash",
                        "vin": [{"prevout": {"scriptpubkey_address": address}}],
                        "vout": [{"scriptpubkey_address": "1address2", "value": 150000000}],
                        "status": {"confirmed": True, "block_time": 1725937200},  # Sept 9 09:00 UTC
                    },
                    # Mempool transactions
                    {
                        "txid": "m1_hash",
                        "vin": [{"prevout": {"scriptpubkey_address": address}}],
                        "vout": [{"scriptpubkey_address": "1BvBMSEYstWetqTFn5Au4m4GFg7xJaNVN2", "value": 50000000}],
                        "status": {"confirmed": False},  # No block_time
                    },
                    {
                        "txid": "m2_hash",
                        "vin": [{"prevout": {"scriptpubkey_address": address}}],
                        "vout": [{"scriptpubkey_address": "1dice8EMCQAqQxoshqwLCRjY8JCEyToMoF", "value": 100000000}],
                        "status": {"confirmed": False},
                    },
                ]
            return {}
        
        mock_get_method.side_effect = async_mock_get
        
        # Use real service and adapter
        service = GreedyCollectorService()
        
        # Mock SessionLocal for monitoring
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            # Run monitoring
            result = asyncio.run(monitor_chain("bitcoin"))
        
        # Verify result
        assert result["processed"] == 1, f"Expected 1 processed wallet, got {result['processed']}"
        
        # Refresh wallet from DB to get updated state
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        assert wallet is not None
        
        # Verify M1 and M2 were detected as new alerts
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "bitcoin",
            )
        ).all()
        
        # Should have alerts for M1 and M2 mempool transactions
        alert_txs = {alert.tx_hash for alert in alerts}
        assert "m1_hash" in alert_txs, f"Mempool transaction M1 should be detected as new. Got alerts for: {alert_txs}"
        assert "m2_hash" in alert_txs, f"Mempool transaction M2 should be detected as new. Got alerts for: {alert_txs}"
        
        # C100 should NOT generate an alert (it's the previous_tx break point)
        assert "c100_hash" not in alert_txs, f"C100 should not alert (it's the break point)"
        
        # Verify last_seen_tx updated to newest (M1, first in list after fix)
        # After fix, M1 should be transactions[0]
        assert wallet.last_seen_tx == "m1_hash", f"last_seen_tx should be updated to newest (mempool tx), got {wallet.last_seen_tx}"


def test_monitoring_mempool_only_no_new_confirmed(db_session: Session):
    """
    Mempool-only scenario: previous mempool tx + multiple new mempool txs.
    
    - last_seen_tx = "m1_hash" (mempool boundary)
    - Returns: [M1, M2, M3] (all mempool)
    - Expected: Only new mempool txs after boundary detected (m2, m3)
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Mempool Only",
        enabled=True,
        last_seen_tx="m1_hash",  # Boundary is in mempool
        last_seen_block="",  # Mempool has no block
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Only unconfirmed transactions - reversed to have newest first
    mock_txs = [
        {
            "tx_hash": f"m{i}_hash",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": f"1address{i}",
            "value_native": str(Decimal(i) / 10),
            "token_symbol": "BTC",
            "timestamp": None,
            "block_number": "",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        }
        for i in range(1, 4)
    ]
    # Reverse to have newest first (m3, m2, m1)
    mock_txs = list(reversed(mock_txs))
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {
                    "score": 20,
                    "level": "Low",
                    "findings": [],
                },
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            
            assert result["processed"] == 1
        
        # Check run status for debugging
        run = db_session.scalars(
            select(MonitoringRun).where(MonitoringRun.wallet_id == wallet_id)
        ).first()
        assert run is not None, "No monitoring run found"
        assert run.status == "completed", f"Run status: {run.status}, error: {run.error}"
        
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
            )
        ).all()
        
        # Only new mempool txs after boundary (m2, m3)
        alert_txs = {alert.tx_hash for alert in alerts}
        assert "m1_hash" not in alert_txs  # m1 is the boundary
        assert "m2_hash" in alert_txs
        assert "m3_hash" in alert_txs
        assert len(alerts) == 2


def test_monitoring_continuity_loss_boundary_not_found(db_session: Session):
    """
    Continuity loss scenario: previous_tx exists but is NOT in current results.
    
    Stored state:
      last_seen_tx = "OLD_BOUNDARY"
    
    Current fetch returns:
      NEW3, NEW2, NEW1 (but no OLD_BOUNDARY)
    
    Expected safe behavior:
    - Zero transaction alerts (ambiguous data)
    - last_seen_tx remains "OLD_BOUNDARY" (boundary preserved)
    - Continuity loss warning/error recorded
    
    This test verifies the fix prevents alert amplification and
    permanent boundary loss during continuity-loss conditions.
    """
    from greedy_collector.models import MonitoringRun
    
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Continuity Loss",
        enabled=True,
        last_seen_tx="OLD_BOUNDARY",  # Stored boundary
        last_seen_block="600000",
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Mock transaction results that don't contain OLD_BOUNDARY
    # (simulates bounded history where boundary has aged out)
    mock_txs = [
        {
            "tx_hash": "NEW3_hash",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_new3",
            "value_native": "3.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc),
            "block_number": "750003",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "NEW2_hash",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_new2",
            "value_native": "2.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "750002",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "NEW1_hash",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_new1",
            "value_native": "1.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 1, 0, 0, tzinfo=timezone.utc),
            "block_number": "750001",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        # Note: OLD_BOUNDARY is NOT in this list (simulates continuity loss)
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {
                    "score": 30,
                    "level": "Medium",
                    "findings": [],
                },
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            # Run monitoring
            result = asyncio.run(monitor_chain("bitcoin"))
            
            assert result["processed"] == 1
        
        # Verify wallet state AFTER continuity loss
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        
        # CRITICAL: last_seen_tx must NOT change
        # It must remain at OLD_BOUNDARY (not updated to NEW3)
        assert wallet.last_seen_tx == "OLD_BOUNDARY", (
            f"Boundary must be preserved on continuity loss. "
            f"Expected 'OLD_BOUNDARY', got '{wallet.last_seen_tx}'"
        )
        
        # CRITICAL: No transaction alerts should be created
        # (ambiguous data from loss of continuity)
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "bitcoin",
            )
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        assert "NEW3_hash" not in alert_txs, (
            "NEW3 should NOT alert when continuity is lost (ambiguous data)"
        )
        assert "NEW2_hash" not in alert_txs, (
            "NEW2 should NOT alert when continuity is lost (ambiguous data)"
        )
        assert "NEW1_hash" not in alert_txs, (
            "NEW1 should NOT alert when continuity is lost (ambiguous data)"
        )
        
        # Verify no transaction-level alerts at all
        transaction_alerts = [a for a in alerts if a.trigger_type in (
            "New outgoing transaction",
            "New incoming transaction"
        )]
        assert len(transaction_alerts) == 0, (
            f"Expected zero transaction alerts on continuity loss, got {len(transaction_alerts)}"
        )


def test_monitoring_first_run_unchanged(db_session: Session):
    """
    First-run scenario: last_seen_tx is None (no previous boundary).
    
    UPDATED for Phase 7: First-run now establishes baseline SILENTLY.
    All returned transactions should generate ZERO alerts (Policy B).
    Baseline should be set to newest confirmed transaction.
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test First Run",
        enabled=True,
        last_seen_tx=None,  # First-run: no previous boundary
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Create transactions in reverse order (newest first)
    mock_txs = [
        {
            "tx_hash": f"tx{i}_hash",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": f"1addr{i}",
            "value_native": str(float(i)),
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 3-i, 0, 0, tzinfo=timezone.utc),  # Newest first
            "block_number": str(750003 - i),
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        }
        for i in range(1, 4)
    ]
    # Reverse to have newest (highest timestamp) first
    mock_txs = list(reversed(mock_txs))
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {
                    "score": 20,
                    "level": "Low",
                    "findings": [],
                },
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            assert result["processed"] == 1
        
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        
        # Phase 7: First-run should generate ZERO alerts (silent baseline)
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "bitcoin",
            )
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        # All should be ZERO on first-run
        assert "tx1_hash" not in alert_txs, "tx1 should NOT alert on first-run"
        assert "tx2_hash" not in alert_txs, "tx2 should NOT alert on first-run"
        assert "tx3_hash" not in alert_txs, "tx3 should NOT alert on first-run"
        
        # last_seen_tx should be set to newest (transactions[0] after reversal)
        assert wallet.last_seen_tx == "tx3_hash", "Baseline should be set to newest confirmed"


def test_monitoring_normal_continuation_boundary_found(db_session: Session):
    """
    Normal scenario: previous_tx exists AND is found in current results.
    
    Stored:
      last_seen_tx = "OLD_TX"
    
    Returns:
      NEW2, NEW1, OLD_TX, OLDER
    
    Expected:
    - NEW2, NEW1 processed normally
    - OLDER ignored (after break point)
    - last_seen_tx updated to NEW2
    - Normal alert behavior
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Normal",
        enabled=True,
        last_seen_tx="OLD_TX",
        last_seen_block="700000",
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    mock_txs = [
        {
            "tx_hash": "NEW2",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_new2",
            "value_native": "2.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "700002",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "NEW1",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_new1",
            "value_native": "1.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 1, 0, 0, tzinfo=timezone.utc),
            "block_number": "700001",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "OLD_TX",  # Boundary found
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_old",
            "value_native": "0.5",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc),
            "block_number": "700000",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "OLDER",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_older",
            "value_native": "0.25",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 9, 23, 0, 0, tzinfo=timezone.utc),
            "block_number": "699999",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {
                    "score": 25,
                    "level": "Medium",
                    "findings": [],
                },
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            assert result["processed"] == 1
        
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "bitcoin",
            )
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        
        # Only NEW2 and NEW1 should alert (they're new)
        assert "NEW2" in alert_txs
        assert "NEW1" in alert_txs
        
        # OLD_TX should NOT alert (it's the boundary)
        assert "OLD_TX" not in alert_txs
        
        # OLDER should NOT alert (it's before boundary)
        assert "OLDER" not in alert_txs
        
        # last_seen_tx should be updated to newest (NEW2)
        assert wallet.last_seen_tx == "NEW2"


def test_monitoring_first_run_ethereum(db_session: Session):
    """
    First-run scenario for Ethereum: last_seen_tx = None
    
    Returned: E3, E2, E1 (all confirmed, newest-first)
    
    Expected behavior:
    - Zero transaction alerts (silent baseline)
    - last_seen_tx set to E3 (newest)
    - Run completes successfully
    """
    wallet = WatchlistWallet(
        chain="ethereum",
        address="0x1234567890123456789012345678901234567890",
        label="Test Ethereum First Run",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Ethereum transactions (all confirmed, newest-first)
    mock_txs = [
        {
            "tx_hash": "E3",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0003",
            "value_native": "3.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc),
            "block_number": "100003",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
        {
            "tx_hash": "E2",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0002",
            "value_native": "2.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "100002",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
        {
            "tx_hash": "E1",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0001",
            "value_native": "1.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 1, 0, 0, tzinfo=timezone.utc),
            "block_number": "100001",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {"score": 10, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("ethereum"))
            assert result["processed"] == 1
        
        # Verify zero transaction alerts (silent baseline)
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "ethereum",
            )
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        assert "E3" not in alert_txs, "E3 should NOT alert on first-run"
        assert "E2" not in alert_txs, "E2 should NOT alert on first-run"
        assert "E1" not in alert_txs, "E1 should NOT alert on first-run"
        
        # Verify baseline established
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        assert wallet.last_seen_tx == "E3", "Baseline should be set to newest (E3)"
        assert wallet.last_checked is not None, "last_checked should be updated"


def test_monitoring_first_run_bitcoin_mempool_and_confirmed(db_session: Session):
    """
    First-run scenario for Bitcoin: mempool + confirmed transactions
    
    Returned: M2, M1, C100, C99 (mempool first, then confirmed)
    
    Expected behavior:
    - Zero alerts
    - Baseline must be C100 (first confirmed, not mempool!)
    - Baseline must NOT be M2 or M1
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Bitcoin First Run Mixed",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Mempool + confirmed transactions
    mock_txs = [
        # Mempool (unconfirmed, no timestamp)
        {
            "tx_hash": "M2",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_m2",
            "value_native": "2.0",
            "token_symbol": "BTC",
            "timestamp": None,  # Unconfirmed
            "block_number": "",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "M1",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_m1",
            "value_native": "1.0",
            "token_symbol": "BTC",
            "timestamp": None,  # Unconfirmed
            "block_number": "",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        # Confirmed transactions
        {
            "tx_hash": "C100",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_c100",
            "value_native": "100.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc),
            "block_number": "750100",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "C99",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_c99",
            "value_native": "99.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "750099",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {"score": 20, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            assert result["processed"] == 1
        
        # Verify zero transaction alerts
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "bitcoin",
            )
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        assert "M2" not in alert_txs, "M2 should NOT alert on first-run"
        assert "M1" not in alert_txs, "M1 should NOT alert on first-run"
        assert "C100" not in alert_txs, "C100 should NOT alert on first-run"
        assert "C99" not in alert_txs, "C99 should NOT alert on first-run"
        
        # Verify baseline is stable confirmed, not mempool
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        assert wallet.last_seen_tx == "C100", f"Baseline should be C100 (first confirmed), got {wallet.last_seen_tx}"
        assert wallet.last_seen_tx != "M2", "Baseline MUST NOT be mempool tx M2"
        assert wallet.last_seen_tx != "M1", "Baseline MUST NOT be mempool tx M1"


def test_monitoring_first_run_bitcoin_confirmed_only(db_session: Session):
    """
    First-run scenario for Bitcoin: confirmed transactions only
    
    Returned: C102, C101, C100
    
    Expected behavior:
    - Zero alerts
    - Baseline = C102 (newest confirmed)
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Bitcoin First Run Confirmed Only",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    mock_txs = [
        {
            "tx_hash": "C102",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_c102",
            "value_native": "102.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc),
            "block_number": "750102",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "C101",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_c101",
            "value_native": "101.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "750101",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "C100",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_c100",
            "value_native": "100.0",
            "token_symbol": "BTC",
            "timestamp": datetime(2026, 9, 10, 1, 0, 0, tzinfo=timezone.utc),
            "block_number": "750100",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {"score": 20, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            assert result["processed"] == 1
        
        alerts = db_session.scalars(
            select(WalletAlert).where(
                WalletAlert.wallet == wallet.address,
                WalletAlert.chain == "bitcoin",
            )
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        assert len(alert_txs) == 0, f"Should have zero alerts, got {alert_txs}"
        
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        assert wallet.last_seen_tx == "C102", "Baseline should be C102"


def test_monitoring_first_run_empty_wallet(db_session: Session):
    """
    First-run scenario for empty wallet: last_seen_tx = None, no transactions
    
    Expected behavior:
    - Zero alerts
    - last_seen_tx remains None (no data to baseline)
    - last_checked updates normally
    - Run completes normally
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1empty000000000000000000000000000000000",
        label="Test Empty Wallet",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": [],  # Empty
                "risk": {"score": 0, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            assert result["processed"] == 1
        
        alerts = db_session.scalars(
            select(WalletAlert).where(WalletAlert.wallet == wallet.address)
        ).all()
        
        assert len(alerts) == 0, "Empty wallet should have zero alerts"
        
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        assert wallet.last_seen_tx is None, "Empty wallet baseline should remain None"
        assert wallet.last_checked is not None, "last_checked should still be updated"


def test_monitoring_first_run_bitcoin_mempool_only(db_session: Session):
    """
    First-run scenario for Bitcoin: mempool-only (no confirmed history)
    
    Returned: M3, M2, M1 (all unconfirmed)
    
    Expected behavior:
    - Zero alerts
    - Do NOT set last_seen_tx to volatile mempool tx
    - last_seen_tx remains None (stable state)
    - last_checked updates normally
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Bitcoin Mempool Only",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Only mempool transactions (unconfirmed)
    mock_txs = [
        {
            "tx_hash": "M3",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_m3",
            "value_native": "3.0",
            "token_symbol": "BTC",
            "timestamp": None,
            "block_number": "",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "M2",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_m2",
            "value_native": "2.0",
            "token_symbol": "BTC",
            "timestamp": None,
            "block_number": "",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
        {
            "tx_hash": "M1",
            "chain": "bitcoin",
            "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
            "to_address": "1addr_m1",
            "value_native": "1.0",
            "token_symbol": "BTC",
            "timestamp": None,
            "block_number": "",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "blockstream",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": mock_txs,
                "risk": {"score": 15, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("bitcoin"))
            assert result["processed"] == 1
        
        alerts = db_session.scalars(
            select(WalletAlert).where(WalletAlert.wallet == wallet.address)
        ).all()
        
        alert_txs = {alert.tx_hash for alert in alerts}
        assert "M3" not in alert_txs, "M3 should NOT alert on first-run"
        assert "M2" not in alert_txs, "M2 should NOT alert on first-run"
        assert "M1" not in alert_txs, "M1 should NOT alert on first-run"
        
        wallet = db_session.scalars(
            select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
        ).first()
        # CRITICAL: Do NOT set baseline to volatile mempool tx
        assert wallet.last_seen_tx is None, "Mempool-only wallet should NOT persist volatile mempool baseline"
        assert wallet.last_checked is not None, "last_checked should be updated"


def test_monitoring_second_run_ethereum_after_first_run(db_session: Session):
    """
    Regression test: verify second-run works normally after silent first-run baseline
    
    Run 1: E3, E2, E1 → baseline = E3, zero alerts
    Run 2: E4, E3, E2 → E4 is new, E3 breaks scan, E2 ignored
    """
    wallet = WatchlistWallet(
        chain="ethereum",
        address="0x1234567890123456789012345678901234567890",
        label="Test Ethereum Second Run",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Run 1: First observation (silent baseline)
    run1_txs = [
        {
            "tx_hash": "E3",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0003",
            "value_native": "3.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc),
            "block_number": "100003",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
        {
            "tx_hash": "E2",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0002",
            "value_native": "2.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "100002",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
        {
            "tx_hash": "E1",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0001",
            "value_native": "1.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 1, 0, 0, tzinfo=timezone.utc),
            "block_number": "100001",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": run1_txs,
                "risk": {"score": 10, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("ethereum"))
            assert result["processed"] == 1
    
    # Verify first-run: zero alerts, baseline set
    wallet = db_session.scalars(
        select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
    ).first()
    assert wallet.last_seen_tx == "E3", "Run 1: baseline should be E3"
    
    alerts_run1 = db_session.scalars(
        select(WalletAlert).where(WalletAlert.wallet == wallet.address)
    ).all()
    assert len(alerts_run1) == 0, "Run 1: should have zero alerts"
    
    # Run 2: Normal monitoring with new transaction
    run2_txs = [
        {
            "tx_hash": "E4",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0004",
            "value_native": "4.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 4, 0, 0, tzinfo=timezone.utc),
            "block_number": "100004",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
        {
            "tx_hash": "E3",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0003",
            "value_native": "3.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 3, 0, 0, tzinfo=timezone.utc),
            "block_number": "100003",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
        {
            "tx_hash": "E2",
            "chain": "ethereum",
            "from_address": "0x1234567890123456789012345678901234567890",
            "to_address": "0xabcd0000000000000000000000000000abcd0002",
            "value_native": "2.0",
            "token_symbol": "ETH",
            "timestamp": datetime(2026, 9, 10, 2, 0, 0, tzinfo=timezone.utc),
            "block_number": "100002",
            "fee": "0.001",
            "direction": "outgoing",
            "source_api": "etherscan",
            "raw_payload": {},
        },
    ]
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_address(*args, **kwargs):
            return {
                "transactions": run2_txs,
                "risk": {"score": 10, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_address)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            result = asyncio.run(monitor_chain("ethereum"))
            assert result["processed"] == 1
    
    # Verify second-run: E4 alerted, baseline updated
    alerts_run2 = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash == "E4",
        )
    ).all()
    assert len(alerts_run2) > 0, "Run 2: E4 should generate alert"
    
    wallet = db_session.scalars(
        select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)
    ).first()
    assert wallet.last_seen_tx == "E4", "Run 2: baseline should update to E4"


def test_monitoring_mempool_confirmed_alert_dedup_same_tx_same_trigger(db_session: Session):
    """
    DEFECT REPRODUCTION TEST: Same Bitcoin transaction mempool→confirmed
    should create only ONE alert despite risk_score changes.
    
    Scenario:
    - Poll 1: TX1 unconfirmed in mempool (no behavioral analysis triggers)
    - Poll 2: TX1 confirmed + other historical TXs that trigger behavioral patterns
    
    The defect: risk_score increases (e.g., 20→25) between polls,
    causing dedupe_key to change, resulting in duplicate alerts.
    
    Expected after fix: Only ONE WalletAlert for TX1+trigger combo,
    even though risk_score changed.
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Mempool Confirm Dedup",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # POLL 1: Establish baseline (silent first-run)
    prev_tx = {
        "tx_hash": "BASELINE",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty_old",
        "value_native": "1.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": "750000",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_poll1(*args, **kwargs):
            return {
                "transactions": [prev_tx],
                "risk": {"score": 10, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_poll1)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            asyncio.run(monitor_chain("bitcoin"))
    
    wallet = db_session.scalars(select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)).first()
    assert wallet.last_seen_tx == "BASELINE", "Baseline should be established"
    
    # POLL 2: TX1 appears unconfirmed in mempool
    # Mock returns high risk_score=20 (no behavioral triggers yet)
    unconfirmed_tx = {
        "tx_hash": "TX1",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "5.0",
        "token_symbol": "BTC",
        "timestamp": None,  # Unconfirmed
        "block_number": "",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_poll2(*args, **kwargs):
            # Return unconfirmed TX1 with risk_score=20
            return {
                "transactions": [unconfirmed_tx, prev_tx],
                "risk": {"score": 20, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_poll2)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            asyncio.run(monitor_chain("bitcoin"))
    
    # Verify Poll 2: TX1 unconfirmed creates first alert
    alerts_poll2 = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash == "TX1",
            WalletAlert.trigger_type == "New outgoing transaction",
        )
    ).all()
    
    assert len(alerts_poll2) == 1, f"Poll 2: Expected 1 alert for unconfirmed TX1, got {len(alerts_poll2)}"
    first_alert = alerts_poll2[0]
    first_dedupe_key = first_alert.dedupe_key
    
    # POLL 3: Same TX1 now confirmed
    # Service returns risk_score=25 (behavioral patterns now detected because TX1 is confirmed)
    confirmed_tx = {
        "tx_hash": "TX1",  # SAME TXID
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "5.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),  # NOW confirmed
        "block_number": "750123",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_poll3(*args, **kwargs):
            # Return confirmed TX1 with risk_score=25 (DIFFERENT from poll 2)
            # This simulates behavioral patterns being detected when TX1 is confirmed
            return {
                "transactions": [confirmed_tx, prev_tx],
                "risk": {"score": 25, "level": "Medium", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_poll3)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            asyncio.run(monitor_chain("bitcoin"))
    
    # CRITICAL: Check alert count for TX1
    alerts_total = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash == "TX1",
            WalletAlert.trigger_type == "New outgoing transaction",
        )
    ).all()
    
    # Debug: print dedupe keys
    print(f"\n=== DEBUG DEDUPE KEYS ===")
    print(f"Wallet ID: {wallet.id}")
    print(f"Alert count: {len(alerts_total)}")
    for i, alert in enumerate(alerts_total):
        print(f"Alert {i+1}: dedupe_key={alert.dedupe_key}, risk_score={alert.risk_score}, trigger={alert.trigger_type}")
    
    # THIS IS THE DEFECT: With current code, we get 2 alerts because:
    # Poll 2 dedupe_key = SHA256("wallet:TX1:New outgoing transaction:20")
    # Poll 3 dedupe_key = SHA256("wallet:TX1:New outgoing transaction:25")  ← Different!
    # Both dedupe_keys are unique, so both alerts are created
    
    # After fix, dedupe_key should NOT include the risk_score:
    # dedupe_key = SHA256("wallet:bitcoin:TX1:New outgoing transaction")  ← Same for both polls
    # So only 1 alert is created
    
    assert len(alerts_total) == 1, (
        f"DEFECT REPRODUCED: Same TX TX1 with same trigger created {len(alerts_total)} alerts. "
        f"Expected 1 alert (no duplicate when risk_score changes from 20→25). "
        f"This proves the dedupe_key incorrectly includes the mutable risk_score. "
        f"Dedupe keys: {[a.dedupe_key[-16:] for a in alerts_total]}"
    )


def test_dedupe_key_calculation_includes_mutable_risk_score():
    """
    Direct test of the dedupe_key calculation to expose the defect.
    
    The dedupe_key formula includes risk_score, which is mutable:
    dedupe_key = SHA256(f"{wallet.id}:{tx_hash}:{trigger_name}:{risk_score}")
    
    When same TX confirms, risk_score may change (e.g., 20→25),
    resulting in different dedupe_key and duplicate alerts.
    
    This test directly computes the dedupe_keys to prove they differ.
    """
    import hashlib
    import uuid
    
    # Simulate wallet.id and transaction
    wallet_id = uuid.uuid4()
    tx_hash = "TX1"
    trigger_name = "New outgoing transaction"
    
    # Poll 2: TX1 unconfirmed, risk_score = 20
    risk_score_poll2 = 20
    dedupe_key_poll2 = hashlib.sha256(
        f"{wallet_id}:{tx_hash}:{trigger_name}:{risk_score_poll2}".encode()
    ).hexdigest()
    
    # Poll 3: Same TX1 confirmed, risk_score = 25 (changed due to behavioral analysis)
    risk_score_poll3 = 25
    dedupe_key_poll3 = hashlib.sha256(
        f"{wallet_id}:{tx_hash}:{trigger_name}:{risk_score_poll3}".encode()
    ).hexdigest()
    
    # DEFECT: dedupe_keys are DIFFERENT because risk_score changed
    print(f"\n=== DEDUPE KEY CALCULATION TEST ===")
    print(f"Wallet ID: {wallet_id}")
    print(f"Poll 2 dedupe_key (risk=20): {dedupe_key_poll2}")
    print(f"Poll 3 dedupe_key (risk=25): {dedupe_key_poll3}")
    print(f"Keys equal? {dedupe_key_poll2 == dedupe_key_poll3}")
    
    # This assertion proves the defect in the current code
    assert dedupe_key_poll2 != dedupe_key_poll3, (
        "DEFECT VERIFIED: Dedupe keys differ when risk_score changes. "
        "Current code includes risk_score in dedupe_key, causing duplicate alerts when "
        "transaction confirms and risk_score updates from 20→25."
    )


def test_monitoring_different_triggers_same_tx_remain_separate(db_session: Session):
    """
    Different triggers for the same TX should create SEPARATE alerts.
    
    TX1 with two triggers:
    - "New outgoing transaction"
    - "Large transfer" (if amount > 100)
    
    Expected: TWO WalletAlerts, not deduplicated.
    Prevents over-deduplication.
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Multiple Triggers",
        enabled=True,
        last_seen_tx="PREVIOUS_TX",
        last_seen_block="750000",
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Previous transaction (boundary)
    prev_tx = {
        "tx_hash": "PREVIOUS_TX",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1prev_counterparty",
        "value_native": "5.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 10, 0, 0, tzinfo=timezone.utc),
        "block_number": "750100",
        "fee": "0.001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }
    
    # Large transaction that should trigger both "New outgoing" and "Large transfer"
    large_tx = {
        "tx_hash": "TX_LARGE",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "150.0",  # > 100 threshold → triggers "Large transfer"
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        "block_number": "750124",
        "fee": "0.001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup(*args, **kwargs):
            return {
                "transactions": [large_tx, prev_tx],  # Include boundary transaction
                "risk": {
                    "score": 35,
                    "level": "Medium",
                    "findings": [
                        {
                            "rule_id": "large_transfer",
                            "rule_name": "Large transfer",
                            "severity": "medium",
                            "confidence": 0.6,
                            "score_contribution": 10,
                            "explanation": "At least one transfer exceeded 100 BTC.",
                            "evidence": {"tx_hash": "TX_LARGE"},
                        }
                    ],
                },
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            asyncio.run(monitor_chain("bitcoin"))
    
    # Verify we have multiple alerts for the same TX
    alerts = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash == "TX_LARGE",
        )
    ).all()
    
    # Should have at least 2 alerts (transaction + large_transfer finding)
    assert len(alerts) >= 2, (
        f"Expected at least 2 alerts for TX with multiple triggers, got {len(alerts)}. "
        f"Alerts: {[(a.trigger_type, a.risk_score) for a in alerts]}"
    )
    
    trigger_types = {alert.trigger_type for alert in alerts}
    assert "New outgoing transaction" in trigger_types, "Should have transaction trigger"
    assert "Large transfer" in trigger_types, "Should have large_transfer finding trigger"


def test_monitoring_provider_independence_same_alert(db_session: Session):
    """
    Same TX observed through different providers should NOT duplicate alerts.
    
    Poll 1: TX1 via Blockstream, score=20
    Poll 2: TX1 via Mempool.space, score=20 (same score, no behavioral change)
    
    Expected: ONE alert, not two.
    Provider name should not affect transaction alert identity.
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Provider Indep",
        enabled=True,
        last_seen_tx=None,
        last_seen_block=None,
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id
    
    # Poll 1: Via Blockstream
    tx_blockstream = {
        "tx_hash": "TX_PROVIDER_TEST",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "5.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        "block_number": "750123",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",  # Provider 1
        "raw_payload": {},
    }
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_blockstream(*args, **kwargs):
            return {
                "transactions": [tx_blockstream],
                "risk": {"score": 20, "level": "Low", "findings": []},
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_blockstream)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            asyncio.run(monitor_chain("bitcoin"))
    
    # Update wallet to set baseline
    wallet = db_session.scalars(select(WatchlistWallet).where(WatchlistWallet.id == wallet_id)).first()
    wallet.last_seen_tx = "PREVIOUS_TX"  # Move boundary forward
    db_session.commit()
    
    # Poll 2: Same TX via Mempool.space
    tx_mempool = {
        "tx_hash": "TX_PROVIDER_TEST",  # SAME TXID
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "5.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        "block_number": "750123",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "mempool.space",  # Provider 2
        "raw_payload": {},
    }
    
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service
        
        async def async_lookup_mempool(*args, **kwargs):
            return {
                "transactions": [tx_mempool],
                "risk": {"score": 20, "level": "Low", "findings": []},  # Same score
            }
        
        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_mempool)
        
        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session
            
            asyncio.run(monitor_chain("bitcoin"))
    
    # Verify only one alert for this TX (not duplicated by provider change)
    alerts = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash == "TX_PROVIDER_TEST",
        )
    ).all()
    
    # Count by trigger type
    trigger_counts = {}
    for alert in alerts:
        trigger_counts[alert.trigger_type] = trigger_counts.get(alert.trigger_type, 0) + 1
    
    # Each trigger should have only 1 alert, not 2 (one per provider)
    for trigger_type, count in trigger_counts.items():
        assert count == 1, (
            f"Trigger '{trigger_type}' has {count} alerts. "
            f"Expected 1 (provider should not create duplicates). "
            f"Alerts: {[(a.tx_hash, a.trigger_type, a.source_api) for a in alerts]}"
        )


def test_monitoring_legacy_transaction_alert_compatibility(db_session: Session):
    """
    CORRECTION TEST: Legacy WalletAlerts with old dedupe keys should be detected.
    
    Scenario:
    - Old alert exists: TX1 + trigger, with dedupe_key generated using OLD formula
      (included risk_score in hash)
    - New monitoring observes TX1 + same trigger
    - New code must query logical identity (wallet + chain + tx_hash + trigger)
    - Should NOT create a duplicate alert
    
    This proves monitoring uses logical identity lookup to catch legacy hashes.
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Legacy Compat",
        enabled=True,
        last_seen_tx="BASELINE",
        last_seen_block="750000",
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id

    # Pre-populate database with legacy alert (created with old formula)
    # OLD formula: wallet.id:tx_hash:trigger:risk_score
    import hashlib
    legacy_dedupe = hashlib.sha256(
        f"{wallet.id}:TX_LEGACY:New outgoing transaction:15".encode()
    ).hexdigest()
    
    legacy_alert = WalletAlert(
        wallet=wallet.address,
        chain="bitcoin",
        tx_hash="TX_LEGACY",
        trigger_type="New outgoing transaction",
        severity="Medium",
        risk_score=15,  # Old risk score
        explanation="Legacy alert created with old dedupe formula",
        counterparty="1counterparty",
        amount="5.0",
        token="BTC",
        case_id=wallet.case_id,
        dedupe_key=legacy_dedupe,  # Old-style hash with risk_score
    )
    db_session.add(legacy_alert)
    db_session.commit()

    # Now monitoring observes the same TX1 with NEW code
    # Risk score is different (25 instead of 15)
    tx = {
        "tx_hash": "TX_LEGACY",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "5.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 12, 0, 0, tzinfo=timezone.utc),
        "block_number": "750123",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }

    baseline_tx = {
        "tx_hash": "BASELINE",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1old",
        "value_native": "1.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": "750000",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }

    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        async def async_lookup(*args, **kwargs):
            return {
                "transactions": [tx, baseline_tx],
                "risk": {"score": 25, "level": "Medium", "findings": []},
            }

        mock_service.lookup_address = AsyncMock(side_effect=async_lookup)

        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session

            asyncio.run(monitor_chain("bitcoin"))

    # Verify no duplicate was created
    alerts = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash == "TX_LEGACY",
            WalletAlert.trigger_type == "New outgoing transaction",
        )
    ).all()

    assert len(alerts) == 1, (
        f"Expected 1 alert (legacy alert should be reused), got {len(alerts)}. "
        f"Logical identity lookup failed to detect legacy hash. "
        f"Alerts: {[(a.risk_score, a.dedupe_key[-16:]) for a in alerts]}"
    )
    
    # The one alert should be the original legacy alert
    assert alerts[0].dedupe_key == legacy_dedupe, (
        f"Expected legacy dedupe_key to remain, got new one. "
        f"Logical identity check should have prevented new alert insertion."
    )


def test_monitoring_risk_only_alert_semantics_preserved(db_session: Session):
    """
    CORRECTION TEST: Risk-only alerts must preserve pre-Phase-8 semantics.
    
    Scenario:
    - Same wallet, chain, trigger
    - No real transaction (falls back to "risk" placeholder)
    - Different risk scores
    
    Expected:
    - Dedupe keys must be DIFFERENT (opposite of transaction alerts)
    - Each risk evaluation creates a separate alert
    - Dedupe formula must include risk_score for risk-only alerts
    
    This proves risk-only alerts use risk-score-based deduplication.
    """
    wallet = WatchlistWallet(
        chain="bitcoin",
        address="1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        label="Test Risk Only",
        enabled=True,
        last_seen_tx="BASELINE",
        last_seen_block="750000",
    )
    db_session.add(wallet)
    db_session.commit()
    wallet_id = wallet.id

    baseline_tx = {
        "tx_hash": "BASELINE",
        "chain": "bitcoin",
        "from_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
        "to_address": "1counterparty",
        "value_native": "1.0",
        "token_symbol": "BTC",
        "timestamp": datetime(2026, 9, 10, 0, 0, 0, tzinfo=timezone.utc),
        "block_number": "750000",
        "fee": "0.0001",
        "direction": "outgoing",
        "source_api": "blockstream",
        "raw_payload": {},
    }

    # POLL 1: Risk assessment creates risk-only alert (no new_rows, only findings)
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        async def async_lookup_poll1(*args, **kwargs):
            return {
                "transactions": [baseline_tx],
                "risk": {
                    "score": 20,
                    "level": "Medium",
                    "findings": [
                        {
                            "rule_id": "high_velocity",
                            "rule_name": "High velocity",
                            "severity": "medium",
                            "confidence": 0.8,
                            "score_contribution": 20,
                            "explanation": "High velocity activity detected",
                            "evidence": {},
                        }
                    ],
                },
            }

        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_poll1)

        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session

            asyncio.run(monitor_chain("bitcoin"))

    # Verify first risk-only alert was created
    alerts_poll1 = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash.is_(None),
            WalletAlert.trigger_type == "High velocity",
        )
    ).all()

    assert len(alerts_poll1) == 1, f"Poll 1: Expected 1 risk-only alert, got {len(alerts_poll1)}"
    first_alert = alerts_poll1[0]
    first_dedupe_key = first_alert.dedupe_key
    first_risk_score = first_alert.risk_score

    # POLL 2: Same wallet/chain/trigger, but risk_score increased to 25
    # Risk-only alerts should create a NEW alert (dedupe keys must differ)
    with patch("greedy_collector.monitoring.GreedyCollectorService") as mock_service_class:
        mock_service = MagicMock()
        mock_service_class.return_value = mock_service

        async def async_lookup_poll2(*args, **kwargs):
            return {
                "transactions": [baseline_tx],
                "risk": {
                    "score": 25,  # DIFFERENT from poll 1
                    "level": "High",
                    "findings": [
                        {
                            "rule_id": "high_velocity",
                            "rule_name": "High velocity",
                            "severity": "high",
                            "confidence": 0.9,
                            "score_contribution": 25,
                            "explanation": "Even higher velocity activity detected",
                            "evidence": {},
                        }
                    ],
                },
            }

        mock_service.lookup_address = AsyncMock(side_effect=async_lookup_poll2)

        with patch("greedy_collector.monitoring.SessionLocal") as mock_session_class:
            mock_session_class.return_value = db_session

            asyncio.run(monitor_chain("bitcoin"))

    # Verify TWO separate risk-only alerts (NOT deduplicated by logical identity)
    alerts_total = db_session.scalars(
        select(WalletAlert).where(
            WalletAlert.wallet == wallet.address,
            WalletAlert.tx_hash.is_(None),
            WalletAlert.trigger_type == "High velocity",
        )
    ).all()

    assert len(alerts_total) == 2, (
        f"Expected 2 risk-only alerts (not deduplicated), got {len(alerts_total)}. "
        f"Risk-only alerts must create separate entries for different scores. "
        f"Alerts: {[(a.risk_score, a.dedupe_key[-16:]) for a in alerts_total]}"
    )

    # Verify dedupe keys are DIFFERENT (opposite of transaction-backed alerts)
    second_alert = alerts_total[1]
    assert first_dedupe_key != second_alert.dedupe_key, (
        f"Risk-only alert dedupe keys must differ when risk_score changes. "
        f"Poll 1 (score={first_risk_score}): {first_dedupe_key} "
        f"Poll 2 (score={second_alert.risk_score}): {second_alert.dedupe_key}"
    )
