import hashlib
import json
from datetime import timezone
from decimal import Decimal, InvalidOperation
from ..chains import get_chain, Capability
from ..chains.registry import ChainFamily, UnsupportedCapability

VERSION = "observed_flow_v1"
DISCLAIMER = "Observed blockchain relationships do not establish ownership, control, identity, transfer purpose or wrongdoing."
UTXO_CAVEAT = "Transaction connectivity only. Exact input-to-output value allocation cannot be established from this transaction alone."
CAPACITY_CAVEAT = "Observed path capacity is the smallest transfer on a homogeneous-asset path; it does not prove the same funds traversed the path."
MAX_ROWS = 5000
MAX_BYTES = 16 * 1024 * 1024
MAX_TARGETS = 1000
TIMEOUT = 5.0

class FlowError(ValueError):
    def __init__(self, message, status=422): super().__init__(message); self.status=status

def definition(chain):
    d=get_chain(chain).require(Capability.GRAPH, Capability.TRANSACTION_HISTORY)
    if d.family not in (ChainFamily.UTXO, ChainFamily.ACCOUNT): raise UnsupportedCapability()
    return d

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=True).encode()).hexdigest()

def iso(value):
    if value is None:return None
    return value.replace(tzinfo=value.tzinfo or timezone.utc).astimezone(timezone.utc).isoformat()

def amount(value):
    if not isinstance(value,(str,int)) or isinstance(value,bool) or len(str(value))>120:raise ValueError()
    try:result=Decimal(str(value))
    except InvalidOperation:raise ValueError() from None
    if not result.is_finite() or result<=0 or abs(result.adjusted())>255:raise ValueError()
    return result

def decimal_text(value):return format(value,'f')
