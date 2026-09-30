from datetime import datetime, timezone
from decimal import Decimal
import re

from .base import ChainAdapter, ChainDataError
from ..schemas import NormalizedTransaction
from ..collection import atomic_amount, atomic_integer


SATOSHIS = Decimal("100000000")
MAX_CONFIRMED_RECORDS = 500  # Safety cap
CONFIRMED_PER_PAGE = 25  # Esplora confirmed pagination returns 25 per page


class BitcoinAdapter(ChainAdapter):
    chain = "bitcoin"
    transaction_pattern = re.compile(r'[0-9a-fA-F]{64}')
    address_case = 'bech32_insensitive'

    def address_key(self,address):
        value=address.strip()
        return value.lower() if value.lower().startswith('bc1') else value

    def address_case_insensitive(self,address):return address.lower().startswith('bc1')
    def monitoring_interval(self,settings):return settings.bitcoin_monitor_minutes
    def monitoring_baseline(self,transactions):
        return next((tx for tx in transactions if (tx.get('timestamp') if isinstance(tx,dict) else tx.timestamp) is not None),None)
    address_pattern = re.compile(
        r"^(?:bc1[a-zA-HJ-NP-Z0-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$",
        re.IGNORECASE,
    )
    base_urls = [
        ("blockstream", "https://blockstream.info/api"),
        ("mempool_space", "https://mempool.space/api"),
    ]

    def validate_address(self, address):
        from .litecoin import _decode_litecoin_segwit, _sha256d
        from .base58 import base58_decode
        candidate = address.strip()
        try:
            if candidate.lower().startswith("bc1"):
                return _decode_litecoin_segwit(candidate, "bc")
            decoded = base58_decode(candidate)
            if len(decoded) != 25 or decoded[0] not in (0, 5) or decoded[-4:] != _sha256d(decoded[:-4])[:4]:
                raise ValueError()
        except ValueError:
            raise ValueError("Invalid Bitcoin mainnet address") from None
        return candidate

    async def _fetch(self, path: str):
        """Try all providers in sequence."""
        errors = []
        for source, base_url in self.base_urls:
            try:
                return await self._get(f"{base_url}{path}"), source
            except ChainDataError as exc:
                errors.append(str(exc))
        raise ChainDataError("All Bitcoin sources failed: " + " | ".join(errors))

    async def _fetch_from_provider(self, base_url: str, path: str) -> dict:
        """Fetch from a specific provider without fallback."""
        try:
            return await self._get(f"{base_url}{path}")
        except ChainDataError as exc:
            raise ChainDataError(f"Provider request failed: {exc}") from exc

    async def _transactions_from_provider(
        self, base_url: str, provider_name: str, address: str
    ) -> list[dict]:
        """
        Paginate through confirmed history using a single provider.
        
        Initial request: /address/{address}/txs
        - Returns up to 50 mempool + 25 confirmed transactions, newest-first
        
        Pagination: /address/{address}/txs/chain/{last_confirmed_txid}
        - Returns confirmed transactions only, newest-first
        - Cursor is the last confirmed txid from previous page
        
        Returns all rows (mempool + confirmed), sorted newest-first.
        """
        confirmed, mempool = {}, {}
        cursor, cursors = None, set()
        self.collection_streams = {"history": {"status": "COMPLETE_WITHIN_REQUESTED_BOUND", "reason": "short_or_empty_page"}}
        for page in range(20):
            path = f"/address/{address}/txs" + (f"/chain/{cursor}" if cursor else "")
            rows = await self._fetch_from_provider(base_url, path)
            if not isinstance(rows, list) or len(rows) > (75 if page == 0 else 25):
                raise ChainDataError("bitcoin_invalid_provider_response")
            confirmed_page = []
            for row in rows:
                if not isinstance(row, dict) or not self.identify_transaction(str(row.get("txid", ""))) or not isinstance(row.get("status"), dict):
                    raise ChainDataError("bitcoin_invalid_provider_response")
                txid, status = row["txid"].lower(), row["status"]
                is_confirmed = status.get("confirmed") is True or (status.get("confirmed") is None and status.get("block_height") is not None)
                if is_confirmed:
                    confirmed_page.append(row)
                    if len(confirmed) < MAX_CONFIRMED_RECORDS: confirmed[txid] = row
                    mempool.pop(txid, None)
                elif page == 0 and txid not in confirmed and len(mempool) < 50:
                    mempool[txid] = row
            if confirmed_page:
                following = confirmed_page[-1]["txid"].lower()
                if following in cursors: raise ChainDataError("Bitcoin cursor stagnation detected")
                cursors.add(following)
                cursor = following
            if len(confirmed_page) < CONFIRMED_PER_PAGE: break
            if len(confirmed) >= MAX_CONFIRMED_RECORDS:
                self.collection_streams["history"] = {"status": "TRUNCATED", "reason": "record_bound"}
                break
        else:
            self.collection_streams["history"] = {"status": "TRUNCATED", "reason": "page_bound"}
        return list(mempool.values()) + list(confirmed.values())

    async def lookup_address(self, address: str) -> dict:
        address = self.validate_address(address)
        payload, source = await self._fetch(f"/address/{address}")
        from .litecoin import _stat_value
        if not isinstance(payload, dict): raise ChainDataError("bitcoin_invalid_provider_response")
        chain = payload.get("chain_stats")
        mempool = payload.get("mempool_stats")
        funded = _stat_value(chain, "funded_txo_sum") + _stat_value(mempool, "funded_txo_sum")
        spent = _stat_value(chain, "spent_txo_sum") + _stat_value(mempool, "spent_txo_sum")
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": atomic_amount(funded - spent, 8),
            "transaction_count": _stat_value(chain, "tx_count") + _stat_value(mempool, "tx_count"),
            "source_api": source,
            "raw": payload,
        }

    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        """
        Fetch bounded transaction history with pagination and fallback (about 500
        confirmed records plus the initial provider mempool set).
        
        Strategy:
        1. Try Blockstream pagination from start to finish
        2. If Blockstream fails at ANY point, discard partial and try Mempool from start
        3. Return normalized + deduplicated results, sorted newest-first
        """
        address = self.validate_address(address)
        
        # Try Blockstream first
        for provider_name, base_url in self.base_urls:
            try:
                rows = await self._transactions_from_provider(
                    base_url, provider_name, address
                )
                
                # Normalize all rows
                normalized = [
                    self._normalize(row, address, provider_name)
                    for row in rows
                    if row.get("txid")
                ]
                
                # Deduplicate by normalized identity (txid + from + to + value)
                seen_ids = set()
                deduplicated = []
                for tx in normalized:
                    # Dedup by composite identity
                    identity = (
                        tx.chain,
                        tx.tx_hash,
                        tx.from_address,
                        tx.to_address,
                        tx.value_native,
                        tx.token_symbol,
                    )
                    if identity not in seen_ids:
                        seen_ids.add(identity)
                        deduplicated.append(tx)
                
                # Separate unconfirmed (mempool, no timestamp) from confirmed
                # Mempool txs must come FIRST so monitoring.py detects them
                # before reaching previous_tx (a confirmed transaction)
                unconfirmed = [tx for tx in deduplicated if tx.timestamp is None]
                confirmed = [tx for tx in deduplicated if tx.timestamp is not None]
                
                # Sort confirmed by timestamp (newest first)
                confirmed_sorted = sorted(confirmed, key=lambda tx: tx.timestamp, reverse=True)
                
                # Return unconfirmed first (preserving order), then confirmed
                result = unconfirmed + confirmed_sorted
                
                return result
            except ChainDataError as exc:
                # If this was the last provider, raise
                if provider_name == self.base_urls[-1][0]:
                    raise
                # Otherwise, continue to next provider (discard partial results)
                continue
        
        # Should not reach here
        raise ChainDataError("No Bitcoin providers available")

    async def lookup_transaction(self, tx_hash: str) -> NormalizedTransaction:
        if not re.fullmatch(r"[0-9a-fA-F]{64}", tx_hash.strip()):
            raise ValueError("Invalid Bitcoin transaction hash")
        row, source = await self._fetch(f"/tx/{tx_hash.strip()}")
        return self._normalize(row, "", source)

    def _normalize(
        self, row: dict, focus_address: str, source_api: str
    ) -> NormalizedTransaction:
        # Both Esplora chains share conservative wallet-relative structural facts.
        from .litecoin import LitecoinAdapter
        normalized_row = dict(row)
        status = dict(row.get("status", {}))
        status.setdefault("confirmed", status.get("block_height") is not None)
        normalized_row["status"] = status
        if "fee" not in row:
            inputs = row.get("vin", [])
            if inputs and all(isinstance(i, dict) and isinstance(i.get("prevout"), dict) for i in inputs):
                total_in = sum(atomic_integer(i["prevout"].get("value")) for i in inputs)
                total_out = sum(atomic_integer(i.get("value")) for i in row.get("vout", []))
                normalized_row["fee"] = max(0, total_in - total_out)
        result = LitecoinAdapter._normalize(self, normalized_row, focus_address, source_api)
        result.token_symbol = "BTC"
        return result
