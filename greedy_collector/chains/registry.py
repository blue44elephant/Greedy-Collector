"""Internal, ordered chain definitions. Providers and credentials stay private."""
from dataclasses import dataclass
from enum import Enum
import re
from .base import ChainAdapter

class ChainError(ValueError):
    code = 'unsupported_chain'
    def __init__(self): super().__init__(self.code)

class UnsupportedCapability(ChainError):
    code = 'unsupported_chain_capability'

class ChainFamily(str, Enum):
    UTXO = 'utxo'
    ACCOUNT = 'account'

class Capability(str, Enum):
    ADDRESS_VALIDATION = 'address_validation'
    BALANCE = 'balance'
    TRANSACTION_HISTORY = 'transaction_history'
    TRANSACTION_LOOKUP = 'transaction_lookup'
    TOKEN_TRANSFERS = 'token_transfers'
    COUNTERPARTIES = 'counterparties'
    GRAPH = 'graph'
    MONITORING = 'monitoring'
    PENDING_TRANSACTIONS = 'pending_transactions'
    DISCOVERY = 'discovery'
    LABELS = 'labels'
    CASES = 'cases'
    ATTRIBUTION = 'attribution'
    RISK = 'risk'

@dataclass(frozen=True)
class ChainDefinition:
    chain_id: str
    display_name: str
    native_symbol: str
    family: ChainFamily
    adapter: type[ChainAdapter]
    capabilities: frozenset[Capability]
    native_decimals: int
    evm_compatible: bool = False

    def __post_init__(self):
        if not isinstance(self.chain_id,str) or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}', self.chain_id):
            raise ValueError('Invalid chain ID')
        if not isinstance(self.display_name,str) or not self.display_name.strip() or not isinstance(self.native_symbol,str) or not self.native_symbol.strip() or not isinstance(self.family,ChainFamily):
            raise ValueError('Invalid chain descriptor')
        if not isinstance(self.capabilities,frozenset) or any(not isinstance(c,Capability) for c in self.capabilities):
            raise ValueError('Typed capabilities required')
        if type(self.native_decimals) is not int or not 0 <= self.native_decimals <= 36:
            raise ValueError('Invalid native precision')
        if not isinstance(self.adapter,type) or not issubclass(self.adapter,ChainAdapter) or self.adapter.chain != self.chain_id:
            raise ValueError('Matching chain adapter required')
        required={Capability.BALANCE:'lookup_address',Capability.TRANSACTION_HISTORY:'transactions',
                  Capability.TRANSACTION_LOOKUP:'lookup_transaction',Capability.MONITORING:'monitoring_interval'}
        for capability,method in required.items():
            if capability in self.capabilities and getattr(self.adapter,method) is getattr(ChainAdapter,method):
                raise ValueError('Capability requires adapter implementation: '+method)
        dependencies={Capability.MONITORING:{Capability.BALANCE,Capability.TRANSACTION_HISTORY,Capability.RISK},
                      Capability.COUNTERPARTIES:{Capability.TRANSACTION_HISTORY},
                      Capability.TOKEN_TRANSFERS:{Capability.TRANSACTION_HISTORY},
                      Capability.PENDING_TRANSACTIONS:{Capability.TRANSACTION_HISTORY}}
        if Capability.ADDRESS_VALIDATION not in self.capabilities or not getattr(self.adapter,'address_pattern',None):
            raise ValueError('Address validation required')
        if Capability.TRANSACTION_LOOKUP in self.capabilities and not getattr(self.adapter,'transaction_pattern',None):
            raise ValueError('Transaction identification required')
        if any(c in self.capabilities and not needs <= self.capabilities for c,needs in dependencies.items()):
            raise ValueError('Inconsistent chain capabilities')
        if self.evm_compatible and self.family != ChainFamily.ACCOUNT:
            raise ValueError('EVM requires account family')

    def require(self,*capabilities):
        if not set(capabilities) <= self.capabilities: raise UnsupportedCapability()
        return self

    def public_metadata(self):
        return dict(id=self.chain_id,display_name=self.display_name,native_symbol=self.native_symbol,
                    family=self.family.value,evm_compatible=self.evm_compatible,native_decimals=self.native_decimals,
                    capabilities=[c.value for c in Capability if c in self.capabilities],
                    address_case=self.adapter.address_case)

class ChainRegistry:
    def __init__(self,definitions=()):
        self._definitions={}
        for definition in definitions:self.register(definition)
    def register(self,definition):
        if not isinstance(definition,ChainDefinition):raise ValueError('Typed chain definition required')
        if definition.chain_id in self._definitions:raise ValueError('Duplicate chain ID')
        self._definitions[definition.chain_id]=definition
    def get_chain(self,chain_id):
        if not isinstance(chain_id,str) or chain_id not in self._definitions:raise ChainError()
        return self._definitions[chain_id]
    def list_chains(self):return tuple(self._definitions.values())
    def is_supported_chain(self,chain_id):return isinstance(chain_id,str) and chain_id in self._definitions
    def get_chain_capabilities(self,chain_id):return self.get_chain(chain_id).capabilities
    def adapter(self,chain_id,*capabilities):return self.get_chain(chain_id).require(*capabilities).adapter()

def _builtins():
    from .bitcoin import BitcoinAdapter
    from .ethereum import EthereumAdapter
    common=frozenset({Capability.ADDRESS_VALIDATION,Capability.BALANCE,
        Capability.TRANSACTION_HISTORY,Capability.TRANSACTION_LOOKUP,Capability.COUNTERPARTIES,
        Capability.GRAPH,Capability.MONITORING,Capability.DISCOVERY,Capability.LABELS,
        Capability.CASES,Capability.ATTRIBUTION,Capability.RISK})
    return ChainRegistry((
        ChainDefinition('bitcoin','Bitcoin','BTC',ChainFamily.UTXO,BitcoinAdapter,common|{Capability.PENDING_TRANSACTIONS},8),
        ChainDefinition('ethereum','Ethereum','ETH',ChainFamily.ACCOUNT,EthereumAdapter,common|{Capability.TOKEN_TRANSFERS},18,True)))

REGISTRY=_builtins()
def get_chain(chain_id):return REGISTRY.get_chain(chain_id)
def list_chains():return REGISTRY.list_chains()
def is_supported_chain(chain_id):return REGISTRY.is_supported_chain(chain_id)
def get_chain_capabilities(chain_id):return REGISTRY.get_chain_capabilities(chain_id)
def wallet_identity(chain,address):return chain,get_chain(chain).adapter().normalize_address(address)
def transaction_identity(chain,tx_hash):return chain,get_chain(chain).adapter().normalize_transaction_id(tx_hash)
