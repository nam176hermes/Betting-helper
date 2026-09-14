"""Normalize inherited $ref anchors to equivalent pointers without changing constraints."""
from pathlib import Path
import hashlib
import json
import sys
sys.dont_write_bytecode=True
P=Path(__file__).resolve().parents[1]
BASE=Path('/home/thenam176/betting-helper/discovery-runtime/vendor/hybrid-discovery-v6.2/schemas')

def normalized():
    docs={p.name:json.loads(p.read_text()) for p in BASE.glob('*.schema.json')}
    byid={d['$id']:d for d in docs.values()};anchor_maps={}
    for d in docs.values():
        anchors={}
        def scan(x,ptr=''):
            if isinstance(x,dict):
                if '$anchor' in x:anchors[x['$anchor']]=ptr
                for k,v in x.items():scan(v,ptr+'/'+k.replace('~','~0').replace('/','~1'))
            elif isinstance(x,list):
                for i,v in enumerate(x):scan(v,ptr+'/'+str(i))
        scan(d);anchor_maps[d['$id']]=anchors
    changes=[]
    for name,d in docs.items():
        def walk(x):
            if isinstance(x,dict):
                if '$ref' in x:
                    ref=x['$ref'];location,sep,fragment=ref.partition('#')
                    if fragment and not fragment.startswith('/'):
                        target=location or d['$id'];pointer=anchor_maps[target][fragment]
                        x['$ref']=location+'#'+pointer;changes.append({'schema':name,'before':ref,'after':x['$ref']})
                for v in x.values():walk(v)
            elif isinstance(x,list):
                for v in x:walk(v)
        walk(d)
    return docs,changes

if __name__=='__main__':
    docs,changes=normalized();mapping=json.loads((P/'docs/registries/normative-source-map.v1.json').read_text())
    for name,d in docs.items():
        path='docs/inherited/v6.2/schemas/'+name;b=(json.dumps(d,indent=2,ensure_ascii=False)+'\n').encode();(P/path).write_bytes(b)
        row=next(r for r in mapping['inherited_entries'] if r['plan_source']==path)
        row['plan_sha256']=hashlib.sha256(b).hexdigest();row['protocol_compatibility']='EQUIVALENT_SCHEMA_POINTER_NORMALIZATION'
    (P/'docs/registries/normative-source-map.v1.json').write_text(json.dumps(mapping,indent=2)+'\n')
    (P/'docs/registries/schema-pointer-normalization.v1.json').write_text(json.dumps({'schema_version':'schema-pointer-normalization/v1','owner_phase':'MIG0','source_root':str(BASE),'changes':changes,'rule':'Only $ref anchor spelling changes; constraints, $ids, $anchors, protocol domains and vector hashes do not change.'},indent=2)+'\n')
    print('normalized reference occurrences',len(changes))
