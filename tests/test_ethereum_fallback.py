"""Tests for Ethereum adapter with Alchemy fallback support.

These tests verify that:
1. Etherscan is tried first and succeeds when available
2. Alchemy fallback is triggered only on Etherscan errors
3. Zero balance from Etherscan is treated as valid success (no fallback)
4. Both provider failures result in a combined error
5. Various error conditions trigger appropriate fallback behavior
"""

import pytest
import asyncio
import json
import traceback
import httpx
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

from greedy_collector.chains.ethereum import EthereumAdapter, ChainDataError

# Enable asyncio mode for this test module
pytestmark = pytest.mark.asyncio


@pytest.fixture
def ethereum_adapter():
    """Create an EthereumAdapter instance for testing."""
    adapter = EthereumAdapter()
    # Mock settings to have valid API keys for fallback tests
    adapter.settings.etherscan_api_key = "test_etherscan_key"
    adapter.settings.alchemy_api_key = "test_alchemy_key"
    return adapter


@pytest.fixture
def valid_address():
    """A valid Ethereum address for testing."""
    return "0x1234567890123456789012345678901234567890"


@pytest.fixture
def hex_balance_1_eth():
    """1 ETH in hex Wei format (as returned by Alchemy)."""
    # 1 ETH = 10^18 Wei = 0xde0b6b3a7640000
    return "0xde0b6b3a7640000"


@pytest.fixture
def hex_balance_5_eth():
    """5 ETH in hex Wei format."""
    # 5 ETH = 5 * 10^18 Wei
    return "0x4b3b4ca85a86c47a00000"


@pytest.fixture
def etherscan_response_1_eth():
    """Etherscan response for 1 ETH balance."""
    return {
        "status": "1",
        "message": "OK",
        "result": "1000000000000000000",  # Decimal Wei as string
    }


@pytest.fixture
def etherscan_response_zero_balance():
    """Etherscan response for zero balance."""
    return {
        "status": "1",
        "message": "OK",
        "result": "0",
    }


@pytest.fixture
def alchemy_response_1_eth():
    """Alchemy JSON-RPC response for 1 ETH balance."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": "0xde0b6b3a7640000",  # Hex Wei
    }


@pytest.fixture
def alchemy_response_zero_balance():
    """Alchemy JSON-RPC response for zero balance."""
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": "0x0",
    }


class TestEthereumEtherscanSuccess:
    """Test A: Etherscan succeeds - Alchemy should not be called."""

    async def test_etherscan_returns_balance(self, ethereum_adapter, valid_address, etherscan_response_1_eth):
        """Etherscan returns valid balance, Alchemy not called."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.return_value = etherscan_response_1_eth
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy") as mock_alchemy:
                result = await ethereum_adapter.lookup_address(valid_address)
                
                # Verify result
                assert result["chain"] == "ethereum"
                assert result["address"] == valid_address
                # Decimal("1000000000000000000") / 10^18 = Decimal("1")
                assert result["balance_native"] == "1"
                assert result["source_api"] == "etherscan"
                
                # Verify Alchemy was never called
                mock_alchemy.assert_not_called()

    async def test_etherscan_success_with_different_balance(self, ethereum_adapter, valid_address):
        """Etherscan returns different balance value."""
        response = {
            "status": "1",
            "message": "OK",
            "result": "2500000000000000000",  # 2.5 ETH
        }
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.return_value = response
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy") as mock_alchemy:
                result = await ethereum_adapter.lookup_address(valid_address)
                
                # Decimal("2500000000000000000") / 10^18 = Decimal("2.5")
                assert result["balance_native"] == "2.5"
                assert result["source_api"] == "etherscan"
                mock_alchemy.assert_not_called()


