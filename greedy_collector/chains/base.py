from abc import ABC, abstractmethod
import re

import httpx

from ..config import get_settings
from ..schemas import NormalizedTransaction


class ChainDataError(RuntimeError):
    pass


class ChainAdapter(ABC):
    chain: str
    address_pattern: re.Pattern

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

    @abstractmethod
    async def lookup_address(self, address: str) -> dict:
        raise NotImplementedError

    @abstractmethod
    async def lookup_transaction(self, tx_hash: str) -> NormalizedTransaction:
        raise NotImplementedError

    @abstractmethod
    async def transactions(self, address: str) -> list[NormalizedTransaction]:
        raise NotImplementedError
