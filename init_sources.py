import json
from pathlib import Path

root = Path(__file__).parent
sources = {
    'dustin-site': {'url': 'https://github.com/DustinWin/ruleset_geodata/releases/download/mihomo-geodata/geosite-all.dat', 'format': 'geosite'},
    'dustin-ip': {'url': 'https://github.com/DustinWin/ruleset_geodata/releases/download/mihomo-geodata/geoip.dat', 'format': 'geoip'},
    'loyal-site': {'url': 'https://raw.githubusercontent.com/Loyalsoldier/v2ray-rules-dat/release/geosite.dat', 'format': 'geosite'},
    'loyal-ip': {'url': 'https://raw.githubusercontent.com/Loyalsoldier/v2ray-rules-dat/release/geoip.dat', 'format': 'geoip'},
}
# Explicit mappings avoid accidentally equating lists with different meanings.
bm = {'cn': 'China', 'proxy': 'Global', 'ads': 'Advertising', 'private': 'Lan',
      'ai': 'OpenAI', 'telegram': 'Telegram', 'youtube': 'YouTube', 'netflix': 'Netflix',
      'disney': 'Disney', 'github': 'GitHub', 'games': 'Game', 'games-cn': 'Game/GameDownloadCN'}
for tag, path in bm.items():
    name = path.rsplit('/', 1)[-1]
    sources['bm-' + tag] = {'url': f'https://raw.githubusercontent.com/blackmatrix7/ios_rule_script/master/rule/Clash/{path}/{name}.list', 'format': 'clash'}

def ref(source, tag=None):
    return {'source': source, **({'tag': tag} if tag else {})}

site = {}
for tag in ['cn', 'proxy', 'ads', 'private', 'ai', 'gfw', 'fakeip-filter', 'trackerslist',
            'microsoft-cn', 'apple-cn', 'google-cn', 'games-cn', 'games', 'netflix', 'disney',
            'max', 'primevideo', 'appletv', 'youtube', 'tiktok', 'bilibili', 'spotify', 'media',
            'networktest', 'tld-proxy']:
    site[tag] = [ref('dustin-site', tag)]
# Same-name Loyalsoldier categories are inherited automatically.
loyal = {'proxy': 'geolocation-!cn', 'ads': 'category-ads-all', 'ai': 'openai'}
for tag, upstream in loyal.items():
    site.setdefault(tag, []).append(ref('loyal-site', upstream))
for tag in bm:
    site.setdefault(tag, []).append(ref('bm-' + tag))
ip = {tag: [ref('dustin-ip', tag)] for tag in ['cn', 'private', 'telegram', 'netflix', 'media']}
for tag in ['cn', 'private', 'telegram', 'netflix']:
    ip[tag].append(ref('bm-' + tag))
# Explicit enhancement mappings supplement the full base; they do not select base tags.
site['geolocation-!cn'] = [ref('dustin-site', 'proxy'), ref('bm-proxy')]
site['category-ads-all'] = [ref('dustin-site', 'ads'), ref('bm-ads')]
site['openai'] = [ref('bm-ai')]
config = {'sources': sources, 'base': {'geosite': 'loyal-site', 'geoip': 'loyal-ip'},
          'geosite': site, 'geoip': ip, 'aliases': {'geosite': {}, 'geoip': {}}}
(root / 'sources.json').write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
print('Created sources.json')