class TestEthereumEtherscanFailureAlchemySuccess:
    """Test B: Etherscan fails, Alchemy succeeds - fallback should succeed."""

    async def test_etherscan_error_triggers_alchemy_fallback(
        self, ethereum_adapter, valid_address, alchemy_response_1_eth
    ):
        """Etherscan raises error, Alchemy fallback succeeds."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan API quota exceeded")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = alchemy_response_1_eth
                
                result = await ethereum_adapter.lookup_address(valid_address)
                
                # Verify fallback succeeded with Alchemy data
                assert result["chain"] == "ethereum"
                assert result["address"] == valid_address
                assert result["balance_native"] == "1"  # hex 0xde0b6b3a7640000 = 10^18 Wei = 1 ETH
                assert result["source_api"] == "alchemy"
                
                # Verify Etherscan was called first
                mock_eth.assert_called_once()

    async def test_etherscan_http_429_triggers_alchemy_fallback(
        self, ethereum_adapter, valid_address, alchemy_response_1_eth
    ):
        """Etherscan returns HTTP 429 rate limit, Alchemy succeeds."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("ethereum source request failed: HTTP 429")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = alchemy_response_1_eth
                
                result = await ethereum_adapter.lookup_address(valid_address)
                
                assert result["source_api"] == "alchemy"
                assert result["balance_native"] == "1"

    async def test_etherscan_timeout_triggers_alchemy_fallback(
        self, ethereum_adapter, valid_address, alchemy_response_1_eth
    ):
        """Etherscan timeout, Alchemy succeeds."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("ethereum source request failed: TimeoutException")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = alchemy_response_1_eth
                
                result = await ethereum_adapter.lookup_address(valid_address)
                
                assert result["source_api"] == "alchemy"

    async def test_etherscan_500_error_triggers_alchemy_fallback(
        self, ethereum_adapter, valid_address, alchemy_response_1_eth
    ):
        """Etherscan returns HTTP 5xx, Alchemy succeeds."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("ethereum source request failed: HTTP 503")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = alchemy_response_1_eth
                
                result = await ethereum_adapter.lookup_address(valid_address)
                
                assert result["source_api"] == "alchemy"
                assert result["balance_native"] == "1"


