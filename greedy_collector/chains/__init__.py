from .base import ChainAdapter, ChainDataError
from .bitcoin import BitcoinAdapter
from .ethereum import EthereumAdapter
from .etherscan_v2 import EtherscanV2Adapter
from .evm_networks import BaseAdapter, ArbitrumAdapter, BnbAdapter, PolygonAdapter
from .tron import TronAdapter
from .solana import SolanaAdapter
from .litecoin import LitecoinAdapter
from .monero import MoneroAdapter
from .registry import (Capability, ChainError, UnsupportedCapability, get_chain,
                       list_chains, is_supported_chain, get_chain_capabilities)

def get_chain_adapter(chain: str, *capabilities: Capability) -> ChainAdapter:
    return get_chain(chain.lower()).require(*capabilities).adapter()

__all__=['BitcoinAdapter','EthereumAdapter','EtherscanV2Adapter','BaseAdapter','ArbitrumAdapter','BnbAdapter','PolygonAdapter','TronAdapter','SolanaAdapter','LitecoinAdapter','MoneroAdapter','ChainAdapter','ChainDataError','get_chain_adapter',
         'get_chain','list_chains','is_supported_chain','get_chain_capabilities','Capability']
