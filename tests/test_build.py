import importlib.util
import ipaddress
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('builder', Path(__file__).parents[1] / 'build.py')
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)


class BuildTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / 'dist'

    def tearDown(self):
        self.temp.cleanup()

    def source(self, name, data, fmt):
        path = self.root / name
        path.write_bytes(data)
        return {'url': path.as_uri(), 'format': fmt}

    def build(self, cfg):
        return b.build({**cfg, '_root': str(self.root)}, self.output)

    def site_source(self, domains):
        return self.site_bundle({'cn': domains})

    def site_bundle(self, tags):
        entries = []
        for tag, domains in tags.items():
            body = b.fbytes(1, tag.encode()) + b''.join(
                b.fbytes(2, b.encode_domain(d)) for d in domains
            )
            entries.append(b.fbytes(1, body))
        return b''.join(entries)

    def geoip_bundle(self, entries):
        payload = []
        for tag, networks, inverse in entries:
            body = b.fbytes(1, tag.encode())
            for network in networks:
                cidr = (
                    b.fbytes(1, network.network_address.packed)
                    + b'\x10' + b.varint(network.prefixlen)
                )
                body += b.fbytes(2, cidr)
            if inverse:
                body += b'\x18\x01'
            payload.append(b.fbytes(1, body))
        return b''.join(payload)

    def custom(self, name, text):
        path = self.root / 'custom' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')

    def test_keyword_explicit_zero_and_attributes(self):
        attr_a = b.fbytes(1, b'cn') + b'\x10\x01'
        attr_b = b.fbytes(1, b'ads') + b'\x10\x01'
        domains = [(0, 'Example.COM', (attr_a,)), (0, 'example.com', (attr_b,)), (0, 'example.com', (attr_a,))]
        cfg = {'sources': {'s': self.source('g.dat', self.site_source(domains), 'geosite')}, 'geosite': {'cn': [{'source': 's'}]}}
        self.build(cfg)
        got = b.decode_geosite((self.output / 'geosite.dat').read_bytes())['cn']
        self.assertEqual(len(got), 2)
        self.assertEqual({d[2] for d in got}, {(attr_a,), (attr_b,)})
        self.assertIn(b'\x08\x00', (self.output / 'geosite.dat').read_bytes())
        self.assertEqual(b.decode_domain(b.fbytes(2, b'keyword'))[0], 0)

    def test_removal_ignores_attributes_and_preserves_other_match_type(self):
        attr = b.fbytes(1, b'cn') + b'\x10\x01'
        domains = [(2, 'EXAMPLE.COM', (attr,)), (3, 'example.com', ())]
        cfg = {'sources': {'s': self.source('g.dat', self.site_source(domains), 'geosite')}, 'geosite': {'cn': [{'source': 's'}]}}
        self.custom('geosite/cn.remove.txt', 'domain:example.com\n')
        self.build(cfg)
        self.assertEqual(b.decode_geosite((self.output / 'geosite.dat').read_bytes())['cn'], [(3, 'example.com', ())])

    def test_regex_and_keyword_semantics(self):
        regex = r'^foo[0-9]{1,3}#\.$'
        ds, _, _ = b.clash_parse('DOMAIN-REGEX,' + regex + '\nDOMAIN-KEYWORD,Ads.\n', 'geosite')
        self.assertEqual(ds, [(1, regex, ()), (0, 'ads.', ())])
        self.custom('geosite/test.add.txt', 'regexp:' + regex + '\ndomain:example.com\n')
        adds, _ = b.custom_domains(self.root, 'test')
        self.assertEqual(adds, [(1, regex, ()), (2, 'example.com', ())])

    def test_cidr_collapse_preserves_v4_v6_coverage_and_skip_counts(self):
        text = b'DOMAIN,Example.COM\nIP-CIDR,192.0.2.0/25,no-resolve\nIP-CIDR,192.0.2.128/25\nIP-CIDR6,2001:db8::/126\nIP-ASN,1234\n'
        cfg = {'sources': {'s': self.source('c.list', text, 'clash')}, 'geosite': {'x': [{'source': 's'}]}, 'geoip': {'x': [{'source': 's'}]}}
        manifest = self.build(cfg)
        networks, inverse = b.decode_geoip((self.output / 'geoip.dat').read_bytes())['x']
        self.assertFalse(inverse)
        self.assertEqual(networks, [ipaddress.ip_network('192.0.2.0/24'), ipaddress.ip_network('2001:db8::/126')])
        self.assertEqual(manifest['skipped']['s:IP-ASN'], 1)

    def test_missing_tag_and_unknown_rules_fail_without_replacing_output(self):
        self.output.mkdir()
        (self.output / 'geosite.dat').write_bytes(b'previous-valid-version')
        cfg = {'sources': {'s': self.source('g.dat', self.site_source([(2, 'example.com', ())]), 'geosite')}, 'geosite': {'missing': [{'source': 's'}]}}
        with self.assertRaises(b.BuildError):
            self.build(cfg)
        self.assertEqual((self.output / 'geosite.dat').read_bytes(), b'previous-valid-version')
        for rule in ('TOTALLY-UNKNOWN', 'DOMAIN-UNKNOWN', 'IP-UNKNOWN'):
            with self.assertRaises(b.BuildError):
                b.clash_parse(rule + ',x', 'geosite')

    def test_inverse_geoip_rejected(self):
        cidr = b.fbytes(1, b'\xc0\x00\x02\x00') + b'\x10\x18'
        raw = b.fbytes(1, b.fbytes(1, b'x') + b.fbytes(2, cidr) + b'\x18\x01')
        cfg = {'sources': {'s': self.source('i.dat', raw, 'geoip')}, 'geoip': {'x': [{'source': 's'}]}}
        with self.assertRaises(b.BuildError):
            self.build(cfg)

    def test_aliases_and_custom_only_categories(self):
        self.custom('geosite/custom.add.txt', 'domain:example.com\n')
        self.custom('geoip/custom.add.txt', '192.0.2.0/24\n')
        cfg = {'sources': {}, 'geosite': {'custom': []}, 'geoip': {'custom': []}, 'aliases': {'geosite': {'alias': 'custom'}}}
        manifest = self.build(cfg)
        self.assertEqual(manifest['counts']['geosite'], {'custom': 1, 'alias': 1})
        self.assertEqual(manifest['counts']['geoip']['custom'], 1)
        self.assertNotIn(b'\r', (self.output / 'sha256sums.txt').read_bytes())
        self.assertNotIn(b'\r', (self.output / 'manifest.json').read_bytes())

    def test_base_inherits_all_unlisted_geosite_tags_and_applies_custom_files(self):
        cfg = {
            'base': {'geosite': 's'},
            'sources': {'s': self.source('base.dat', self.site_bundle({
                'alpha': [(2, 'alpha.example', ())],
                'beta': [(3, 'beta.example', ())],
            }), 'geosite')},
            'geosite': {},
        }
        self.custom('geosite/beta.add.txt', 'domain:extra.example\n')
        self.build(cfg)
        got = b.decode_geosite((self.output / 'geosite.dat').read_bytes())
        self.assertEqual(set(got), {'alpha', 'beta'})
        self.assertEqual({d[1] for d in got['beta']}, {'beta.example', 'extra.example'})

    def test_same_name_geosite_enhancement_unions_with_original_attributes(self):
        original_attr = b.fbytes(1, b'original')
        added_attr = b.fbytes(1, b'added')
        cfg = {
            'base': {'geosite': 's'},
            'sources': {
                's': self.source('base.dat', self.site_bundle({
                    'shared': [(2, 'same.example', (original_attr,))],
                }), 'geosite'),
                'e': self.source('enhanced.dat', self.site_bundle({
                    'shared': [
                        (2, 'same.example', (added_attr,)),
                        (2, 'new.example', ()),
                    ],
                }), 'geosite'),
            },
            'geosite': {'shared': [{'source': 'e'}]},
        }
        self.build(cfg)
        got = b.decode_geosite((self.output / 'geosite.dat').read_bytes())['shared']
        self.assertEqual({d[1] for d in got}, {'same.example', 'new.example'})
        self.assertIn((2, 'same.example', (original_attr,)), got)
        self.assertIn((2, 'same.example', (added_attr,)), got)

    def test_new_tag_added_to_base_source_is_inherited_without_config_change(self):
        base_path = self.root / 'base.dat'
        cfg = {
            'base': {'geosite': 's'},
            'sources': {'s': {'url': base_path.as_uri(), 'format': 'geosite'}},
            'geosite': {},
        }
        base_path.write_bytes(self.site_bundle({'alpha': [(2, 'alpha.example', ())]}))
        self.build(cfg)
        self.assertEqual(set(b.decode_geosite((self.output / 'geosite.dat').read_bytes())), {'alpha'})
        base_path.write_bytes(self.site_bundle({
            'alpha': [(2, 'alpha.example', ())],
            'future': [(2, 'future.example', ())],
        }))
        self.build(cfg)
        self.assertEqual(set(b.decode_geosite((self.output / 'geosite.dat').read_bytes())), {'alpha', 'future'})

    def test_custom_removal_applies_to_inherited_geosite_category(self):
        cfg = {
            'base': {'geosite': 's'},
            'sources': {'s': self.source('base.dat', self.site_bundle({
                'personal': [
                    (2, 'keep.example', ()),
                    (2, 'remove.example', (b.fbytes(1, b'upstream'),)),
                ],
            }), 'geosite')},
            'geosite': {},
        }
        self.custom('geosite/personal.remove.txt', 'domain:remove.example\n')
        self.build(cfg)
        got = b.decode_geosite((self.output / 'geosite.dat').read_bytes())['personal']
        self.assertEqual({d[1] for d in got}, {'keep.example'})

    def test_alias_cannot_overwrite_inherited_tag(self):
        cfg = {
            'base': {'geosite': 's'},
            'sources': {'s': self.source('base.dat', self.site_bundle({
                'existing': [(2, 'existing.example', ())],
                'target': [(2, 'target.example', ())],
            }), 'geosite')},
            'geosite': {},
            'aliases': {'geosite': {'existing': 'target'}},
        }
        with self.assertRaises(b.BuildError):
            self.build(cfg)

    def test_base_inherits_unlisted_geoip_and_preserves_inverse_flags(self):
        cfg = {
            'base': {'geoip': 'i'},
            'sources': {'i': self.source('base.dat', self.geoip_bundle([
                ('cn', [ipaddress.ip_network('203.0.113.0/24')], False),
                ('private', [ipaddress.ip_network('192.0.2.0/24')], True),
            ]), 'geoip')},
            'geoip': {},
        }
        self.custom('geoip/cn.add.txt', '198.51.100.0/24\n')
        self.build(cfg)
        got = b.decode_geoip((self.output / 'geoip.dat').read_bytes())
        self.assertEqual(got['cn'][1], False)
        self.assertEqual(
            got['cn'][0],
            [ipaddress.ip_network('198.51.100.0/24'), ipaddress.ip_network('203.0.113.0/24')],
        )
        self.assertEqual(got['private'], ([ipaddress.ip_network('192.0.2.0/24')], True))

    def test_merging_into_inherited_inverse_geoip_category_is_rejected(self):
        cfg = {
            'base': {'geoip': 'i'},
            'sources': {'i': self.source('base.dat', self.geoip_bundle([
                ('private', [ipaddress.ip_network('192.0.2.0/24')], True),
            ]), 'geoip')},
            'geoip': {'private': [{'source': 'i'}]},
        }
        with self.assertRaises(b.BuildError):
            self.build(cfg)

    def test_truncated_wire_and_unknown_domain_type_rejected(self):
        with self.assertRaises(b.BuildError):
            list(b.fields(b'\x12\xff'))
        with self.assertRaises(b.BuildError):
            b.decode_domain(b'\x08\x09' + b.fbytes(2, b'example.com'))


if __name__ == '__main__':
    unittest.main()
