from datetime import datetime, timezone
from decimal import Decimal
import asyncio
import re

from .base import ChainAdapter, ChainDataError
from ..schemas import NormalizedTransaction


WEI = Decimal("1000000000000000000")


class EthereumAdapter(ChainAdapter):
    chain = "ethereum"
    address_pattern = re.compile(r"^0x[a-fA-F0-9]{40}$")
    etherscan_url = "https://api.etherscan.io/v2/api"
    alchemy_url = "https://eth-mainnet.g.alchemy.com/v2"

    def _require_key(self) -> str:
        if not self.settings.etherscan_api_key:
            raise ChainDataError(
                "Ethereum live lookup requires ETHERSCAN_API_KEY; no paid API is required"
            )
        return self.settings.etherscan_api_key

    def _require_alchemy_key(self) -> str:
        if not self.settings.alchemy_api_key:
            raise ChainDataError(
                "Alchemy fallback requires ALCHEMY_API_KEY environment variable"
            )
        return self.settings.alchemy_api_key

    async def _etherscan(self, params: dict) -> dict:
        params = {
            "chainid": "1",
            "apikey": self._require_key(),
            **params,
        }
        data = await self._get(self.etherscan_url, params=params)
        if str(data.get("status")) == "0" and data.get("message") != "No transactions found":
            raise ChainDataError(f"Etherscan returned: {data.get('result')}")
        return data

    async def _alchemy(self, method: str, params: list) -> dict:
        """Make a JSON-RPC call to Alchemy.
        
        Args:
            method: JSON-RPC method name (e.g., "eth_getBalance")
            params: List of parameters for the method
            
        Returns:
            The result field from the JSON-RPC response
            
        Raises:
            ChainDataError: If Alchemy request fails or returns error
        """
        key = self._require_alchemy_key()
        url = f"{self.alchemy_url}/{key}"
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params,
        }
        
        try:
            data = await self._get(url, json=payload)
        except ChainDataError as exc:
            raise ChainDataError(f"Alchemy request failed: {exc}") from exc
        
        # Check for JSON-RPC error response
        if "error" in data and data["error"]:
            error_msg = data["error"].get("message", "Unknown error")
            raise ChainDataError(f"Alchemy returned error: {error_msg}")
        
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
            raise ChainDataError(f"Invalid hex balance from Alchemy: {exc}") from exc
        
        balance_eth = str(Decimal(balance_wei) / WEI)
        
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": balance_eth,
            "source_api": "alchemy",
            "raw": {"result": result},
        }

    async def _lookup_address_etherscan(self, address: str) -> dict:
        """Lookup Ethereum address balance via Etherscan.
        
        Args:
            address: Validated Ethereum address
            
        Returns:
            Balance info dict with normalized format
            
        Raises:
            ChainDataError: If Etherscan lookup fails
        """
        data = await self._etherscan(
            {"module": "account", "action": "balance", "address": address, "tag": "latest"}
        )
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": str(Decimal(str(data.get("result", "0"))) / WEI),
            "source_api": "etherscan",
            "raw": data,
        }

    async def _paginate_account_action(
        self, action: str, address: str, max_pages: int = 10, page_size: int = 1000
    ) -> list[dict]:
        """Paginate through Etherscan account action results.
        
        Retrieves bounded records for an action (txlist or tokentx) by iterating
        through pages. Stops when: fewer records returned than page_size, valid empty
        result, or max_pages reached.
        
        Args:
            action: Etherscan action ("txlist" or "tokentx")
            address: Validated Ethereum address
            max_pages: Maximum pages to retrieve (default 10, max 10,000 records)
            page_size: Records per page (default 1000, Etherscan max)
            
        Returns:
            List of all transaction/token rows from all pages
            
        Raises:
            ChainDataError: If a page request fails after page 1 succeeds,
                           (partial data not returned)
        """
        all_rows = []
        
        for page_num in range(1, max_pages + 1):
            try:
                data = await self._etherscan({
                    "module": "account",
                    "action": action,
                    "address": address,
                    "startblock": 0,
                    "endblock": 99999999,
                    "page": page_num,
                    "offset": page_size,
                    "sort": "desc",
                })
            except ChainDataError as exc:
                # If we already have data from page 1, a later page failure is fatal
                if all_rows:
                    raise ChainDataError(
                        f"Etherscan {action} pagination failed at page {page_num}: {exc}"
                    ) from exc
                # Page 1 itself failed, raise as-is
                raise
            
            # Extract result
            rows = data.get("result", [])
            
            # Handle valid empty response
            if not rows or (isinstance(rows, str) and rows == "No transactions found"):
                # Normal termination: no more data
                break
            
            # Filter to valid dict rows
            valid_rows = [r for r in rows if isinstance(r, dict)]
            all_rows.extend(valid_rows)
            
            # Stop if fewer than page_size returned (last page)
            if len(valid_rows) < page_size:
                break
        
        return all_rows

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

    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        """Retrieve bounded Ethereum transaction history with pagination
        (up to 10,000 records each for normal transactions and ERC-20 transfers).
        
        Independently paginates both normal transactions (txlist) and ERC-20 transfers
        (tokentx) from Etherscan, then merges and sorts the results globally by
        timestamp descending.
        
        Args:
            address: Validated Ethereum address
            
        Returns:
            List of NormalizedTransaction objects sorted newest-first
            
        Raises:
            ChainDataError: If page 1 succeeds but a later page fails
        """
        address = self.validate_address(address)
        
        # Paginate both transaction types independently (up to 10,000 each)
        normal_rows, token_rows = await asyncio.gather(
            self._paginate_account_action("txlist", address, max_pages=10, page_size=1000),
            self._paginate_account_action("tokentx", address, max_pages=10, page_size=1000),
        )
        
        # Normalize rows
        normal = [
            self._normalize(row, address)
            for row in normal_rows
            if isinstance(row, dict) and row.get("hash")
        ]
        tokens = [
            self._normalize_token(row, address)
            for row in token_rows
            if isinstance(row, dict) and row.get("hash")
        ]
        
        # Combine and globally sort by timestamp descending
        combined = normal + tokens
        
        # Deduplicate conservatively using transaction identity semantics:
        # (chain, tx_hash, from_address, to_address, value_native, token_symbol)
        seen = set()
        deduplicated = []
        for tx in combined:
            identity = (
                tx.chain,
                tx.tx_hash,
                tx.from_address,
                tx.to_address,
                tx.value_native,
                tx.token_symbol,
            )
            if identity not in seen:
                seen.add(identity)
                deduplicated.append(tx)
        
        # Sort globally by timestamp descending
        return sorted(
            deduplicated,
            key=lambda tx: tx.timestamp or datetime.min.replace(tzinfo=timezone.utc),
            reverse=True,
        )

    async def lookup_transaction(self, tx_hash: str) -> NormalizedTransaction:
        if not re.fullmatch(r"0x[a-fA-F0-9]{64}", tx_hash.strip()):
            raise ValueError("Invalid Ethereum transaction hash")
        data = await self._etherscan(
            {"module": "proxy", "action": "eth_getTransactionByHash", "txhash": tx_hash}
        )
        row = data.get("result")
        if not isinstance(row, dict):
            raise ChainDataError("Transaction was not found")
        normalized = {
            "hash": row.get("hash", ""),
            "from": row.get("from", ""),
            "to": row.get("to", ""),
            "value": str(int(row.get("value", "0x0"), 16)),
            "blockNumber": str(int(row.get("blockNumber", "0x0"), 16))
            if row.get("blockNumber")
            else "",
            "gas": str(int(row.get("gas", "0x0"), 16)),
            "gasPrice": str(int(row.get("gasPrice", "0x0"), 16)),
        }
        return self._normalize(normalized, "")

    def _normalize(self, row: dict, focus_address: str) -> NormalizedTransaction:
        sender = row.get("from", "")
        recipient = row.get("to", "") or ""
        gas_used = Decimal(str(row.get("gasUsed", row.get("gas", "0")) or "0"))
        gas_price = Decimal(str(row.get("gasPrice", "0") or "0"))
        timestamp = row.get("timeStamp")
        return NormalizedTransaction(
            tx_hash=row.get("hash", ""),
            chain=self.chain,
            from_address=sender,
            to_address=recipient,
            value_native=str(Decimal(str(row.get("value", "0"))) / WEI),
            token_symbol="ETH",
            timestamp=datetime.fromtimestamp(int(timestamp), timezone.utc)
            if timestamp
            else None,
            block_number=str(row.get("blockNumber", "")),
            fee=str((gas_used * gas_price) / WEI),
            direction="outgoing"
            if focus_address and sender.lower() == focus_address.lower()
            else "incoming",
            source_api="etherscan",
            raw_payload=row,
        )

    def _normalize_token(self, row: dict, focus_address: str) -> NormalizedTransaction:
        decimals = int(row.get("tokenDecimal", 0) or 0)
        divisor = Decimal(10) ** decimals
        sender = row.get("from", "")
        timestamp = row.get("timeStamp")
        return NormalizedTransaction(
            tx_hash=row.get("hash", ""),
            chain=self.chain,
            from_address=sender,
            to_address=row.get("to", "") or "",
            value_native=str(Decimal(str(row.get("value", "0"))) / divisor),
            token_symbol=row.get("tokenSymbol", "TOKEN"),
            timestamp=datetime.fromtimestamp(int(timestamp), timezone.utc)
            if timestamp
            else None,
            block_number=str(row.get("blockNumber", "")),
            fee="0",
            direction="outgoing"
            if focus_address and sender.lower() == focus_address.lower()
            else "incoming",
            source_api="etherscan_token",
            raw_payload=row,
        )
