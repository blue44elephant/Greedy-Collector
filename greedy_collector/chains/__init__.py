from .base import ChainAdapter, ChainDataError
from .bitcoin import BitcoinAdapter
from .ethereum import EthereumAdapter


def get_chain_adapter(chain: str) -> ChainAdapter:
    adapters = {
        "bitcoin": BitcoinAdapter(),
        "ethereum": EthereumAdapter(),
    }
    try:
        return adapters[chain.lower()]
    except KeyError as exc:
        raise ValueError(f"Unsupported chain: {chain}") from exc


__all__ = [
    "BitcoinAdapter",
    "ChainAdapter",
    "ChainDataError",
    "EthereumAdapter",
    "get_chain_adapter",
]
