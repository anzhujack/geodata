"""Guard published ad categories against blocking known functional hosts."""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from build import AD_PROTECTED as PROTECTED, FULL, PLAIN, REGEXP, ROOT_DOMAIN, custom_domains, decode_geosite


def matches(host, kind, value):
    if kind == FULL:
        return host == value
    if kind == ROOT_DOMAIN:
        return host == value or host.endswith('.' + value)
    if kind == PLAIN:
        return value in host
    if kind == REGEXP:
        return re.search(value, host) is not None
    return False


def main(path):
    sites = decode_geosite(Path(path).read_bytes())
    root = Path(__file__).resolve().parents[1]
    additions, _ = custom_domains(root, 'category-ads')
    rules = set(sites['category-ads'])
    for kind, value, attrs in additions:
        if kind != FULL or (kind, value, attrs) not in rules:
            raise SystemExit(f'Expected exact ad match missing or too broad: {value}')
    for tag in ('category-ads', 'category-ads-all'):
        for kind, value, _ in sites[tag]:
            for host in PROTECTED:
                if matches(host, kind, value):
                    raise SystemExit(f'{tag} would block protected host {host}: {kind}:{value}')
    print(f'Ad guard passed: {len(additions)} exact overrides, {len(PROTECTED)} protected hosts')


if __name__ == '__main__':
    main(sys.argv[1])
