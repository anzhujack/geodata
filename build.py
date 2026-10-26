#!/usr/bin/env python3
"""Build V2Ray geosite.dat and geoip.dat from JSON source definitions."""
from __future__ import annotations
import argparse, hashlib, ipaddress, json, os, re, shutil, tempfile, urllib.error, urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# V2Ray Domain.Type values
PLAIN, REGEXP, ROOT_DOMAIN, FULL = 0, 1, 2, 3

class BuildError(ValueError): pass

def varint(n: int) -> bytes:
    out=bytearray()
    while n>127: out.append((n&127)|128); n >>= 7
    out.append(n); return bytes(out)

def read_varint(data: bytes, pos: int) -> tuple[int,int]:
    n=0; shift=0
    while pos<len(data):
        b=data[pos]; pos+=1; n |= (b&127)<<shift
        if not b&128: return n,pos
        shift += 7
        if shift>70: raise BuildError('invalid protobuf varint')
    raise BuildError('truncated protobuf varint')

def fields(data: bytes):
    p=0
    while p<len(data):
        key,p=read_varint(data,p); no,wt=key>>3,key&7
        if not no: raise BuildError('invalid protobuf field number')
        if wt==0: v,p=read_varint(data,p); yield no,wt,v
        elif wt==1:
            if p+8>len(data): raise BuildError('truncated fixed64')
            yield no,wt,data[p:p+8]; p+=8
        elif wt==2:
            n,p=read_varint(data,p)
            if p+n>len(data): raise BuildError('truncated protobuf bytes')
            yield no,wt,data[p:p+n]; p+=n
        elif wt==5:
            if p+4>len(data): raise BuildError('truncated fixed32')
            yield no,wt,data[p:p+4]; p+=4
        else: raise BuildError(f'unsupported protobuf wire type {wt}')

def fbytes(no:int, val:bytes)->bytes: return varint(no<<3|2)+varint(len(val))+val

def decode_domain(raw:bytes):
    typ=0; value=''; attrs=[]
    for no,wt,v in fields(raw):
        if no==1 and wt==0: typ=int(v)
        elif no==2 and wt==2: value=v.decode('utf-8')
        elif no==3 and wt==2: attrs.append(bytes(v))
    if typ not in (PLAIN, REGEXP, ROOT_DOMAIN, FULL): raise BuildError(f'unknown Domain type: {typ}')
    return typ,value,tuple(sorted(attrs))

def encode_domain(d):
    typ,value,attrs=d
    out=varint(8)+varint(typ)+fbytes(2,value.encode())
    for a in attrs: out += fbytes(3,a)
    return out

def decode_geosite(data:bytes)->dict[str,list[tuple]]:
    out={}
    # top-level GeoSiteList: repeated entry field 1; entry has code=1 domains=2
    for no,wt,raw in fields(data):
        if no!=1 or wt!=2: continue
        code=None; ds=[]
        for en,ew,ev in fields(raw):
            if en==1 and ew==2: code=ev.decode().lower()
            elif en==2 and ew==2: ds.append(decode_domain(ev))
        if code is not None: out[code]=ds
    return out

def decode_cidr(raw:bytes):
    ip=b''; prefix=0
    for no,wt,v in fields(raw):
        if no==1 and wt==2: ip=bytes(v)
        elif no==2 and wt==0: prefix=int(v)
    if len(ip) not in (4,16): raise BuildError('invalid CIDR IP length')
    return ipaddress.ip_network((ip,prefix), strict=False)

def decode_geoip(data:bytes):
    out={}
    # top-level GeoIPList: repeated entry field 1; entry code=1 cidr=2 inverse=3
    for no,wt,raw in fields(data):
        if no!=1 or wt!=2: continue
        code=None; cs=[]; inv=False
        for en,ew,ev in fields(raw):
            if en==1 and ew==2: code=ev.decode().lower()
            elif en==2 and ew==2: cs.append(decode_cidr(ev))
            elif en==3 and ew==0: inv=bool(ev)
        if code is not None: out[code]=(cs,inv)
    return out

def normalize_domain(value:str, typ:int)->str:
    value=value.strip()
    if typ==REGEXP: return value
    if typ==PLAIN: return value.lower()
    value=value.rstrip('.')
    try: return value.encode('idna').decode().lower()
    except UnicodeError: return value.lower()

def domain_key(d): return (d[0],d[1],d[2])

