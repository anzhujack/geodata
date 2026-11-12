#!/usr/bin/env python3
"""Regenerate custom/geoip/discord.add.txt from registry + BGP data.

用途：把 Discord 的语音/媒体服务器地址单独归到 geoip:discord，让 dae 能把不带
域名的 UDP 语音流量也固定到 discord 出口，而不是落到 IP 兜底组。

数据来源：
  1. RIPE RDAP 组织记录（Discord Inc. 与 Discord Netherlands B.V.）
     自有地址块：66.22.192.0/18、195.62.89.0/24、188.244.120.0/24、2a0e:5940::/29。
  2. RIPE Stat announced-prefixes（AS25773，Radware）
     Discord 的语音服务器对外地址是 66.22.x.x，由 Radware 的 anycast 池
     66.22.0.0/17 以 /24 粒度宣告（ARIN 注册名 RADWARE-CLOUD-SERVICES）。
     这里只取该池内当前被宣告的段。

  66.22.0.0/17 是 Radware 的注册块，除 Discord 外可能还有别的客户；
  只取宣告中的 /24 可以缩小误伤面，同时覆盖语音服务器实际会出现的地址。

用法：
  python tools/discord_asn.py            # 重新生成 custom/geoip/discord.add.txt
  python tools/discord_asn.py --check    # 只比对，不写文件；有差异返回 1

拉取失败或结果异常（自有块缺失、语音段少于 10 个）时直接报错退出，
不写文件，避免把分类清空。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
import urllib.request
from pathlib import Path

ORG_HANDLES = ["ORG-DI90-RIPE", "ORG-DNB8-RIPE"]  # Discord Inc. / Discord Netherlands B.V.
VOICE_ASN = "AS25773"  # Radware
VOICE_POOL = ipaddress.ip_network("66.22.0.0/17")
MIN_VOICE_PREFIXES = 10
ROOT = Path(__file__).resolve().parent.parent
OUTFILE = ROOT / "custom" / "geoip" / "discord.add.txt"


def http_json(url: str, tries: int = 3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8", "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=40) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001 - 网络抖动只需重试
            if attempt == tries - 1:
                print(f"  ! {url}: {exc}", file=sys.stderr)
            time.sleep(2)
    return None


def org_networks(handle: str) -> list[ipaddress._BaseNetwork]:
    data = http_json(f"https://rdap.db.ripe.net/entity/{handle}")
    if not data:
        raise RuntimeError(f"RDAP lookup failed: {handle}")
    nets = []
    for net in data.get("networks") or []:
        for cidr in net.get("cidr0_cidrs") or []:
            prefix = cidr.get("v4prefix") or cidr.get("v6prefix")
            length = cidr.get("length")
            if prefix is None or length is None:
                continue
            nets.append(ipaddress.ip_network(f"{prefix}/{length}", strict=False))
    return nets


def voice_prefixes() -> list[ipaddress.IPv4Network]:
    data = http_json(f"https://stat.ripe.net/data/announced-prefixes/data.json?resource={VOICE_ASN}")
    if not data:
        raise RuntimeError(f"RIPE Stat lookup failed: {VOICE_ASN}")
    nets = []
    for item in (data.get("data") or {}).get("prefixes") or []:
        prefix = item.get("prefix", "")
        if ":" in prefix:
            continue
        net = ipaddress.ip_network(prefix, strict=False)
        if net.subnet_of(VOICE_POOL):
            nets.append(net)
    if len(nets) < MIN_VOICE_PREFIXES:
        raise RuntimeError(f"only {len(nets)} voice prefixes in {VOICE_POOL}, expected >= {MIN_VOICE_PREFIXES}")
    return nets


def build() -> list[str]:
    owned: list[ipaddress._BaseNetwork] = []
    for handle in ORG_HANDLES:
        nets = org_networks(handle)
        if not nets:
            raise RuntimeError(f"no networks registered for {handle}")
        owned.extend(nets)
        print(f"  {handle}: {len(nets)} network(s) {[str(n) for n in nets]}")
    voice = voice_prefixes()
    print(f"  {VOICE_ASN} voice pool {VOICE_POOL}: {len(voice)} announced prefix(es)")

    v4 = [n for n in owned + voice if n.version == 4]
    v6 = [n for n in owned if n.version == 6]
    out = [str(n) for n in ipaddress.collapse_addresses(v4)]
    out += [str(n) for n in ipaddress.collapse_addresses(v6)]
    if not any(n.startswith("66.22.") for n in out):
        raise RuntimeError("66.22.x.x missing from output")
    return out


def render(cidrs: list[str]) -> str:
    lines = [
        "# geoip:discord",
        "# Discord 语音/媒体服务器地址（用于让不带域名的 UDP 流量也走 discord 出口）",
        "# 自有块：Discord Inc. 66.22.192.0/18、195.62.89.0/24、2a0e:5940::/29；",
        "#         Discord Netherlands B.V. 188.244.120.0/24（RIPE RDAP）",
        f"# 语音 anycast：{VOICE_ASN} 在 66.22.0.0/17（Radware Cloud Services）内宣告的前缀",
        "# 注意：66.22.0.0/17 是 Radware 注册块，只取宣告中的段以缩小误伤面",
        "# 重新生成：python tools/discord_asn.py",
    ]
    lines += cidrs
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对现有文件，不写入")
    args = ap.parse_args()

    cidrs = build()
    content = render(cidrs)
    if args.check:
        current = OUTFILE.read_text(encoding="utf-8") if OUTFILE.exists() else ""
        if current != content:
            print(f"  DIFF {OUTFILE}", file=sys.stderr)
            return 1
        print(f"  OK {OUTFILE} ({len(cidrs)} CIDR)")
        return 0
    OUTFILE.write_text(content, encoding="utf-8", newline="\n")
    print(f"wrote {OUTFILE} ({len(cidrs)} CIDR)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
