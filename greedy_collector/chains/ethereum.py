"""Ethereum mainnet Etherscan V2 adapter with Ethereum-only Alchemy fallback."""
from decimal import Decimal
import re

from .base import ChainDataError, RpcReadError
from ..collection import atomic_amount
from .etherscan_v2 import EtherscanV2Adapter

WEI = Decimal("1000000000000000000")

class EthereumAdapter(EtherscanV2Adapter):
    chain = "ethereum"
    alchemy_url = "https://eth-mainnet.g.alchemy.com/v2"

    def _require_alchemy_key(self) -> str:
        if not self.settings.alchemy_api_key:
            raise ChainDataError(
                "Alchemy fallback requires ALCHEMY_API_KEY environment variable"
            )
        return self.settings.alchemy_api_key


    async def _alchemy(self, method: str, params: list, *, bounded=False) -> dict:
        """Make a JSON-RPC call to Alchemy.
        
        Args:
            method: JSON-RPC method name (e.g., "eth_getBalance")
            params: List of parameters for the method
            
        Returns:
            The result field from the JSON-RPC response
            
        Raises:
            ChainDataError: If Alchemy request fails or returns error
        """
        if bounded and not self.settings.alchemy_api_key:
            raise RpcReadError('configuration_unavailable')
        key = self._require_alchemy_key()
        url = f"{self.alchemy_url}/{key}"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        
        if bounded:
            data = await self._post_bounded(url, payload)
            if not isinstance(data, dict) or data.get('jsonrpc') != '2.0' or type(data.get('id')) is not int or data['id'] != 1:
                raise RpcReadError('invalid_provider_response')
            if 'error' in data:
                error=data['error']
                if not isinstance(error,dict) or 'result' in data:raise RpcReadError('invalid_provider_response')
                if error.get('code') == 429:raise RpcReadError('rate_limited')
                raw=error.get('data')
                if isinstance(raw,dict):raw=raw.get('data')
                selector=raw[:10].lower() if isinstance(raw,str) and re.fullmatch(r'0x[0-9a-fA-F]{8,}',raw) else None
                raise RpcReadError('invalid_provider_response',selector)
            if 'result' not in data:raise RpcReadError('invalid_provider_response')
            return data['result']

        try:
            data = await self._post(url, json=payload)
        except ChainDataError as exc:
            raise ChainDataError(f"Alchemy request failed: {exc}") from exc
        
        # Check for JSON-RPC error response
        if "error" in data and data["error"]:
            error_msg = data["error"].get("message", "Unknown error")
            raise ChainDataError("Alchemy returned error: provider_error")
        
        # Ensure result exists
        if "result" not in data:
            raise ChainDataError("Alchemy response missing result field")
        
        return data["result"]


    async def _lookup_address_alchemy(self, address: str) -> dict:
        """Lookup Ethereum address balance via Alchemy.
        
        Args:
            address: Validated Ethereum address
            
        Returns:
            Balance info dict with normalized format matching Etherscan path
            
        Raises:
            ChainDataError: If balance lookup fails or returns invalid data
        """
        # eth_getBalance returns hex-encoded Wei
        try:
            result = await self._alchemy("eth_getBalance", [address, "latest"])
        except ChainDataError:
            raise
        
        # Validate result is a hex string
        if not isinstance(result, str):
            raise ChainDataError(
                f"Alchemy eth_getBalance returned invalid type: {type(result)}"
            )
        
        # Convert hex Wei to decimal ETH
        try:
            balance_wei = int(result, 16)
        except (ValueError, TypeError) as exc:
            raise ChainDataError("Invalid hex balance from Alchemy: malformed_response") from None
        
        balance_eth = atomic_amount(balance_wei, 18)
        
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": balance_eth,
            "source_api": "alchemy",
            "raw": {"result": result},
        }


    async def lookup_address(self, address: str) -> dict:
        """Lookup Ethereum address balance with fallback support.
        
        Attempts to get balance from Etherscan first. If Etherscan fails with a
        provider error (not a zero balance), attempts Alchemy as fallback.
        
        Args:
            address: Ethereum address to lookup
            
        Returns:
            Balance info dict with source_api indicating which provider was used
            
        Raises:
            ChainDataError: If both Etherscan and Alchemy fail, or if neither is configured
        """
        address = self.validate_address(address)
        
        # Try Etherscan first (primary provider)
        try:
            return await self._lookup_address_etherscan(address)
        except ChainDataError as err_eth:
            # Etherscan failed, attempt Alchemy fallback
            try:
                return await self._lookup_address_alchemy(address)
            except ChainDataError as err_alch:
                # Both providers failed, raise combined error
                raise ChainDataError(
                    f"Ethereum address lookup failed: "
                    f"Etherscan error: {err_eth} | "
                    f"Alchemy fallback error: {err_alch}"
                ) from err_eth