def clash_parse(text:str, target:str):
    domains=[]; cidrs=[]; skipped={}
    known={'DOMAIN':FULL,'DOMAIN-SUFFIX':ROOT_DOMAIN,'DOMAIN-KEYWORD':PLAIN,'DOMAIN-REGEX':REGEXP,
           'IP-CIDR':None,'IP-CIDR6':None}
    unsupported={'GEOIP','DST-PORT','SRC-IP-CIDR','SRC-PORT','PROCESS-NAME','PROCESS-PATH','MATCH','NETWORK','RULE-SET','AND','NOT','OR','IP-ASN','IP-SUFFIX','DOMAIN-WILDCARD','URL-REGEX','URL-REJECT','DSCP','IN-PORT','SRC-IP'}
    for line in text.splitlines():
        line=line.strip()
        if not line or line.startswith(('#', '//')): continue
        parts=[x.strip() for x in line.split(',', 1)]; rule=parts[0].upper()
        if rule not in known:
            if rule in unsupported:
                skipped[rule]=skipped.get(rule,0)+1; continue
            raise BuildError(f'unknown Clash rule type: {rule}')
        if len(parts)<2 or not parts[1]: raise BuildError(f'missing value for Clash rule {rule}')
        val=parts[1] if rule=='DOMAIN-REGEX' else parts[1].split(',',1)[0].strip()
        if rule.startswith('DOMAIN'):
            domains.append((known[rule],normalize_domain(val,known[rule]),()))
        else:
            try: cidrs.append(ipaddress.ip_network(val,strict=False))
            except ValueError as e: raise BuildError(f'invalid CIDR: {val}') from e
    return domains,cidrs,skipped

def custom_domains(root:Path, tag:str):
    add=[]; rem=[]; d=root/'custom'/'geosite'
    for suffix,out in [('.add.txt',add),('.remove.txt',rem)]:
        p=d/(tag+suffix)
        if not p.exists(): continue
        for line in p.read_text(encoding='utf-8').splitlines():
            line=line.strip()
            if not line or line.startswith('#'): continue
            typ=ROOT_DOMAIN; val=line
            for prefix,t in [('full:',FULL),('domain:',ROOT_DOMAIN),('keyword:',PLAIN),('regexp:',REGEXP)]:
                if line.lower().startswith(prefix): typ=t; val=line[len(prefix):]; break
            out.append((typ,normalize_domain(val,typ),()))
    return add,rem

def custom_geoip(root:Path, tag:str):
    add=[]; rem=[]; d=root/'custom'/'geoip'
    for suffix,out in [('.add.txt',add),('.remove.txt',rem)]:
        p=d/(tag+suffix)
        if p.exists():
            for line in p.read_text(encoding='utf-8').splitlines():
                line=line.split('#',1)[0].strip()
                if line:
                    try: out.append(ipaddress.ip_network(line,strict=False))
                    except ValueError as e: raise BuildError(f'invalid custom CIDR: {line}') from e
    return add,rem

def fetch(url:str, cache:dict):
    if url in cache: return cache[url]
    last=None
    for i in range(3):
        try:
            req=urllib.request.Request(url,headers={'User-Agent':'personal-geodata/1.0'})
            with urllib.request.urlopen(req,timeout=20) as r: b=r.read()
            cache[url]=b; return b
        except (OSError,urllib.error.URLError) as e: last=e
    raise BuildError(f'failed to fetch {url}: {last}')

def load_source(spec, cache):
    raw=fetch(spec['url'],cache)
    fmt=spec.get('format','geosite')
    if fmt=='clash': return ('clash',raw.decode('utf-8'))
    if fmt=='geosite': return ('geosite',decode_geosite(raw))
    if fmt=='geoip': return ('geoip',decode_geoip(raw))
    raise BuildError(f'unsupported source format: {fmt}')

