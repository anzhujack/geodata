#!/usr/bin/env python3
"""Regenerate custom/geoip/meta.add.txt from BGP data for the Meta ASNs.

用途：让 `dip(geoip:meta)` 与 `domain(geosite:meta)` 走同一个出口。没有域名可嗅探
的 Meta 流量（App 内直连 IP、CDN、语音/视频边缘）才会命中 IP 规则。

为什么不用 PuthsenTaylor/Mihomo-RuleSets 的 Meta_IP.yaml：
  2026-11-26 逐条核对 149 个段，有 21 个不属于 Meta——AWS（34.224.0.0/12、
  18.194.0.0/15、52.58.0.0/15 等）、IBM SoftLayer、LINE 日本段，甚至
  108.177.8.0/24 是 Google DNS。把这些段挂到 Instagram 出口，等于把别人的流量
  拐到日本节点。所以这里只取 Meta 自己宣告的前缀。

数据来源：RIPE Stat announced-prefixes
  AS32934 FACEBOOK               自有网络
  AS63293 FACEBOOK-OFFNET        边缘/离网（CDN、PoP、合作方）
  AS54115 FACEBOOK-CORP          其他服务段

用法：
  python tools/meta_asn.py            # 重新生成 custom/geoip/meta.add.txt
  python tools/meta_asn.py --check    # 只比对，不写文件；有差异返回 1

拉取失败或结果异常（前缀过少、缺少已知的 Meta 段）时直接报错退出，不写文件，
避免把分类写空。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
import urllib.request
from pathlib import Path

META_ASNS = ["AS32934", "AS63293", "AS54115"]
MIN_V4_PREFIXES = 60
# 已知的 Meta 关键段，缺任意一个都说明上游数据异常
KNOWN_PREFIXES = ["157.240.0.0/16", "129.134.0.0/16", "31.13.0.0/16", "102.132.0.0/16"]
ROOT = Path(__file__).resolve().parent.parent
OUTFILE = ROOT / "custom" / "geoip" / "meta.add.txt"


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


def announced(asn: str) -> list[ipaddress._BaseNetwork]:
    data = http_json(f"https://stat.ripe.net/data/announced-prefixes/data.json?resource={asn}")
    if not data:
        raise RuntimeError(f"RIPE Stat lookup failed: {asn}")
    nets = []
    for item in (data.get("data") or {}).get("prefixes") or []:
        prefix = item.get("prefix", "")
        if not prefix:
            continue
        try:
            nets.append(ipaddress.ip_network(prefix, strict=False))
        except ValueError as exc:
            raise RuntimeError(f"bad prefix {prefix!r} from {asn}") from exc
    return nets


def build() -> list[str]:
    v4: list[ipaddress._BaseNetwork] = []
    v6: list[ipaddress._BaseNetwork] = []
    for asn in META_ASNS:
        nets = announced(asn)
        if not nets:
            raise RuntimeError(f"no announced prefixes for {asn}")
        for net in nets:
            (v4 if net.version == 4 else v6).append(net)
        print(f"  {asn}: {len(nets)} announced prefix(es)")

    v4_collapsed = list(ipaddress.collapse_addresses(v4))
    v6_collapsed = list(ipaddress.collapse_addresses(v6))
    if len(v4_collapsed) < MIN_V4_PREFIXES:
        raise RuntimeError(f"only {len(v4_collapsed)} IPv4 prefixes, expected >= {MIN_V4_PREFIXES}")

    for known in KNOWN_PREFIXES:
        target = ipaddress.ip_network(known)
        inner = [net for net in v4_collapsed if net.version == 4 and net.subnet_of(target)]
        if not inner:
            raise RuntimeError(f"known Meta prefix {known} missing from announced set")

    return [str(n) for n in v4_collapsed] + [str(n) for n in v6_collapsed]


def render(cidrs: list[str]) -> str:
    lines = [
        "# geoip:meta",
        "# Meta（Facebook / Instagram / WhatsApp / Messenger / Threads）自己宣告的地址段，",
        "# 供 dip(geoip:meta) 与 domain(geosite:meta) 走同一个出口。",
        "# 来源：RIPE Stat announced-prefixes，AS32934 / AS63293 / AS54115",
        "# 不含 AWS、SoftLayer、LINE 等第三方段（上游 Meta_IP.yaml 混入过 21 个，已改用本清单）",
        "# 重新生成：python tools/meta_asn.py",
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
