"""One bounded Ethereum primary-name read, using Universal Resolver verification.

No CCIP client, forward re-query, text records, history, or naming-root executor.
"""
import asyncio
from datetime import datetime, timezone
import re

from ..chains.ethereum import EthereumAdapter
from ..chains.base import RpcReadError
from ..config import get_settings
from .ens_normalization import normalize_ens_name, probe_ens_normalizer, EnsNormalizationError, MAX_NAME_BYTES
from .executors import ExecutionSignal
from .schemas import Batch

UNIVERSAL_RESOLVER = '0xeEeEEEeE14D718C2B47D9923Deab1335E144EeEe'
ETHEREUM_COIN_TYPE = 60
# First four bytes of keccak256("reverse(bytes,uint256)"). Fixed ABI only.
REVERSE_SELECTOR = '5d78a217'
TRANSFORM_ID = 'wallet.ens_primary_name'
SOURCE_ID = 'ens_ethereum'
VERIFICATION_METHOD = 'universal_resolver_reverse'
_REVERTS = {
    '0xef9c03ce':'reverse_forward_mismatch',
    '0x556f1830':'ccip_read_unsupported',
    '0x77209fe8':'resolver_not_found',
    '0x1e9535f2':'resolver_not_contract',
    '0x7b1c461b':'unsupported_resolver_profile',
    '0x95c0c752':'resolver_error',
    '0x01800152':'resolver_error',
}


def configured():
    return bool(get_settings().alchemy_api_key) and probe_ens_normalizer().usable


def reverse_calldata(wallet):
    address=EthereumAdapter().validate_address(wallet)
    word=lambda value:value.to_bytes(32,'big')
    return '0x'+REVERSE_SELECTOR+(word(64)+word(ETHEREUM_COIN_TYPE)+word(20)+bytes.fromhex(address[2:])+bytes(12)).hex()


def decode_reverse(value):
    """Strict ABI tuple (string,address,address), capped at 2048 name bytes.

    Require canonical offset, address padding, string padding and exact length.
    Never allocate using untrusted ABI lengths or accept trailing payloads.
    """
    try:
        if not isinstance(value,str) or len(value)>2+2*(128+MAX_NAME_BYTES) or not re.fullmatch(r'0x(?:[0-9a-fA-F]{2})+',value):raise ValueError()
        data=bytes.fromhex(value[2:])
        if len(data)<128 or len(data)%32 or int.from_bytes(data[:32],'big')!=96:raise ValueError()
        if any(data[32:44]) or any(data[64:76]):raise ValueError()
        size=int.from_bytes(data[96:128],'big')
        if size>MAX_NAME_BYTES or len(data)!=128+((size+31)//32)*32 or any(data[128+size:]):raise ValueError()
        name=data[128:128+size].decode('utf-8',errors='strict')
        return name,'0x'+data[44:64].hex(),'0x'+data[76:96].hex()
    except (ValueError,UnicodeError):
        raise ExecutionSignal('invalid_provider_response',{'diagnostic':'malformed_abi'}) from None


class EnsPrimaryNameExecutor:
    async def execute(self, context):
        context.checkpoint()
        if context.subject.get('kind')!='blockchain_address' or context.subject.get('namespace')!='ethereum':
            raise ExecutionSignal('invalid_provider_response')
        if not configured():raise ExecutionSignal('configuration_unavailable',{'diagnostic':'ens_configuration_unavailable'})
        wallet=context.subject['canonical_value']
        adapter=EthereumAdapter()
        try:
            value=await context.request(lambda:adapter._alchemy('eth_call',[
                {'to':UNIVERSAL_RESOLVER,'data':reverse_calldata(wallet)},'latest'],bounded=True))
        except RpcReadError as exc:
            diagnostic=_REVERTS.get(exc.selector)
            if diagnostic:
                return Batch(records=[],coverage='provider_incomplete',quota={'diagnostic':diagnostic})
            raise ExecutionSignal(exc.category,{'diagnostic':'rpc_error'}) from None
        name,resolver,reverse_resolver=decode_reverse(value)
        if not name:return Batch(records=[],coverage='bounded',quota={'diagnostic':'empty_primary_name'})
        try:
            normalized=await asyncio.to_thread(normalize_ens_name,name)
        except EnsNormalizationError as exc:
            category='configuration_unavailable' if exc.error_type=='normalizer_unavailable' else 'timeout' if exc.error_type=='normalizer_timeout' else 'invalid_provider_response'
            raise ExecutionSignal(category,{'diagnostic':exc.error_type}) from None
        context.checkpoint()
        # ENSIP-19 requires an already-normalized reverse name. Verification of
        # the raw spelling must not be transferred to a different normalized name.
        if normalized!=name:raise ExecutionSignal('invalid_provider_response',{'diagnostic':'invalid_ens_name'})
        if resolver=='0x'+'0'*40 or reverse_resolver=='0x'+'0'*40:
            raise ExecutionSignal('invalid_provider_response',{'diagnostic':'malformed_abi'})
        now=datetime.now(timezone.utc)
        provenance=dict(primary_name=normalized,wallet=wallet,namespace='ethereum',coin_type=ETHEREUM_COIN_TYPE,
            universal_resolver=UNIVERSAL_RESOLVER,resolver=resolver,reverse_resolver=reverse_resolver,
            verification='forward_verified',verification_method=VERIFICATION_METHOD,provider='alchemy',schema_version=1)
        return Batch(records=[{'kind':'candidate_relationship','predicate':'resolves_to',
            'from':{'kind':'ens_name','namespace':'ethereum','value':normalized},
            'to':{'kind':'blockchain_address','namespace':'ethereum','value':wallet},'fact_key':{},
            'observation':{'kind':'name_service_record','source_record_key':wallet,
                'source_locator':'ethereum:mainnet:universal-resolver:'+UNIVERSAL_RESOLVER,
                'title':'ENS primary name: '+normalized[:220],
                'summary':'At observation time, ENS primary-name resolution returned this name and verified its address relationship. This does not establish real-world identity or wallet control.',
                'verification':'technical_verified','match_context':{'verification':'forward_verified','verification_method':VERIFICATION_METHOD},
                'source_class':'public_blockchain','retrieved_at':now,'source_snapshot':provenance}}],coverage='bounded')


def verified_material(result, observation, source, wallet, endpoint):
    """Stored technical provenance gate shared by graph and explicit promotion.

    Read-only: no RPC or re-normalization of immutable historical material.
    """
    snapshot=observation.source_snapshot
    return bool(endpoint and (source.transform_id,source.source_id,source.transform_version,source.source_version)==(TRANSFORM_ID,SOURCE_ID,1,1)
        and (result.kind,result.predicate,observation.kind,observation.verification)==('candidate_relationship','resolves_to','name_service_record','technical_verified')
        and (endpoint.kind,endpoint.namespace)==('ens_name','ethereum')
        and (wallet.kind,wallet.namespace)==('blockchain_address','ethereum')
        and result.from_subject_id==endpoint.id and result.to_subject_id==wallet.id
        and snapshot.get('primary_name')==endpoint.canonical_value and snapshot.get('wallet')==wallet.canonical_value
        and snapshot.get('namespace')=='ethereum' and snapshot.get('coin_type')==ETHEREUM_COIN_TYPE
        and snapshot.get('universal_resolver')==UNIVERSAL_RESOLVER and snapshot.get('provider')=='alchemy'
        and all(snapshot.get(k)==v and observation.match_context.get(k)==v for k,v in
                [('verification','forward_verified'),('verification_method',VERIFICATION_METHOD)]))