def build(config:dict, output:Path):
    root=Path(config.get('_root','.')); sources=config.get('sources',{}); cache={}; loaded={}; skipped={}
    for sid,spec in sources.items(): loaded[sid]=load_source(spec,cache)
    result_g={}; result_i={}
    for kind in ('geosite','geoip'):
        for tag, refs in config.get(kind,{}).items():
            vals_d=[]; vals_i=[]
            for ref in refs:
                sid=ref['source']; up=ref.get('tag',tag); fmt,payload=loaded[sid]; sk={}
                if kind=='geosite':
                    if fmt=='clash': d,_,sk=clash_parse(payload,'geosite'); vals_d += d
                    elif fmt=='geosite':
                        if up.lower() not in payload: raise BuildError(f'missing geosite tag {up} in {sid}')
                        vals_d += payload[up.lower()]
                    else: raise BuildError(f'geoip source {sid} used for geosite')
                else:
                    if fmt=='clash': _,c,sk=clash_parse(payload,'geoip'); vals_i += c
                    elif fmt=='geoip':
                        if up.lower() not in payload: raise BuildError(f'missing geoip tag {up} in {sid}')
                        c,inv=payload[up.lower()]
                        if inv: raise BuildError(f'inverse geoip source {sid}:{up} is unsupported')
                        vals_i += c
                    else: raise BuildError(f'geosite source {sid} used for geoip')
                for k,v in sk.items():
                    key=f'{sid}:{k}'
                    if key not in skipped: skipped[key]=v
            if kind=='geosite':
                a,r=custom_domains(root,tag); vals_d += a; remove={(x[0],x[1]) for x in r}
                vals_d=[x for x in vals_d if (x[0],normalize_domain(x[1],x[0])) not in remove]
                vals_d=sorted(set((t,normalize_domain(v,t),tuple(sorted(a))) for t,v,a in vals_d),key=domain_key)
                if not vals_d: raise BuildError(f'requested geosite tag is empty: {tag}')
                result_g[tag.lower()]=vals_d
            else:
                a,r=custom_geoip(root,tag); vals_i += a; vals_i=[x for x in vals_i if x not in set(r)]
                vals_i=list(ipaddress.collapse_addresses([n for n in set(vals_i) if n.version==4])) + list(ipaddress.collapse_addresses([n for n in set(vals_i) if n.version==6]))
                vals_i=sorted(vals_i,key=lambda n:(n.version,int(n.network_address),n.prefixlen))
                if not vals_i: raise BuildError(f'requested geoip tag is empty: {tag}')
                result_i[tag.lower()]=vals_i
    # aliases point to copied output tags
    for kind,res in [('geosite',result_g),('geoip',result_i)]:
        for alias,tag in config.get('aliases',{}).get(kind,{}).items():
            if tag.lower() not in res: raise BuildError(f'alias target missing: {kind}:{tag}')
            res[alias.lower()]=res[tag.lower()]
    gs=bytearray(); gi=bytearray()
    for tag,ds in sorted(result_g.items()):
        body=fbytes(1,tag.encode())+b''.join(fbytes(2,encode_domain(d)) for d in ds); gs += fbytes(1,body)
    gi=bytearray()
    for tag,cs in sorted(result_i.items()):
        body=fbytes(1,tag.encode())
        for n in cs:
            cidr=fbytes(1,n.network_address.packed)+varint(16)+varint(n.prefixlen)
            body += fbytes(2,cidr)
        gi += fbytes(1,body)
    overlap=[]
    if 'cn' in result_g and 'proxy' in result_g:
        common=set(result_g['cn']) & set(result_g['proxy'])
        overlap=[{'type':t,'value':v,'attrs':[a.hex() for a in attrs]} for t,v,attrs in sorted(common,key=domain_key)]
    manifest={'sources':{sid:{'url':s['url'],'sha256':hashlib.sha256(fetch(s['url'],cache)).hexdigest()} for sid,s in sources.items()},'counts':{'geosite':{k:len(v) for k,v in result_g.items()},'geoip':{k:len(v) for k,v in result_i.items()}},'skipped':skipped,'overlaps':overlap}
    # Validate the complete in-memory wire output before replacing any artifact.
    if decode_geosite(bytes(gs)) != result_g:
        raise BuildError('geosite round-trip verification failed')
    expected_i={tag:(networks,False) for tag,networks in result_i.items()}
    if decode_geoip(bytes(gi)) != expected_i:
        raise BuildError('geoip round-trip verification failed')
    output.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.staging-',dir=output.parent))
    try:
        (stage/'geosite.dat').write_bytes(gs); (stage/'geoip.dat').write_bytes(gi)
        (stage/'manifest.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        sums=''.join(f'{hashlib.sha256((stage/n).read_bytes()).hexdigest()}  {n}\n' for n in ('geosite.dat','geoip.dat','manifest.json'))
        (stage/'sha256sums.txt').write_text(sums,encoding='utf-8')
        for n in ('geosite.dat','geoip.dat','manifest.json','sha256sums.txt'): os.replace(stage/n,output/n)
    finally:
        shutil.rmtree(stage,ignore_errors=True)
    # reread and verify requested tags
    if not decode_geosite((output/'geosite.dat').read_bytes()) and result_g: raise BuildError('geosite verification failed')
    if not decode_geoip((output/'geoip.dat').read_bytes()) and result_i: raise BuildError('geoip verification failed')
    return manifest

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--config',default='sources.json'); ap.add_argument('--output',default='dist'); ns=ap.parse_args(argv)
    cfg=json.loads(Path(ns.config).read_text(encoding='utf-8')); cfg['_root']=str(Path(ns.config).resolve().parent)
    build(cfg,Path(ns.output))
if __name__=='__main__': main()
