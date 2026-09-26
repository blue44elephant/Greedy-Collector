"""Local adapter syntax resolution. No provider retrieval or secret reflection."""
from .chains import Capability
from .chains import registry as chains

def resolve_identifier(value: str, chain_hint: str | None = None, *, registry=None) -> dict:
    registry=registry or chains.REGISTRY
    definitions=(registry.get_chain(chain_hint),) if chain_hint is not None else registry.list_chains()
    normalized=value.strip()
    matches=[]
    # Keep transaction precedence, including the existing permissive BTC syntax.
    for definition in definitions:
        adapter=definition.adapter()
        if (Capability.TRANSACTION_LOOKUP in definition.capabilities
                and (chain_hint is not None or adapter.resolve_unqualified_transactions)
                and adapter.identify_transaction(normalized)):
            matches.append(dict(kind='transaction',chain=definition.chain_id,
                                normalized=adapter.normalize_transaction_id(normalized),lookup_type='transaction'))
    if not matches:
        for definition in definitions:
            try:address=definition.adapter().validate_address(normalized)
            except ValueError:continue
            # Preserve resolver response spelling; persistence uses normalize_address.
            matches.append(dict(kind='address',chain=definition.chain_id,normalized=address,lookup_type='address'))
    if len(matches)==1:return matches[0]
    if matches and chain_hint is None:
        # EVM syntax is shared across networks. Keep Ethereum mainnet as the
        # compatibility default; a non-Ethereum network requires an explicit hint.
        evm_matches=[m for m in matches if registry.get_chain(m['chain']).evm_compatible]
        if len(evm_matches)==len(matches):
            default=next((m for m in evm_matches if m['chain']=='ethereum'),None)
            if default:return default
    if matches:return dict(kind='ambiguous',possibilities=[dict(chain=m['chain'],kind=m['kind']) for m in matches],message='Specify a chain for this identifier.')
    supported=[d.display_name+' address' for d in registry.list_chains()]
    supported += [d.display_name+' '+getattr(d.adapter,'transaction_identifier_name',
                  'transaction '+('hash' if d.adapter.transaction_pattern.pattern.startswith('0x') else 'ID'))
                  for d in registry.list_chains() if Capability.TRANSACTION_LOOKUP in d.capabilities]
    return dict(kind='unknown',supported=supported,message='Greedy Collector could not identify this value as a supported wallet address or transaction hash.')
