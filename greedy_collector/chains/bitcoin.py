from datetime import datetime, timezone
from decimal import Decimal
import re

from .base import ChainAdapter, ChainDataError
from ..schemas import NormalizedTransaction


SATOSHIS = Decimal("100000000")
MAX_CONFIRMED_RECORDS = 500  # Safety cap
CONFIRMED_PER_PAGE = 25  # Esplora confirmed pagination returns 25 per page


class BitcoinAdapter(ChainAdapter):
    chain = "bitcoin"
    address_pattern = re.compile(
        r"^(?:bc1[a-zA-HJ-NP-Z0-9]{11,71}|[13][a-km-zA-HJ-NP-Z1-9]{25,34})$",
        re.IGNORECASE,
    )
    base_urls = [
        ("blockstream", "https://blockstream.info/api"),
        ("mempool_space", "https://mempool.space/api"),
    ]

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
        all_rows = []
        all_confirmed = []
        last_cursor = None
        previous_cursor = None
        page_num = 0
        confirmed_count = 0
        
        while True:
            try:
                if page_num == 0:
                    # Initial request includes mempool + confirmed
                    rows = await self._fetch_from_provider(
                        base_url, f"/address/{address}/txs"
                    )
                else:
                    # Confirmed pagination - must have a cursor
                    if not last_cursor:
                        break
                    rows = await self._fetch_from_provider(
                        base_url, f"/address/{address}/txs/chain/{last_cursor}"
                    )
            except ChainDataError as exc:
                raise ChainDataError(
                    f"Bitcoin {provider_name} pagination failed at page {page_num}: {exc}"
                ) from exc
            
            if not rows:
                # Empty response = end of history
                break
            
            page_num += 1
            
            if page_num == 1:
                # Initial page: separate mempool from confirmed
                for row in rows:
                    status = row.get("status", {})
                    # Use status.confirmed field if available, else check block_height
                    is_confirmed = status.get("confirmed", False) or status.get("block_height") is not None
                    if is_confirmed:
                        all_confirmed.append(row)
                        confirmed_count += 1
                    else:
                        all_rows.append(row)  # mempool
                
                # For pagination, we need the last confirmed txid
                if all_confirmed:
                    last_cursor = all_confirmed[-1]["txid"]
                else:
                    # No confirmed transactions, can't paginate
                    break
            else:
                # Later pages: all are confirmed
                for row in rows:
                    all_confirmed.append(row)
                    confirmed_count += 1
                
                # Update cursor for next iteration
                if rows:
                    previous_cursor = last_cursor
                    last_cursor = rows[-1]["txid"]
                    
                    # Protect against cursor stagnation
                    if previous_cursor == last_cursor:
                        raise ChainDataError(
                            f"Bitcoin {provider_name} cursor stagnation detected: "
                            f"page {page_num} ended with same cursor as previous page, no progress"
                        )
            
            # Check stop conditions
            if len(rows) < CONFIRMED_PER_PAGE:
                # Short page indicates end of history
                break
            
            if confirmed_count >= MAX_CONFIRMED_RECORDS:
                # Reached safety cap
                break
        
        # Combine: mempool + confirmed (both already newest-first from provider)
        result = all_rows + all_confirmed
        return result

    async def lookup_address(self, address: str) -> dict:
        address = self.validate_address(address)
        payload, source = await self._fetch(f"/address/{address}")
        chain = payload.get("chain_stats", {})
        mempool = payload.get("mempool_stats", {})
        funded = int(chain.get("funded_txo_sum", 0)) + int(
            mempool.get("funded_txo_sum", 0)
        )
        spent = int(chain.get("spent_txo_sum", 0)) + int(
            mempool.get("spent_txo_sum", 0)
        )
        return {
            "chain": self.chain,
            "address": address,
            "balance_native": str(Decimal(funded - spent) / SATOSHIS),
            "transaction_count": int(chain.get("tx_count", 0))
            + int(mempool.get("tx_count", 0)),
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
        inputs = row.get("vin", [])
        outputs = row.get("vout", [])
        from_addresses = [
            item.get("prevout", {}).get("scriptpubkey_address", "")
            for item in inputs
            if item.get("prevout")
        ]
        to_addresses = [
            item.get("scriptpubkey_address", "") for item in outputs
        ]
        sent_by_focus = focus_address in from_addresses if focus_address else False
        received = sum(
            int(item.get("value", 0))
            for item in outputs
            if not focus_address or item.get("scriptpubkey_address") == focus_address
        )
        sent = sum(
            int(item.get("prevout", {}).get("value", 0))
            for item in inputs
            if item.get("prevout")
            and (not focus_address or item["prevout"].get("scriptpubkey_address") == focus_address)
        )
        value = sent if sent_by_focus else received
        input_value = sum(
            int(item.get("prevout", {}).get("value", 0))
            for item in inputs
            if item.get("prevout")
        )
        output_value = sum(int(item.get("value", 0)) for item in outputs)
        block_time = row.get("status", {}).get("block_time")
        return NormalizedTransaction(
            tx_hash=row.get("txid", ""),
            chain=self.chain,
            from_address=from_addresses[0] if from_addresses else "",
            to_address=to_addresses[0] if to_addresses else "",
            value_native=str(Decimal(value) / SATOSHIS),
            token_symbol="BTC",
            timestamp=datetime.fromtimestamp(block_time, timezone.utc)
            if block_time
            else None,
            block_number=str(row.get("status", {}).get("block_height", "")),
            fee=str(Decimal(max(input_value - output_value, 0)) / SATOSHIS),
            direction="outgoing" if sent_by_focus else "incoming",
            source_api=source_api,
            raw_payload=row,
        )
