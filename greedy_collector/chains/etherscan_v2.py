"""Shared Etherscan V2 adapter for configured EVM networks."""
from datetime import datetime, timezone
from decimal import Decimal
import asyncio
import re

from .base import ChainDataError
from .evm import EvmAdapter
from ..schemas import NormalizedTransaction

class EtherscanV2Adapter(EvmAdapter):
    etherscan_url = "https://api.etherscan.io/v2/api"

    @property
    def native_divisor(self):
        return Decimal(10) ** self.native_decimals

    def monitoring_interval(self, settings):
        return settings.ethereum_monitor_minutes

    async def lookup_address(self, address: str) -> dict:
        address = self.validate_address(address)
        return await self._lookup_address_etherscan(address)

    def _require_key(self) -> str:
        if not self.settings.etherscan_api_key:
            raise ChainDataError(
                f"{self.display_name} live lookup requires ETHERSCAN_API_KEY"
            )
        return self.settings.etherscan_api_key


    async def _etherscan(self, params: dict) -> dict:
        params = {
            "chainid": str(self.evm_chain_id),
            "apikey": self._require_key(),
            **params,
        }
        data = await self._get(self.etherscan_url, params=params)
        if str(data.get("status")) == "0" and data.get("message") != "No transactions found":
            raise ChainDataError(f"Etherscan returned: {data.get('result')}")
        return data


    async def _lookup_address_etherscan(self, address: str) -> dict:
        """Lookup this EVM address balance via Etherscan.
        
        Args:
            address: Validated EVM address
            
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
            "balance_native": str(Decimal(str(data.get("result", "0"))) / self.native_divisor),
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
            address: Validated EVM address
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


    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        """Retrieve bounded EVM transaction history with pagination
        (up to 10,000 records each for normal transactions and ERC-20 transfers).
        
        Independently paginates both normal transactions (txlist) and ERC-20 transfers
        (tokentx) from Etherscan, then merges and sorts the results globally by
        timestamp descending.
        
        Args:
            address: Validated EVM address
            
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
        
        # Token logs use their protocol position; native records remain tx-scoped.
        from ..transaction_identity import build_event_key
        seen = set()
        deduplicated = []
        for tx in combined:
            identity = (tx.chain, tx.tx_hash, build_event_key(tx))
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
            raise ValueError(f"Invalid {self.display_name} transaction hash")
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
            value_native=str(Decimal(str(row.get("value", "0"))) / self.native_divisor),
            token_symbol=self.native_symbol,
            timestamp=datetime.fromtimestamp(int(timestamp), timezone.utc)
            if timestamp
            else None,
            block_number=str(row.get("blockNumber", "")),
            fee=str((gas_used * gas_price) / self.native_divisor),
            direction="outgoing"
            if focus_address and sender.lower() == focus_address.lower()
            else "incoming",
            source_api="etherscan",
            raw_payload=row,
        )


    def _normalize_token(self, row: dict, focus_address: str) -> NormalizedTransaction:
        from ..transaction_identity import normalize_event_index
        try:
            decimals = int(row.get("tokenDecimal", 0) or 0)
            event_index = normalize_event_index(row.get("logIndex", row.get("log_index")))
        except (TypeError, ValueError, OverflowError):
            raise ChainDataError("Etherscan returned malformed token event metadata") from None
        if decimals < 0 or decimals > 255:
            raise ChainDataError("Etherscan returned malformed token event metadata")
        contract = row.get("contractAddress", row.get("tokenContractAddress"))
        if contract is not None:
            if not isinstance(contract, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", contract):
                raise ChainDataError("Etherscan returned malformed token event metadata")
            contract = contract.lower()
        raw_value = str(row.get("value", "0"))
        divisor = Decimal(10) ** decimals
        sender = row.get("from", "")
        timestamp = row.get("timeStamp")
        public = {
            "asset_type": "erc20", "token_contract": contract,
            "token_name": str(row.get("tokenName", ""))[:255],
            "token_decimals": decimals, "raw_value": raw_value,
        }
        return NormalizedTransaction(
            tx_hash=row.get("hash", ""),
            chain=self.chain,
            from_address=sender,
            to_address=row.get("to", "") or "",
            value_native=str(Decimal(raw_value) / divisor),
            token_symbol=str(row.get("tokenSymbol", "TOKEN"))[:32],
            timestamp=datetime.fromtimestamp(int(timestamp), timezone.utc)
            if timestamp
            else None,
            block_number=str(row.get("blockNumber", "")),
            fee="0",
            direction="outgoing"
            if focus_address and sender.lower() == focus_address.lower()
            else "incoming",
            source_api="etherscan_token",
            raw_payload={**row, "_public": public},
            event_index=event_index,
            asset_contract=contract,
        )

