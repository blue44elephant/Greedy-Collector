"""Comprehensive tests for Ethereum transaction-history pagination."""

import pytest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, patch

from greedy_collector.chains.ethereum import EthereumAdapter
from greedy_collector.chains.base import ChainDataError

# Mark all tests in this module as async
pytestmark = pytest.mark.asyncio


@pytest.fixture
def ethereum_adapter():
    """Create a test Ethereum adapter with mocked settings."""
    adapter = EthereumAdapter()
    adapter.settings.etherscan_api_key = "test_key"
    adapter.settings.alchemy_api_key = "test_alchemy_key"
    return adapter


@pytest.fixture
def valid_address():
    """A valid Ethereum address for testing."""
    return "0x1234567890123456789012345678901234567890"


def make_tx_row(tx_id: int, timestamp: int = 1695000000, tx_type: str = "normal") -> dict:
    """Factory function to create mock transaction rows."""
    focus_addr = "0x1234567890123456789012345678901234567890"
    # Generate unique hash for each tx_id (pad to 64 hex digits)
    hex_id = format(tx_id, '064x')
    if tx_type == "normal":
        return {
            "hash": f"0x{hex_id}",  # Unique hash per tx
            "from": focus_addr if tx_id % 2 == 0 else "0x9999999999999999999999999999999999999999",
            "to": "0x8888888888888888888888888888888888888888",
            "value": "1000000000000000000",  # 1 ETH in Wei
            "gas": "21000",
            "gasPrice": "50000000000",
            "gasUsed": "21000",
            "timeStamp": str(timestamp + tx_id),
            "blockNumber": str(17000000 + tx_id),
        }
    else:  # token
        # Use different prefix for token hashes to avoid collision with normal tx hashes
        hex_id = format(100000 + tx_id, '064x')
        return {
            "hash": f"0x{hex_id}",  # Unique hash per tx
            "from": focus_addr if tx_id % 2 == 0 else "0x7777777777777777777777777777777777777777",
            "to": "0x6666666666666666666666666666666666666666",
            "value": "1000000000000000000",  # Token amount
            "tokenSymbol": "USDC",
            "tokenDecimal": "6",
            "timeStamp": str(timestamp + 500000 + tx_id),  # Different timestamp range
            "blockNumber": str(17000000 + tx_id),
        }


class TestEthereumPaginationShortFirstPage:
    """Test: Page 1 returns 25 rows, page 2 never requested."""

    async def test_short_first_page_stops_pagination(self, ethereum_adapter, valid_address):
        """First page has fewer than 1000 rows, pagination stops."""
        # Page 1 returns only 25 rows
        page1_response = {
            "status": "1",
            "message": "OK",
            "result": [make_tx_row(i) for i in range(25)],
        }

        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            # Track call count
            call_count = [0]
            
            async def side_effect(params):
                call_count[0] += 1
                page = params.get('page', 1)
                action = params.get('action', '')
                
                if page == 1 and action == "txlist":
                    return page1_response
                elif page == 1 and action == "tokentx":
                    return {"status": "1", "message": "OK", "result": []}
                else:
                    # Page 2 should never be requested
                    pytest.fail(f"Unexpected page request: action={action}, page={page}")
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have 25 normalized transactions
            assert len(result) == 25
            # Verify call_count was exactly 2 (one for txlist page 1, one for tokentx page 1)
            assert call_count[0] == 2


class TestEthereumPaginationMultiplePages:
    """Test: Pagination across multiple pages."""

    async def test_multiple_pages_aggregation(self, ethereum_adapter, valid_address):
        """Page 1 → 1000, Page 2 → 1000, Page 3 → 20, total = 2020."""
        page_responses = {
            "txlist": {
                1: {"status": "1", "message": "OK", "result": [make_tx_row(i) for i in range(1000)]},
                2: {"status": "1", "message": "OK", "result": [make_tx_row(1000 + i) for i in range(1000)]},
                3: {"status": "1", "message": "OK", "result": [make_tx_row(2000 + i) for i in range(20)]},
            },
            "tokentx": {
                1: {"status": "1", "message": "OK", "result": []},
            },
        }

        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            call_log = []
            
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                call_log.append((action, page))
                
                if action == "txlist" and page in page_responses["txlist"]:
                    return page_responses["txlist"][page]
                elif action == "tokentx" and page in page_responses["tokentx"]:
                    return page_responses["tokentx"][page]
                else:
                    return {"status": "1", "message": "OK", "result": []}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have 2020 transactions (1000 + 1000 + 20)
            assert len(result) == 2020
            
            # Verify we requested all three pages for txlist
            txlist_calls = [page for action, page in call_log if action == "txlist"]
            assert txlist_calls == [1, 2, 3]


