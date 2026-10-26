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
        return b.fbytes(1, b.fbytes(1, b'CN') + b''.join(b.fbytes(2, b.encode_domain(d)) for d in domains))

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

    def test_truncated_wire_and_unknown_domain_type_rejected(self):
        with self.assertRaises(b.BuildError):
            list(b.fields(b'\x12\xff'))
        with self.assertRaises(b.BuildError):
            b.decode_domain(b'\x08\x09' + b.fbytes(2, b'example.com'))


if __name__ == '__main__':
    unittest.main()
