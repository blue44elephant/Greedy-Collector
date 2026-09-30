"""Shared Etherscan V2 adapter for configured EVM networks."""
from datetime import datetime, timezone
from decimal import Decimal
import asyncio
import re

from .base import ChainDataError
from .evm import EvmAdapter
from ..schemas import NormalizedTransaction
from ..collection import atomic_amount, atomic_integer, decimals_or_none, utc_timestamp

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
        params = {**params, "chainid": str(self.evm_chain_id), "apikey": self._require_key()}
        data = await self._get(self.etherscan_url, params=params)
        if not isinstance(data, dict) or data.get("error") is not None:
            raise ChainDataError("malformed_response")
        if str(data.get("status")) == "0" and data.get("message") != "No transactions found":
            message = str(data.get("result", "")).lower()
            category = "rate_limited" if "rate limit" in message else "quota_exhausted" if "quota" in message else "authentication" if "api key" in message else "provider_error"
            raise ChainDataError(category)
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
            "balance_native": atomic_amount(data.get("result"), self.native_decimals),
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
            ChainDataError: If the initial page is unavailable. Later failures
                           retain collected data with explicit PARTIAL diagnostics.
        """
        all_rows = []
        seen_pages = set()
        if not 1 <= max_pages <= 10 or not 1 <= page_size <= 1000:
            raise ValueError("Invalid history bounds")
        if not hasattr(self, "collection_streams"): self.collection_streams = {}
        status, reason = "COMPLETE_WITHIN_REQUESTED_BOUND", "short_or_empty_page"
        for page_num in range(1, max_pages + 1):
            try:
                data = await self._etherscan({"module": "account", "action": action,
                    "address": address, "startblock": 0, "endblock": 99999999,
                    "page": page_num, "offset": page_size, "sort": "desc"})
                rows = data.get("result") if isinstance(data, dict) else None
                if rows == "No transactions found": rows = []
                if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows) or len(rows) > page_size:
                    raise ChainDataError("malformed_response")
                import json
                signature = json.dumps(rows, sort_keys=True, separators=(",", ":"))
                if rows and signature in seen_pages:
                    status, reason = "PARTIAL", "repeated_page"
                    break
                seen_pages.add(signature)
                all_rows.extend(rows)
                if len(rows) < page_size: break
                if page_num == max_pages: status, reason = "TRUNCATED", "page_bound"
            except ChainDataError as exc:
                if not all_rows: raise
                status, reason = "PARTIAL", getattr(exc, "category", "provider_error")
                break
        self.collection_streams[action] = {"status": status, "reason": reason,
            "pages": page_num, "records": len(all_rows), "max_records": max_pages * page_size}
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
            ChainDataError: If both history streams are unavailable
        """
        address = self.validate_address(address)
        
        self.collection_streams = {}
        responses = await asyncio.gather(
            self._paginate_account_action("txlist", address),
            self._paginate_account_action("tokentx", address), return_exceptions=True)
        if all(isinstance(r, Exception) for r in responses):
            raise ChainDataError("provider_error")
        normal, tokens = [], []
        for action, response, normalize, target in zip(
                ("txlist", "tokentx"), responses, (self._normalize, self._normalize_token), (normal, tokens)):
            if isinstance(response, Exception):
                if not isinstance(response, ChainDataError): raise response
                self.collection_streams[action] = {"status": "UNAVAILABLE", "reason": getattr(response, "category", "provider_error")}
                continue
            for row in response:
                try:
                    if not isinstance(row, dict) or not row.get("hash"): raise ChainDataError("malformed_response")
                    target.append(normalize(row, address))
                except (ChainDataError, ValueError, TypeError, OverflowError):
                    self.collection_streams[action] = {**self.collection_streams.get(action, {}),
                        "status": "PARTIAL", "reason": "malformed_response"}

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
        row = data.get("result") if isinstance(data, dict) else None
        if not isinstance(row, dict):
            raise ChainDataError("Transaction was not found")
        if str(row.get("hash", "")).lower() != tx_hash.strip().lower():
            raise ChainDataError("malformed_response")
        def quantity(key, optional=False):
            value = row.get(key)
            if value is None and optional: return ""
            if not isinstance(value, str) or not re.fullmatch(r"0x[0-9a-fA-F]{1,64}", value):
                raise ChainDataError("malformed_response")
            return str(int(value, 16))
        normalized = {
            "hash": row.get("hash", ""),
            "from": row.get("from", ""),
            "to": row.get("to", ""),
            "value": quantity("value"),
            "blockNumber": quantity("blockNumber", optional=True),
            "gas": quantity("gas", optional=True),
            "gasPrice": quantity("gasPrice", optional=True),
        }
        result = self._normalize(normalized, "")
        result.raw_payload = {**result.raw_payload, "provider": row}
        # The proxy transaction response does not establish execution success or paid fee.
        result.fee = ""
        return result


    def _normalize(self, row: dict, focus_address: str) -> NormalizedTransaction:
        sender = (row.get("from", "") or "").lower()
        recipient = (row.get("to", "") or "").lower()
        gas_used = atomic_integer(row.get("gasUsed", "0") or "0")
        gas_price = atomic_integer(row.get("gasPrice", "0") or "0")
        timestamp = row.get("timeStamp")
        return NormalizedTransaction(
            tx_hash=self.normalize_transaction_id(row.get("hash", "")),
            chain=self.chain,
            from_address=sender,
            to_address=recipient,
            value_native=atomic_amount(row.get("value"), self.native_decimals),
            token_symbol=self.native_symbol,
            timestamp=utc_timestamp(timestamp),
            block_number=str(row.get("blockNumber", "")),
            fee=atomic_amount(gas_used * gas_price, self.native_decimals) if "gasUsed" in row else "",
            direction="outgoing"
            if focus_address and sender.lower() == focus_address.lower()
            else "incoming" if focus_address else "unknown",
            source_api="etherscan",
            raw_payload={**row, "_public": {"asset_type": "native", "raw_value": str(atomic_integer(row.get("value"))), "token_decimals": self.native_decimals}},
        )


    def _normalize_token(self, row: dict, focus_address: str) -> NormalizedTransaction:
        from ..transaction_identity import normalize_event_index
        try:
            decimals = decimals_or_none(row.get("tokenDecimal"))
            event_index = normalize_event_index(row.get("logIndex", row.get("log_index")))
        except (TypeError, ValueError, OverflowError):
            raise ChainDataError("Etherscan returned malformed token event metadata") from None
        contract = row.get("contractAddress", row.get("tokenContractAddress"))
        if contract is not None:
            if not isinstance(contract, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", contract):
                raise ChainDataError("Etherscan returned malformed token event metadata")
            contract = contract.lower()
        raw_value = str(atomic_integer(row.get("value")))
        sender = (row.get("from", "") or "").lower()
        timestamp = row.get("timeStamp")
        public = {
            "asset_type": "erc20", "token_contract": contract,
            "token_name": str(row.get("tokenName", ""))[:255],
            "token_decimals": decimals, "raw_value": raw_value,
        }
        return NormalizedTransaction(
            tx_hash=self.normalize_transaction_id(row.get("hash", "")),
            chain=self.chain,
            from_address=sender,
            to_address=(row.get("to", "") or "").lower(),
            value_native=atomic_amount(raw_value, decimals) if decimals is not None else "",
            token_symbol=str(row.get("tokenSymbol", "TOKEN"))[:32],
            timestamp=utc_timestamp(timestamp),
            block_number=str(row.get("blockNumber", "")),
            fee="",
            direction="outgoing"
            if focus_address and sender.lower() == focus_address.lower()
            else "incoming" if focus_address else "unknown",
            source_api="etherscan_token",
            raw_payload={**row, "_public": public},
            event_index=event_index,
            asset_contract=contract,
        )

