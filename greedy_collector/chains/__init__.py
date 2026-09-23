from .base import ChainAdapter, ChainDataError
from .bitcoin import BitcoinAdapter
from .ethereum import EthereumAdapter
from .tron import TronAdapter
from .registry import (Capability, ChainError, UnsupportedCapability, get_chain,
                       list_chains, is_supported_chain, get_chain_capabilities)

def get_chain_adapter(chain: str, *capabilities: Capability) -> ChainAdapter:
    return get_chain(chain.lower()).require(*capabilities).adapter()

__all__=['BitcoinAdapter','EthereumAdapter','TronAdapter','ChainAdapter','ChainDataError','get_chain_adapter',
         'get_chain','list_chains','is_supported_chain','get_chain_capabilities','Capability']
