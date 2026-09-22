"""Test-only ABI replies for mocked Universal Resolver eth_call."""
def encoded_reverse(name='alice.eth', resolver='11'*20, reverse_resolver='22'*20):
    raw=name.encode('utf-8')
    word=lambda n:n.to_bytes(32,'big')
    return '0x'+(word(96)+bytes(12)+bytes.fromhex(resolver)+bytes(12)+bytes.fromhex(reverse_resolver)+word(len(raw))+raw+bytes((-len(raw))%32)).hex()

def reply(name='alice.eth'):
    return {'jsonrpc':'2.0','id':1,'result':encoded_reverse(name)}
