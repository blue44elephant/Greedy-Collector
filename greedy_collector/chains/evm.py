"""EVM syntax only: no network, mainnet configuration, ENS or token parsing."""
import re
from .base import ChainAdapter

class EvmAdapter(ChainAdapter):
    address_pattern = re.compile(r'^0x[a-fA-F0-9]{40}$')
    transaction_pattern = re.compile(r'0x[0-9a-fA-F]{64}')
    address_case = 'insensitive'
    def address_key(self,address):return address.strip().lower()
    def address_case_insensitive(self,address):return True
