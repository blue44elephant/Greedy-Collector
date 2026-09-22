"""Synthetic GraphSense packs and official-API envelopes, tests only."""
import base64
import hashlib
import yaml

REPO='graphsense/graphsense-tagpacks'
ETH='0x'+'ab'*20

def pack(address=ETH,currency='ETH',**overrides):
    return {'title':'Synthetic public pack','creator':'Test publisher','currency':currency,
        'category':'exchange','confidence':'service_data','actor':'synthetic-actor',
        'lastmod':'2026-09-01','is_cluster_definer':True,
        'source':'https://source.example.test/public','label':'Synthetic service A',
        'tags':[{'address':address},{'address':'0x'+'cd'*20}],**overrides}

def material(value,path='packs/test.yaml'):
    content=value if isinstance(value,bytes) else yaml.safe_dump(value).encode('utf8')
    sha=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
    item={'repository':{'id':123,'full_name':REPO,'private':False,'visibility':'public'},
        'path':path,'sha':sha,'html_url':'https://github.com/'+REPO+'/blob/master/'+path}
    blob={'sha':sha,'encoding':'base64','size':len(content),'content':base64.b64encode(content).decode()}
    return item,blob

def search(items,incomplete=False,total=None):
    return {'items':items,'total_count':len(items) if total is None else total,'incomplete_results':incomplete}