class TestEthereumZeroBalance:
    """Test C: Zero balance from Etherscan is valid - no fallback."""

    async def test_zero_balance_from_etherscan_is_success(
        self, ethereum_adapter, valid_address, etherscan_response_zero_balance
    ):
        """Zero balance from Etherscan is treated as valid success."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.return_value = etherscan_response_zero_balance
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy") as mock_alchemy:
                result = await ethereum_adapter.lookup_address(valid_address)
                
                # Verify result is zero
                assert result["balance_native"] == "0"
                assert result["source_api"] == "etherscan"
                
                # Verify Alchemy was NOT called
                mock_alchemy.assert_not_called()


class TestEthereumBothProvidersFail:
    """Test E: Both Etherscan and Alchemy fail - error handling."""

    async def test_both_providers_fail_raises_combined_error(
        self, ethereum_adapter, valid_address
    ):
        """Both providers fail, error indicates both failed."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan API error")
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy", new_callable=AsyncMock) as mock_alchemy:
                mock_alchemy.side_effect = ChainDataError("Alchemy JSON-RPC error")
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                error_msg = str(exc_info.value)
                # Verify error message indicates both failed
                assert "Ethereum address lookup failed" in error_msg
                assert "Etherscan error" in error_msg
                assert "Alchemy fallback error" in error_msg
                # Verify API keys are not exposed
                assert "ETHERSCAN_API_KEY" not in error_msg
                assert "ALCHEMY_API_KEY" not in error_msg

    async def test_both_providers_fail_with_429_errors(self, ethereum_adapter, valid_address):
        """Both providers return rate limit errors."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan: HTTP 429 Too Many Requests")
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy", new_callable=AsyncMock) as mock_alchemy:
                mock_alchemy.side_effect = ChainDataError("Alchemy: HTTP 429 Too Many Requests")
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                error_msg = str(exc_info.value)
                assert "Etherscan error" in error_msg
                assert "Alchemy fallback error" in error_msg


class TestAlchemyInvalidResponse:
    """Test F: Invalid Alchemy response handling."""

    async def test_alchemy_json_rpc_error_response(self, ethereum_adapter, valid_address):
        """Alchemy returns JSON-RPC error object."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan failed")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "error": {
                        "code": -32600,
                        "message": "Invalid Request",
                    },
                }
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                assert "Alchemy returned error" in str(exc_info.value)
                assert "Invalid Request" in str(exc_info.value)

    async def test_alchemy_invalid_hex_balance(self, ethereum_adapter, valid_address):
        """Alchemy returns invalid hexadecimal balance."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan failed")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": "0xGGGGGG",  # Invalid hex
                }
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                assert "Invalid hex balance" in str(exc_info.value)

    async def test_alchemy_missing_result_field(self, ethereum_adapter, valid_address):
        """Alchemy response missing result field."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan failed")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    # Missing result field
                }
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                assert "missing result field" in str(exc_info.value)

    async def test_alchemy_result_wrong_type(self, ethereum_adapter, valid_address):
        """Alchemy returns result with wrong type (not string)."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan failed")
            
            with patch.object(ethereum_adapter, "_post", new_callable=AsyncMock) as mock_get:
                mock_get.return_value = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": 12345,  # Wrong type (int instead of string)
                }
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                assert "invalid type" in str(exc_info.value)


class TestEthereumAlchemyKeyMissing:
    """Test missing Alchemy API key handling."""

    async def test_fallback_with_missing_alchemy_key(
        self, ethereum_adapter, valid_address
    ):
        """Fallback to Alchemy when Etherscan fails but Alchemy key missing."""
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.side_effect = ChainDataError("Etherscan failed")
            
            # Mock settings to have no Alchemy key
            with patch.object(ethereum_adapter, "settings") as mock_settings:
                mock_settings.etherscan_api_key = "test_key"
                mock_settings.alchemy_api_key = ""  # Empty key
                
                with pytest.raises(ChainDataError) as exc_info:
                    await ethereum_adapter.lookup_address(valid_address)
                
                error_msg = str(exc_info.value)
                assert "ALCHEMY_API_KEY" in error_msg
                # Verify the key itself is not in the error
                assert "ALCHEMY_API_KEY=" not in error_msg


class TestEthereumAddressValidation:
    """Test address validation still works."""

    async def test_invalid_address_format_rejected(self, ethereum_adapter):
        """Invalid address format raises ValueError before provider call."""
        with patch.object(ethereum_adapter, "_etherscan") as mock_eth:
            with pytest.raises(ValueError):
                await ethereum_adapter.lookup_address("invalid_address")
            
            # Verify provider was never called
            mock_eth.assert_not_called()

    async def test_address_case_insensitive(
        self, ethereum_adapter, etherscan_response_1_eth
    ):
        """Address validation accepts mixed case."""
        # Use mixed case address (lowercase and uppercase letters)
        address_mixed = "0x1234567890aBcDeF1234567890aBcDeF12345678"  # Mixed case
        
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.return_value = etherscan_response_1_eth
            
            result = await ethereum_adapter.lookup_address(address_mixed)
            # Should accept mixed case and preserve it
            assert result["address"] == address_mixed


class TestTransactionHistoryUnchanged:
    """Verify that transactions() method was not affected by fallback changes."""

    async def test_transactions_still_use_etherscan_only(self, ethereum_adapter, valid_address):
        """transactions() method still uses Etherscan only, no fallback."""
        etherscan_response = {
            "status": "1",
            "message": "OK",
            "result": [
                {
                    "hash": "0xabc123",
                    "from": valid_address,
                    "to": "0x9999999999999999999999999999999999999999",
                    "value": "1000000000000000000",
                    "gas": "21000",
                    "gasPrice": "50000000000",
                    "gasUsed": "21000",
                    "timeStamp": "1695000000",
                    "blockNumber": "17000000",
                }
            ],
        }
        
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            # Mock both txlist and tokentx calls
            mock_eth.side_effect = [etherscan_response, {"status": "1", "message": "OK", "result": []}]
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy") as mock_alchemy:
                result = await ethereum_adapter.transactions(valid_address)
                
                # Should have one transaction
                assert len(result) == 1
                assert result[0].source_api == "etherscan"
                
                # Verify Alchemy fallback was NOT used
                mock_alchemy.assert_not_called()


class TestLookupTransactionUnchanged:
    """Verify that lookup_transaction() method was not affected."""

    async def test_lookup_transaction_still_uses_etherscan_only(self, ethereum_adapter):
        """lookup_transaction() method still uses Etherscan only."""
        tx_response = {
            "status": "1",
            "message": "OK",
            "result": {
                "hash": "0xabc123def456",
                "from": "0x1111111111111111111111111111111111111111",
                "to": "0x2222222222222222222222222222222222222222",
                "value": "0x0de0b6b3a7640000",
                "gas": "0x5208",
                "gasPrice": "0xba43b7400",
                "blockNumber": "0x1034d00",
                "gasUsed": "0x5208",
                "timeStamp": "1695000000",
            },
        }
        
        with patch.object(ethereum_adapter, "_etherscan", new_callable=AsyncMock) as mock_eth:
            mock_eth.return_value = tx_response
            
            with patch.object(ethereum_adapter, "_lookup_address_alchemy") as mock_alchemy:
                result = await ethereum_adapter.lookup_transaction("0x" + "a" * 64)
                
                assert result.source_api == "etherscan"
                mock_alchemy.assert_not_called()


@pytest.fixture
def alchemy_transport(monkeypatch):
    """Keep real httpx request building, replacing only network transport."""
    client_type = httpx.AsyncClient

    def install(handler):
        monkeypatch.setattr(
            "greedy_collector.chains.base.httpx.AsyncClient",
            lambda **kwargs: client_type(transport=httpx.MockTransport(handler), **kwargs),
        )

    return install


@pytest.mark.parametrize("hex_result,expected", [("0xde0b6b3a7640000", "1"), ("0x0", "0")])
async def test_alchemy_transport_post_balance(
    ethereum_adapter, valid_address, alchemy_transport, hex_result, expected
):
    requests = []

    def handler(request):
        requests.append(request)
        if request.url.host == "api.etherscan.io":
            assert request.method == "GET"
            assert request.url.params["action"] == "balance"
            return httpx.Response(429)
        assert request.method == "POST"
        assert str(request.url) == "https://eth-mainnet.g.alchemy.com/v2/test_alchemy_key"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "jsonrpc": "2.0", "id": 1, "method": "eth_getBalance",
            "params": [valid_address, "latest"],
        }
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": hex_result})

    alchemy_transport(handler)
    result = await ethereum_adapter.lookup_address(valid_address)
    assert result["balance_native"] == expected
    assert result["source_api"] == "alchemy"
    assert len(requests) == 2


@pytest.mark.parametrize("failure", [429, 500, "timeout", "malformed_json"])
async def test_alchemy_transport_failure(
    ethereum_adapter, valid_address, alchemy_transport, failure
):
    def handler(request):
        assert request.method == "POST"
        if failure == "timeout":
            raise httpx.ReadTimeout(f"Timeout at {request.url}", request=request)
        if failure == "malformed_json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(failure)

    alchemy_transport(handler)
    with pytest.raises(ChainDataError, match="Alchemy request failed") as error:
        await ethereum_adapter._lookup_address_alchemy(valid_address)
    assert "test_alchemy_key" not in str(error.value)
    assert "test_alchemy_key" not in "".join(traceback.format_exception(error.value))
    if isinstance(failure, int):
        assert str(failure) in str(error.value)