class TestEthereumPaginationExactBoundary:
    """Test: Exact boundary - page 1 has exactly 1000, page 2 is empty."""

    async def test_exact_boundary_stops_cleanly(self, ethereum_adapter, valid_address):
        """Page 1 returns exactly 1000, page 2 is empty, stops cleanly."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            call_log = []
            
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                call_log.append((action, page))
                
                if page == 1 and action == "txlist":
                    return {"status": "1", "message": "OK", "result": [make_tx_row(i) for i in range(1000)]}
                elif page == 2 and action == "txlist":
                    return {"status": "1", "message": "OK", "result": []}
                elif action == "tokentx":
                    return {"status": "1", "message": "OK", "result": []}
                else:
                    pytest.fail(f"Unexpected request: action={action}, page={page}")
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have exactly 1000 transactions
            assert len(result) == 1000
            
            # Verify we requested page 2 and stopped (empty response ends pagination)
            txlist_calls = [page for action, page in call_log if action == "txlist"]
            assert txlist_calls == [1, 2]


class TestEthereumPaginationIndependent:
    """Test: txlist and tokentx paginate independently."""

    async def test_independent_pagination_different_pages(self, ethereum_adapter, valid_address):
        """txlist spans 3 pages, tokentx spans 2 pages."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            call_log = []
            
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                call_log.append((action, page))
                
                if action == "txlist":
                    if page == 1:
                        return {"status": "1", "message": "OK", "result": [make_tx_row(i) for i in range(1000)]}
                    elif page == 2:
                        return {"status": "1", "message": "OK", "result": [make_tx_row(1000 + i) for i in range(1000)]}
                    elif page == 3:
                        return {"status": "1", "message": "OK", "result": [make_tx_row(2000 + i) for i in range(50)]}
                    else:
                        return {"status": "1", "message": "OK", "result": []}
                elif action == "tokentx":
                    if page == 1:
                        return {"status": "1", "message": "OK", "result": [make_tx_row(i, tx_type="token") for i in range(1000)]}
                    elif page == 2:
                        return {"status": "1", "message": "OK", "result": [make_tx_row(1000 + i, tx_type="token") for i in range(100)]}
                    else:
                        return {"status": "1", "message": "OK", "result": []}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have 3150 total (2050 normal + 1100 token)
            assert len(result) == 3150
            
            # Verify both actions paginated independently
            txlist_calls = [page for action, page in call_log if action == "txlist"]
            tokentx_calls = [page for action, page in call_log if action == "tokentx"]
            
            assert txlist_calls == [1, 2, 3]
            assert tokentx_calls == [1, 2]


class TestEthereumPaginationGlobalOrdering:
    """Test: Global ordering by timestamp across pages and transaction types."""

    async def test_global_ordering_newest_first(self, ethereum_adapter, valid_address):
        """Transactions are globally sorted newest-first and pagination continues across pages."""
        now = 1700000000
        
        # Create pages: page 1 has 1000 rows, page 2 has 500 (triggers continuation)
        page1_normal = [make_tx_row(i, now + (2000 - i), "normal") for i in range(1000)]
        page2_normal = [make_tx_row(1000 + i, now + (1000 - i), "normal") for i in range(500)]
        
        # Token transactions: page 1 has 1000, page 2 has 200 to trigger pagination
        page1_token = [make_tx_row(10000 + i, now + (1500 - i), "token") for i in range(1000)]
        page2_token = [make_tx_row(11000 + i, now + (800 - i), "token") for i in range(200)]
        
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            call_log = []
            
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                call_log.append((action, page))
                
                if action == "txlist":
                    if page == 1:
                        return {"status": "1", "message": "OK", "result": page1_normal}
                    elif page == 2:
                        return {"status": "1", "message": "OK", "result": page2_normal}
                    else:
                        return {"status": "1", "message": "OK", "result": []}
                elif action == "tokentx":
                    if page == 1:
                        return {"status": "1", "message": "OK", "result": page1_token}
                    elif page == 2:
                        return {"status": "1", "message": "OK", "result": page2_token}
                    else:
                        return {"status": "1", "message": "OK", "result": []}
                else:
                    return {"status": "1", "message": "OK", "result": []}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Verify pagination occurred (page 2 was requested for both)
            txlist_pages = [page for action, page in call_log if action == "txlist"]
            tokentx_pages = [page for action, page in call_log if action == "tokentx"]
            assert 2 in txlist_pages, "Should have requested page 2 for txlist"
            assert 2 in tokentx_pages, "Should have requested page 2 for tokentx"
            
            # Total: 1000 + 500 + 1000 + 200 = 2700
            assert len(result) == 2700, f"Expected 2700 transactions but got {len(result)}"
            
            # Verify global descending order by timestamp
            timestamps = [tx.timestamp.timestamp() if tx.timestamp else 0 for tx in result]
            expected_order = sorted(timestamps, reverse=True)
            assert timestamps == expected_order, "Transactions should be ordered newest-first"


