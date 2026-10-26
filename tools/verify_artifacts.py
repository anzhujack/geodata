"""Optional independent verification; requires protobuf and PyYAML (not build dependencies)."""
import hashlib
import json
from pathlib import Path
from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
import yaml

root = Path(__file__).resolve().parents[1]
schema = descriptor_pb2.FileDescriptorProto(name='geodata-validation.proto', package='validation', syntax='proto3')

def message(name):
    return schema.message_type.add(name=name)

def field(msg, name, number, typ, repeated=False, type_name=None):
    f = msg.field.add(name=name, number=number, type=typ, label=3 if repeated else 1)
    if type_name:
        f.type_name = '.validation.' + type_name

attribute = message('Attribute')
field(attribute, 'key', 1, 9)
# No oneof needed for read-only inspection; the wire numbers match the official schema.
field(attribute, 'bool_value', 2, 8)
field(attribute, 'int_value', 3, 3)
domain = message('Domain')
field(domain, 'type', 1, 5)
field(domain, 'value', 2, 9)
field(domain, 'attribute', 3, 11, True, 'Attribute')
site = message('GeoSite')
field(site, 'country_code', 1, 9)
field(site, 'domain', 2, 11, True, 'Domain')
sites = message('GeoSiteList')
field(sites, 'entry', 1, 11, True, 'GeoSite')
cidr = message('CIDR')
field(cidr, 'ip', 1, 12)
field(cidr, 'prefix', 2, 13)
ip = message('GeoIP')
field(ip, 'country_code', 1, 9)
field(ip, 'cidr', 2, 11, True, 'CIDR')
field(ip, 'reverse_match', 3, 8)
ips = message('GeoIPList')
field(ips, 'entry', 1, 11, True, 'GeoIP')
pool = descriptor_pool.DescriptorPool()
pool.Add(schema)
manifest = json.loads((root / 'dist/manifest.json').read_text(encoding='utf-8'))
for line in (root / 'dist/sha256sums.txt').read_text().splitlines():
    expected, name = line.split()
    assert name in ('geosite.dat', 'geoip.dat', 'manifest.json')
    assert hashlib.sha256((root / 'dist' / name).read_bytes()).hexdigest() == expected, name

report = {}
for kind, msg_name, item_name in [('geosite', 'GeoSiteList', 'domain'), ('geoip', 'GeoIPList', 'cidr')]:
    cls = message_factory.GetMessageClass(pool.FindMessageTypeByName('validation.' + msg_name))
    parsed = cls.FromString((root / 'dist' / (kind + '.dat')).read_bytes())
    tags = [entry.country_code.lower() for entry in parsed.entry]
    assert len(tags) == len(set(tags)), 'Duplicate tag'
    counts = {}
    for entry in parsed.entry:
        items = getattr(entry, item_name)
        assert items
        counts[entry.country_code.lower()] = len(items)
        for item in items:
            if kind == 'geosite':
                assert item.type in range(4)
                assert item.value
            else:
                assert len(item.ip) in (4, 16)
                assert 0 <= item.prefix <= (32 if len(item.ip) == 4 else 128)
                assert not entry.reverse_match
    assert counts == manifest['counts'][kind]
    report[kind] = {'tags': len(tags), 'entries': sum(counts.values())}

workflow = yaml.load((root / '.github/workflows/build.yml').read_text(), Loader=yaml.BaseLoader)
assert workflow['on']['schedule'][0]['cron'] == '30 0 * * *'
assert workflow['jobs']['publish']['needs'] == 'build'
print(json.dumps({'independent_protobuf_validation': 'passed', 'checksums': 'passed', 'workflow_yaml': 'passed', **report}, indent=2))
