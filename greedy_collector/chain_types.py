"""Lazy schema validators avoid importing providers while defining transport models."""
from typing import Annotated
from pydantic import AfterValidator

def supported_chain(value):
    from .chains import get_chain
    return get_chain(value).chain_id

def label_chain(value):return value if value == 'any' else supported_chain(value)

class RegistrySchema:
    """Document current registry choices without a hard-coded schema enum."""
    def __init__(self,any_scope=False):self.any_scope=any_scope
    def __get_pydantic_json_schema__(self,core_schema,handler):
        from .chains import list_chains
        return {**handler(core_schema),'enum':[d.chain_id for d in list_chains()]+(['any'] if self.any_scope else [])}

ChainName=Annotated[str,AfterValidator(supported_chain),RegistrySchema()]
LabelChain=Annotated[str,AfterValidator(label_chain),RegistrySchema(any_scope=True)]
