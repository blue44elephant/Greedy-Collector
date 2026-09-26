"""Descriptor-only adapters for supported non-Ethereum EVM networks."""
from .etherscan_v2 import EtherscanV2Adapter

class BaseAdapter(EtherscanV2Adapter):
    chain = "base"

class ArbitrumAdapter(EtherscanV2Adapter):
    chain = "arbitrum"

class BnbAdapter(EtherscanV2Adapter):
    chain = "bsc"

class PolygonAdapter(EtherscanV2Adapter):
    chain = "polygon"
