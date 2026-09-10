"""Comprehensive tests for Bitcoin transaction-history pagination."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch, MagicMock

from greedy_collector.chains.bitcoin import BitcoinAdapter
from greedy_collector.chains.base import ChainDataError

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


@pytest.fixture
def bitcoin_adapter():
    """Create a test Bitcoin adapter."""
    return BitcoinAdapter()


@pytest.fixture
def valid_address():
    """A valid Bitcoin address for testing."""
    return "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa"  # Genesis block address


def make_tx_row(
    tx_id: int,
    timestamp: int | None = 1695000000,
    is_confirmed: bool = True,
    block_height: int | None = None,
) -> dict:
    """
    Factory function to create mock Bitcoin transaction rows (Esplora format).
    
    Args:
        tx_id: Unique transaction ID for hash generation
        timestamp: Unix timestamp (None for mempool/unconfirmed)
        is_confirmed: Whether transaction is confirmed
        block_height: Block height (None for mempool)
    """
    # Generate unique txid
    txid = format(tx_id, '064x')
    
    status = {"confirmed": is_confirmed}
    if timestamp:
        status["block_time"] = timestamp + tx_id
    if block_height is not None:
        status["block_height"] = block_height
    
    return {
        "txid": txid,
        "vin": [
            {
                "prevout": {
                    "scriptpubkey_address": "1A1zP1eP5QGefi2DMPTfTL5SLmv7DivfNa",
                    "value": 50000000000,  # 500 BTC in satoshis
                }
            }
        ],
        "vout": [
            {
                "scriptpubkey_address": "1dice8EMCmnqBTS6omRS4iGD466V8i5KF",
                "value": 49999500000,  # 499.99 BTC in satoshis
            }
        ],
        "status": status,
    }


class TestBitcoinPaginationSmallHistory:
    """Test A: Small history with fewer than 25 confirmed transactions."""

    async def test_small_history_no_pagination(self, bitcoin_adapter, valid_address):
        """Initial response has several mempool + 10 confirmed, no chain request."""
        # Create initial response: 5 mempool + 10 confirmed
        mempool_txs = [make_tx_row(i, is_confirmed=False, timestamp=None) for i in range(5)]
        confirmed_txs = [
            make_tx_row(100 + i, timestamp=1695000000, is_confirmed=True, block_height=800000 + i)
            for i in range(10)
        ]
        initial_response = mempool_txs + confirmed_txs

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                if "/txs/chain/" in path:
                    # Should not be called
                    pytest.fail(f"Unexpected chain request: {path}")
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 15 transactions (5 mempool + 10 confirmed)
            assert len(result) == 15
            # After fix: unconfirmed (mempool) come FIRST, then confirmed sorted by timestamp DESC
            confirmed_results = [tx for tx in result if tx.timestamp is not None]
            mempool_results = [tx for tx in result if tx.timestamp is None]
            assert len(confirmed_results) == 10
            assert len(mempool_results) == 5
            # Mempool should be at the BEGINNING (to be detected before previous_tx break point)
            assert all(tx.timestamp is None for tx in result[:5])


class TestBitcoinPaginationExactBoundary:
    """Test B: Exactly 25 confirmed on first page, then empty chain page."""

    async def test_exact_25_confirmed_stops_cleanly(self, bitcoin_adapter, valid_address):
        """Initial page has exactly 25 confirmed, chain returns empty."""
        # Initial: 25 confirmed (no mempool for simplicity)
        initial_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]

        call_log = []

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                call_log.append(path)
                if "/txs/chain/" in path:
                    # Second page should be requested and return empty
                    return []
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 25 transactions
            assert len(result) == 25
            # Verify exactly one chain request was made
            chain_requests = [path for path in call_log if "/txs/chain/" in path]
            assert len(chain_requests) == 1


class TestBitcoinPaginationMultipleConfirmedPages:
    """Test C: Multiple confirmed pages with partial last page."""

    async def test_multiple_confirmed_pages(self, bitcoin_adapter, valid_address):
        """Pagination: initial 25 confirmed, then 25, then 10."""
        # Simulate 3 pages: 25, 25, 10 confirmed
        initial_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]
        
        page2_response = [
            make_tx_row(100 + i, timestamp=1694000000 + i, is_confirmed=True, block_height=799000 + i)
            for i in range(25)
        ]
        
        page3_response = [
            make_tx_row(200 + i, timestamp=1693000000 + i, is_confirmed=True, block_height=798000 + i)
            for i in range(10)
        ]

        call_log = []
        page_count = [0]

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                call_log.append(path)
                if "/txs/chain/" in path:
                    page_count[0] += 1
                    if page_count[0] == 1:
                        return page2_response
                    elif page_count[0] == 2:
                        return page3_response
                    else:
                        return []
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 60 transactions total (25 + 25 + 10)
            assert len(result) == 60
            # Verify exactly 2 chain requests were made
            chain_requests = [path for path in call_log if "/txs/chain/" in path]
            assert len(chain_requests) == 2


class TestBitcoinPaginationMixedMempoolConfirmed:
    """Test D: Mixed mempool + confirmed, cursor uses confirmed only."""

    async def test_cursor_uses_confirmed_not_mempool(self, bitcoin_adapter, valid_address):
        """Mempool txs in initial page, cursor is last confirmed, not last overall."""
        # Initial: 5 mempool + 25 confirmed
        mempool_txs = [make_tx_row(i, is_confirmed=False, timestamp=None) for i in range(5)]
        confirmed_txs = [
            make_tx_row(100 + i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]
        initial_response = confirmed_txs + mempool_txs  # Confirmed first, then mempool in initial

        page2_response = [
            make_tx_row(200 + i, timestamp=1694000000 + i, is_confirmed=True, block_height=799000 + i)
            for i in range(10)
        ]

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                if "/txs/chain/" in path:
                    # Cursor should be the last confirmed txid (index 124)
                    expected_cursor = format(124, '064x')
                    assert expected_cursor in path, f"Expected cursor {expected_cursor} in {path}"
                    return page2_response
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # 25 confirmed + 10 confirmed + 5 mempool = 40
            assert len(result) == 40
            # Verify mempool results exist
            mempool_results = [tx for tx in result if tx.timestamp is None]
            assert len(mempool_results) == 5


class TestBitcoinPaginationMempoolOnly:
    """Test E: Address has only mempool transactions, no confirmed."""

    async def test_mempool_only_no_chain_request(self, bitcoin_adapter, valid_address):
        """Initial page has only mempool, no chain pagination attempted."""
        initial_response = [
            make_tx_row(i, is_confirmed=False, timestamp=None) for i in range(10)
        ]

        call_log = []

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                call_log.append(path)
                if "/txs/chain/" in path:
                    pytest.fail("Should not request chain pagination for mempool-only address")
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 10 mempool transactions
            assert len(result) == 10
            # Verify no chain requests
            chain_requests = [path for path in call_log if "/txs/chain/" in path]
            assert len(chain_requests) == 0


class TestBitcoinPaginationBlockstreamInitialFailure:
    """Test F: Blockstream initial request fails, fallback to Mempool succeeds."""

    async def test_blockstream_failure_mempool_fallback(self, bitcoin_adapter, valid_address):
        """Blockstream initial fails, Mempool completes successfully."""
        mempool_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(15)
        ]

        with patch.object(bitcoin_adapter, "_transactions_from_provider", new_callable=AsyncMock) as mock_paginate:
            async def side_effect(base_url, provider_name, address):
                if "blockstream" in base_url:
                    raise ChainDataError("Blockstream connection failed")
                elif "mempool" in base_url:
                    return mempool_response
                else:
                    raise ChainDataError("Unknown provider")

            mock_paginate.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 15 transactions from Mempool
            assert len(result) == 15
            # Verify all come from Mempool
            assert all(tx.source_api == "mempool_space" for tx in result)


class TestBitcoinPaginationBlockstreamLaterPageFailure:
    """Test G: Blockstream succeeds initially, fails on later page, fallback to Mempool."""

    async def test_blockstream_later_page_failure_discard_restart(self, bitcoin_adapter, valid_address):
        """Blockstream pages 1-2 OK, page 3 fails, discard ALL and retry Mempool."""
        blockstream_initial = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]
        blockstream_page2 = [
            make_tx_row(100 + i, timestamp=1694000000 + i, is_confirmed=True, block_height=799000 + i)
            for i in range(25)
        ]

        mempool_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(20)
        ]

        call_log = []

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                call_log.append((base_url, path))
                
                if "blockstream" in base_url:
                    if "/txs/chain/" in path:
                        # Check if this is page 2 or later
                        if "0000000000000000000000000000000000000000000000000000000000000018" in path:
                            # Page 2 request from Blockstream - fail
                            raise ChainDataError("Blockstream connection lost on page 2")
                    elif "/txs" in path:
                        return blockstream_initial
                elif "mempool" in base_url:
                    if "/txs" in path and "/chain/" not in path:
                        return mempool_response
                
                raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 20 transactions from Mempool (NOT 25+25=50 from Blockstream partial)
            assert len(result) == 20
            # Verify all come from Mempool
            assert all(tx.source_api == "mempool_space" for tx in result)


class TestBitcoinPaginationBothProvidersFail:
    """Test H: Both Blockstream and Mempool fail."""

    async def test_both_providers_fail(self, bitcoin_adapter, valid_address):
        """Both providers fail at initial request."""
        with patch.object(bitcoin_adapter, "_transactions_from_provider", new_callable=AsyncMock) as mock_paginate:
            async def side_effect(base_url, provider_name, address):
                raise ChainDataError(f"{provider_name} unavailable")

            mock_paginate.side_effect = side_effect

            with pytest.raises(ChainDataError) as exc_info:
                await bitcoin_adapter.transactions(valid_address)
            
            # Should raise error from last provider
            assert "mempool_space" in str(exc_info.value)


class TestBitcoinPaginationSafetyCap:
    """Test I: Safety cap enforcement (max 500 confirmed records)."""

    async def test_safety_cap_500_confirmed(self, bitcoin_adapter, valid_address):
        """Pagination stops at 500 confirmed records."""
        # Create pages of 25 confirmed each
        # 500 records / 25 per page = 20 pages needed
        # But we should stop at 20 pages (500 confirmed)
        pages = []
        for page_num in range(21):
            start_id = page_num * 25
            page = [
                make_tx_row(
                    start_id + i,
                    timestamp=1695000000 - page_num * 1000 + i,
                    is_confirmed=True,
                    block_height=800000 - page_num + i,
                )
                for i in range(25)
            ]
            pages.append(page)

        initial_response = pages[0]
        page_index = [0]

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                if "/txs/chain/" in path:
                    page_index[0] += 1
                    if page_index[0] < len(pages):
                        return pages[page_index[0]]
                    else:
                        return []
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have exactly 500 confirmed records (safety cap)
            confirmed_results = [tx for tx in result if tx.timestamp is not None]
            assert len(confirmed_results) == 500
            
            # Verify no more than 20 pages total (1 initial + 19 chain)
            # Since each page has 25, 20 pages * 25 = 500
            assert page_index[0] <= 19  # page_index counts chain pages only


class TestBitcoinPaginationCursorStagnation:
    """Test J: Cursor stagnation detection (provider returns same page repeatedly)."""

    async def test_cursor_stagnation_raises_error(self, bitcoin_adapter, valid_address):
        """Provider returns same cursor, indicates no progress."""
        initial_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]

        # Stagnant page (same txids as initial)
        stagnant_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                if "/txs/chain/" in path:
                    # Return stagnant page (same as initial, not progressing)
                    return stagnant_response
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            with pytest.raises(ChainDataError) as exc_info:
                await bitcoin_adapter.transactions(valid_address)
            
            assert "cursor stagnation" in str(exc_info.value).lower()


class TestBitcoinPaginationDeduplication:
    """Test K: Deduplication of overlapping records."""

    async def test_deduplication_overlapping_records(self, bitcoin_adapter, valid_address):
        """Duplicate records across pages are deduplicated."""
        # Initial page with 25 confirmed
        initial_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(25)
        ]

        # Second page has 1 duplicate (last from initial) + 2 new
        page2_response = [
            make_tx_row(24, timestamp=1695000024, is_confirmed=True, block_height=800024),  # Duplicate
            make_tx_row(100, timestamp=1694000000, is_confirmed=True, block_height=799000),
            make_tx_row(101, timestamp=1694000001, is_confirmed=True, block_height=799001),
        ]

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                if "/txs/chain/" in path:
                    return page2_response
                elif "/txs" in path:
                    return initial_response
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should be 27 unique (25 from initial + 2 new from page2, 1 duplicate removed)
            # 25 + 3 - 1 = 27
            assert len(result) == 27


class TestBitcoinPaginationOrdering:
    """Test L: Final result ordering is newest-first."""

    async def test_result_ordering_newest_first(self, bitcoin_adapter, valid_address):
        """Final normalized results are ordered newest-first by timestamp."""
        # Mix timestamps across pages
        mempool_txs = [
            make_tx_row(0, is_confirmed=False, timestamp=None),
            make_tx_row(1, is_confirmed=False, timestamp=None),
        ]
        
        page1_txs = [
            make_tx_row(100, timestamp=1695000000, is_confirmed=True, block_height=800000),
            make_tx_row(101, timestamp=1695000001, is_confirmed=True, block_height=800001),
            make_tx_row(102, timestamp=1695000002, is_confirmed=True, block_height=800002),
            # ... continue to 25 txs
        ] + [
            make_tx_row(103 + i, timestamp=1695000003 + i, is_confirmed=True, block_height=800003 + i)
            for i in range(22)
        ]

        page2_txs = [
            make_tx_row(200 + i, timestamp=1694000000 + i, is_confirmed=True, block_height=799000 + i)
            for i in range(10)
        ]

        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                if "/txs/chain/" in path:
                    return page2_txs
                elif "/txs" in path:
                    return mempool_txs + page1_txs
                else:
                    raise ChainDataError("Unexpected path")

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Check ordering: confirmed newest first, then unconfirmed last
            # Get timestamps (treating None as minimum)
            timestamps = []
            for tx in result:
                if tx.timestamp:
                    timestamps.append(tx.timestamp.timestamp())
                else:
                    timestamps.append(-1)  # Mempool at end
            
            # Should be descending (with mempool at end)
            for i in range(len(timestamps) - 1):
                if timestamps[i] > 0 and timestamps[i + 1] > 0:
                    # Both confirmed, should be descending
                    assert timestamps[i] >= timestamps[i + 1], f"Not sorted at index {i}: {timestamps[i]} > {timestamps[i+1]}"


class TestBitcoinPaginationPrimaryProvider:
    """Test M: Blockstream remains primary provider when successful."""

    async def test_blockstream_primary_not_fallback(self, bitcoin_adapter, valid_address):
        """Blockstream is tried first and Mempool is not called if successful."""
        blockstream_response = [
            make_tx_row(i, timestamp=1695000000 + i, is_confirmed=True, block_height=800000 + i)
            for i in range(15)
        ]

        provider_calls = []

        with patch.object(bitcoin_adapter, "_transactions_from_provider", new_callable=AsyncMock) as mock_paginate:
            async def side_effect(base_url, provider_name, address):
                provider_calls.append(provider_name)
                if "blockstream" in base_url:
                    return blockstream_response
                else:
                    pytest.fail("Mempool should not be called if Blockstream succeeds")

            mock_paginate.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            # Should have 15 transactions from Blockstream
            assert len(result) == 15
            # Verify only Blockstream was called
            assert provider_calls == ["blockstream"]
            # Verify all transactions have blockstream source
            assert all(tx.source_api == "blockstream" for tx in result)


class TestBitcoinPaginationEmptyAddress:
    """Test: Address with no transactions at all."""

    async def test_empty_address_history(self, bitcoin_adapter, valid_address):
        """Address with no transactions returns empty list."""
        with patch.object(bitcoin_adapter, "_fetch_from_provider", new_callable=AsyncMock) as mock_fetch:
            async def side_effect(base_url, path):
                return []

            mock_fetch.side_effect = side_effect

            result = await bitcoin_adapter.transactions(valid_address)

            assert len(result) == 0