class TestEthereumPaginationLaterPageFailure:
    """Test: Page 1 succeeds, later page fails - returns explicitly partial data."""

    async def test_later_page_failure_preserves_partial_history(self, ethereum_adapter, valid_address):
        """Page 1 survives page 2 failure with explicit partial status."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                
                if action == "txlist":
                    if page == 1:
                        return {"status": "1", "message": "OK", "result": [make_tx_row(i) for i in range(1000)]}
                    elif page == 2:
                        # Simulate page 2 failure
                        raise ChainDataError("Etherscan API quota exceeded on page 2")
                elif action == "tokentx":
                    return {"status": "1", "message": "OK", "result": []}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            assert len(result) == 1000
            assert ethereum_adapter.collection_streams["txlist"]["status"] == "PARTIAL"
            assert ethereum_adapter.collection_streams["tokentx"]["status"] == "COMPLETE_WITHIN_REQUESTED_BOUND"



class TestEthereumPaginationSafetyCap:
    """Test: Safety cap - max 10 pages (10,000 records)."""

    async def test_safety_cap_stops_at_10_pages(self, ethereum_adapter, valid_address):
        """Each page returns 1000 unique rows, verify exactly 10 pages requested, no page 11."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            call_log = []
            
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                call_log.append((action, page))
                
                if action == "txlist" and page <= 10:
                    # Return full 1000 rows for each page with unique IDs
                    start_id = (page - 1) * 1000
                    return {"status": "1", "message": "OK", "result": [make_tx_row(start_id + i) for i in range(1000)]}
                elif action == "tokentx":
                    return {"status": "1", "message": "OK", "result": []}
                else:
                    pytest.fail(f"Should not request page {page} (exceeds safety cap of 10)")
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have 10,000 transactions (10 pages × 1000)
            assert len(result) == 10000
            
            # Verify exactly 10 pages requested for txlist, no page 11
            txlist_calls = [page for action, page in call_log if action == "txlist"]
            assert txlist_calls == list(range(1, 11))
            assert max(txlist_calls) == 10


class TestEthereumPaginationEmptyHistory:
    """Test: Legitimate empty history - valid no-transactions response."""

    async def test_empty_history_no_error(self, ethereum_adapter, valid_address):
        """Valid empty response returns empty history without error."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            async def side_effect(*args, **kwargs):
                params = kwargs.get('params', {})
                action = params.get('action', '')
                
                # Both txlist and tokentx return "No transactions found"
                return {"status": "1", "message": "No transactions found", "result": "No transactions found"}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have empty list
            assert len(result) == 0
            assert isinstance(result, list)


class TestEthereumPaginationDeduplication:
    """Test: Deduplication across pages and transaction types."""

    async def test_deduplication_across_pages(self, ethereum_adapter, valid_address):
        """Duplicate transactions across pages are deduplicated."""
        # Create identical transaction in both pages
        duplicate_tx = make_tx_row(1, 1695000000, "normal")
        
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                
                if action == "txlist" and page == 1:
                    # Include duplicate_tx in page 1
                    return {"status": "1", "message": "OK", "result": [duplicate_tx, make_tx_row(2)]}
                elif action == "txlist" and page == 2:
                    # Include duplicate_tx again in page 2
                    return {"status": "1", "message": "OK", "result": [duplicate_tx]}
                elif action == "tokentx":
                    return {"status": "1", "message": "OK", "result": []}
                else:
                    return {"status": "1", "message": "OK", "result": []}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Should have 2 transactions (duplicate removed)
            assert len(result) == 2
            
            # Verify only one instance of the duplicate hash exists
            hashes = [tx.tx_hash for tx in result]
            assert len(set(hashes)) == 2  # Two unique hashes


class TestEthereumPaginationConcurrency:
    """Test: txlist and tokentx are fetched concurrently."""

    async def test_concurrent_pagination(self, ethereum_adapter, valid_address):
        """Both actions are fetched concurrently (asyncio.gather)."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            # Both will be called, order not guaranteed due to concurrency
            call_order = []
            
            async def side_effect(params):
                action = params.get('action', '')
                page = params.get('page', 1)
                
                call_order.append(action)
                
                if action == "txlist" and page == 1:
                    return {"status": "1", "message": "OK", "result": [make_tx_row(i) for i in range(100)]}
                elif action == "tokentx" and page == 1:
                    return {"status": "1", "message": "OK", "result": [make_tx_row(i, tx_type="token") for i in range(50)]}
                else:
                    return {"status": "1", "message": "OK", "result": []}
            
            mock_eth.side_effect = side_effect
            
            result = await ethereum_adapter.transactions(valid_address)
            
            # Both actions were called at least once
            assert "txlist" in call_order
            assert "tokentx" in call_order
            # Total should be 150 (100 + 50)
            assert len(result) == 150
