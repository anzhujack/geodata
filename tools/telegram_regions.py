#!/usr/bin/env python3
"""Regenerate custom/geoip/telegram-{sg,us,eu}.add.txt.

Telegram 自有机房的网段按地理位置拆成三份，用于让不同区域的 Telegram 连接
走就近出口（新加坡 -> SG 节点、迈阿密 -> US 节点、阿姆斯特丹/赫尔辛基 -> EU）。

数据来源：
  1. https://core.telegram.org/resources/cidr.txt   官方 CIDR
  2. RIPE Stat announced-prefixes                   各 ASN 当前宣告的前缀
  3. ipinfo.io / ipwho.is                           每个 /24 采样 3 个 IP 做地理定位
     （ip-api.com 对 Telegram 的归属误差很大，不采用）

用法：
  python tools/telegram_regions.py            # 重新生成三个 .add.txt
  python tools/telegram_regions.py --check    # 只比对，不写文件；有差异返回 1

只覆盖 IPv4。俄罗斯、印度、安提瓜的地址刻意不进入这三个分类，仍由
geoip:telegram 兜底。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

OFFICIAL = [
    "91.108.56.0/22", "91.108.4.0/22", "91.108.8.0/22", "91.108.16.0/22",
    "91.108.12.0/22", "149.154.160.0/20", "91.105.192.0/23", "91.108.20.0/22",
    "185.76.151.0/24",
]
# Telegram 的 ASN（含 CDN / 短信 / 印度节点）
ASNS = ["AS59930", "AS62041", "AS62014", "AS44907", "AS211157"]
# 视为「欧洲」的国家；俄罗斯不在此列（其节点单独兜底）
EU = {
    "AT", "BE", "BG", "HR", "CY", "CZ", "DK", "EE", "FI", "FR", "DE", "GR", "HU",
    "IE", "IT", "LV", "LT", "LU", "MT", "NL", "PL", "PT", "RO", "SK", "SI", "ES",
    "SE", "GB", "CH", "NO", "IS", "LI", "RS", "UA", "MD", "BA", "MK", "AL", "ME", "XK",
}
SAMPLES = (50, 130, 10)
ROOT = Path(__file__).resolve().parent.parent
OUTDIR = ROOT / "custom" / "geoip"
TITLES = {
    "sg": ("新加坡 DC（91.108.16.0/22、91.108.56.0/23、149.154.168.0/22）",
           "Telegram 新加坡机房（AS62014）"),
    "us": ("美国 DC（91.108.12.0/22 迈阿密、149.154.172.0/22）",
           "Telegram 美国机房（AS59930/AS62041），迈阿密/华盛顿"),
    "eu": ("欧洲 DC（荷兰阿姆斯特丹、芬兰赫尔辛基）",
           "Telegram 欧洲机房（AS62041/AS211157），不含俄罗斯节点"),
}


def http_json(url: str, tries: int = 3):
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8", "replace"))
        except Exception as exc:  # noqa: BLE001 - 网络抖动只需重试
            if attempt == tries - 1:
                print(f"  ! {url}: {exc}", file=sys.stderr)
            time.sleep(2)
    return None


def collect_prefixes() -> list[ipaddress.IPv4Network]:
    seen = {ipaddress.ip_network(p) for p in OFFICIAL}
    for asn in ASNS:
        data = http_json(f"https://stat.ripe.net/data/announced-prefixes/data.json?resource={asn}")
        for item in (data or {}).get("data", {}).get("prefixes", []):
            net = item["prefix"]
            if ":" not in net:  # 只处理 IPv4
                seen.add(ipaddress.ip_network(net, strict=False))
    return sorted(ipaddress.collapse_addresses(seen))


def locate(net24: ipaddress.IPv4Network) -> tuple[str, dict]:
    base = int(net24.network_address)
    votes: Counter = Counter()
    for off in SAMPLES:
        ip = str(ipaddress.ip_address(base + off))
        data = http_json(f"https://ipwho.is/{ip}", tries=2)
        if data and data.get("success") and data.get("country_code"):
            votes[data["country_code"]] += 1
    if not votes:  # 兜底换一家数据源
        ip = str(ipaddress.ip_address(base + SAMPLES[0]))
        data = http_json(f"https://ipinfo.io/{ip}/json", tries=2)
        if data and data.get("country"):
            votes[data["country"]] += 1
    country = votes.most_common(1)[0][0] if votes else "??"
    return country, dict(votes)


def classify() -> tuple[dict[str, list[str]], list[tuple[str, str]]]:
    buckets: dict[str, list[ipaddress.IPv4Network]] = defaultdict(list)
    unknown: list[tuple[str, str]] = []
    for net in collect_prefixes():
        for net24 in net.subnets(new_prefix=24):
            country, votes = locate(net24)
            if country == "SG":
                buckets["sg"].append(net24)
            elif country == "US":
                buckets["us"].append(net24)
            elif country in EU:
                buckets["eu"].append(net24)
            else:
                unknown.append((str(net24), country))
            print(f"  {str(net24):18s} {country:3s} {votes}")
            time.sleep(0.3)

    result: dict[str, list[str]] = {}
    for key in ("sg", "us", "eu"):
        collapsed = ipaddress.collapse_addresses(buckets[key])
        result[key] = [str(net) for net in collapsed]
    return result, unknown


def render(key: str, cidrs: list[str]) -> str:
    lines = [
        f"# geoip:telegram-{key}",
        f"# {TITLES[key][0]}",
        "# 依据：core.telegram.org/resources/cidr.txt + AS59930/AS62041/AS62014/AS44907/AS211157 的 RIPE Stat 宣告前缀，",
        "#       逐个 /24 取 3 个采样 IP，经 ipinfo.io / ipwho.is 交叉定位（ip-api 误差大，未采用）",
        f"# {TITLES[key][1]}",
        "# 俄罗斯、印度、安提瓜的地址不在本文件内，由 geoip:telegram 兜底",
        "# 重新生成：python tools/telegram_regions.py",
    ]
    lines += cidrs
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只比对现有文件，不写入")
    args = ap.parse_args()

    cidrs, unknown = classify()
    print("\n未纳入三个分类的网段（仍由 geoip:telegram 兜底）：")
    for net, country in unknown:
        print(f"  {net:18s} {country}")

    rc = 0
    for key in ("sg", "us", "eu"):
        target = OUTDIR / f"telegram-{key}.add.txt"
        content = render(key, cidrs[key])
        if args.check:
            current = target.read_text(encoding="utf-8") if target.exists() else ""
            if current != content:
                print(f"  DIFF {target}", file=sys.stderr)
                rc = 1
            continue
        target.write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {target} ({len(cidrs[key])} CIDR)")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
