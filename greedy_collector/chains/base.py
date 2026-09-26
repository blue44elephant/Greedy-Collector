from abc import ABC
import re
import json

import httpx

from ..config import get_settings
from ..schemas import NormalizedTransaction


class ChainDataError(RuntimeError):
    pass


class RpcReadError(ChainDataError):
    """Bounded read failure: no provider message, URL or revert payload retained."""
    def __init__(self, category, selector=None):
        self.category = category
        self.selector = selector
        super().__init__(category)


class ChainAdapter(ABC):
    chain: str
    address_pattern: re.Pattern
    transaction_pattern: re.Pattern | None = None
    address_case = 'sensitive'
    resolve_unqualified_transactions = True
    behavioral_risk = True

    def address_key(self, address: str) -> str:
        """Canonical comparison without validation; also supports stored legacy records."""
        return address.strip()

    def normalize_address(self, address: str) -> str:
        return self.address_key(self.validate_address(address))

    def address_case_insensitive(self, address: str) -> bool:
        return False

    def identify_transaction(self, value: str) -> bool:
        return bool(self.transaction_pattern and self.transaction_pattern.fullmatch(value))

    def normalize_transaction_id(self, value: str) -> str:
        value=value.strip()
        if not self.identify_transaction(value):raise ValueError('Invalid transaction identifier')
        return value.lower()

    def monitoring_interval(self, settings):
        from .registry import UnsupportedCapability
        raise UnsupportedCapability()

    def monitoring_baseline(self, transactions):
        return transactions[0] if transactions else None

    def transfer_identity(self, transaction) -> str:
        """Stable chain-scoped event identity used by graph and monitoring."""
        from ..transaction_identity import event_identity
        persisted_key = transaction.get("event_key") if isinstance(transaction, dict) else getattr(transaction, "event_key", None)
        return event_identity(transaction, persisted_key)

    def __init__(self):
        self.settings = get_settings()

    def validate_address(self, address: str) -> str:
        candidate = address.strip()
        if not self.address_pattern.fullmatch(candidate):
            raise ValueError(f"Invalid {self.chain} address format")
        return candidate

    async def _get(self, url: str, **kwargs):
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", "Greedy-Collector/0.1 (+Greedy Collector)")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout, follow_redirects=True
            ) as client:
                response = await client.get(url, headers=headers, **kwargs)
                response.raise_for_status()
                return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ChainDataError(f"{self.chain} source request failed: {exc}") from exc

    async def _post(self, url: str, **kwargs):
        """Send JSON-RPC requests without exposing credential-bearing URLs in errors."""
        headers = kwargs.pop("headers", {})
        headers.setdefault("User-Agent", "Greedy-Collector/0.1 (+Greedy Collector)")
        try:
            async with httpx.AsyncClient(
                timeout=self.settings.request_timeout, follow_redirects=True
            ) as client:
                response = await client.post(url, headers=headers, **kwargs)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            raise ChainDataError(
                f"{self.chain} source request failed: HTTP {exc.response.status_code}"
            ) from None
        except (httpx.HTTPError, ValueError) as exc:
            # httpx exception text can contain the API key in the request URL.
            raise ChainDataError(
                f"{self.chain} source request failed: {type(exc).__name__}"
            ) from None

    async def _post_bounded(self, url: str, payload: dict, maximum=16384):
        """Strict read-only RPC transport; existing lookup transport is unchanged."""
        try:
            async with httpx.AsyncClient(timeout=min(self.settings.request_timeout, 20),
                                         follow_redirects=False, trust_env=False) as client:
                async with client.stream('POST', url, json=payload,
                        headers={'User-Agent':'Greedy-Collector/0.1','Accept-Encoding':'identity'}) as response:
                    if response.status_code == 429:raise RpcReadError('rate_limited')
                    if response.status_code in (401,403):raise RpcReadError('configuration_unavailable')
                    if response.status_code != 200:raise RpcReadError('transport_failed')
                    if response.headers.get('content-encoding','identity') != 'identity':
                        raise RpcReadError('invalid_provider_response')
                    body=bytearray()
                    async for chunk in response.aiter_bytes():
                        if len(body)+len(chunk)>maximum:raise RpcReadError('invalid_provider_response')
                        body.extend(chunk)
                    return json.loads(body)
        except httpx.TimeoutException:
            raise RpcReadError('timeout') from None
        except httpx.HTTPError:
            raise RpcReadError('transport_failed') from None
        except (ValueError, UnicodeError):
            raise RpcReadError('invalid_provider_response') from None

    async def lookup_address(self, address: str) -> dict:
        from .registry import UnsupportedCapability
        raise UnsupportedCapability()

    async def lookup_transaction(self, tx_hash: str) -> NormalizedTransaction:
        from .registry import UnsupportedCapability
        raise UnsupportedCapability()

    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        from .registry import UnsupportedCapability
        raise UnsupportedCapability()
