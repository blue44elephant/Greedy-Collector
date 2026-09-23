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
        if Capability.TRANSACTION_LOOKUP in definition.capabilities and adapter.identify_transaction(normalized):
            matches.append(dict(kind='transaction',chain=definition.chain_id,
                                normalized=adapter.normalize_transaction_id(normalized),lookup_type='transaction'))
    if not matches:
        for definition in definitions:
            try:address=definition.adapter().validate_address(normalized)
            except ValueError:continue
            # Preserve resolver response spelling; persistence uses normalize_address.
            matches.append(dict(kind='address',chain=definition.chain_id,normalized=address,lookup_type='address'))
    if len(matches)==1:return matches[0]
    if matches:return dict(kind='ambiguous',possibilities=[dict(chain=m['chain'],kind=m['kind']) for m in matches],message='Specify a chain for this identifier.')
    supported=[d.display_name+' address' for d in registry.list_chains()]
    supported += [d.display_name+' transaction '+('hash' if d.adapter.transaction_pattern.pattern.startswith('0x') else 'ID')
                  for d in registry.list_chains() if Capability.TRANSACTION_LOOKUP in d.capabilities]
    return dict(kind='unknown',supported=supported,message='Greedy Collector could not identify this value as a supported wallet address or transaction hash.')
