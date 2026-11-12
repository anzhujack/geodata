# 个人 Geodata

完整继承 Loyalsoldier 的 `geosite.dat` 和 `geoip.dat` 全部分类，再按用途合并 DustinWin 和 blackmatrix7 的补充规则，生成标准 V2Ray protobuf 格式的数据，供 dae、honk 等客户端使用。Loyalsoldier 后续新增的分类会自动继承，无需手工逐个登记。

## 数据流

上游 DAT / Clash 文本 → GitHub Actions 下载 → 按分类转换和去重 → 加入个人增删 → 校验 → GitHub Release → 本地下载并重载。

每天北京时间 08:30 自动构建，也支持手动运行和提交配置后构建。GitHub 定时任务可能延迟；公开仓库长时间无活动时定时任务可能被 GitHub 停用，需要重新启用。上游下载失败、指定分类缺失、解析异常时整个构建失败，不发布不完整数据。

## 放到自己的 GitHub

1. 创建空的**公开仓库**，例如 `my-geodata`，默认分支为 `main`。无需 fork 上游，也无需填写个人访问令牌。
2. 把本项目的内容放入仓库根目录，务必包括隐藏目录 `.github`。不要把外层 `personal-geodata` 文件夹整体作为仓库内的子目录。
3. 在 Actions 中启用工作流，选择 **Build geodata → Run workflow**。发布步骤使用仓库自带 `GITHUB_TOKEN`，已在工作流中声明 `contents: write`；组织若限制 Actions 写权限，需要管理员允许该权限。
4. 成功后 Releases 会出现 `build-运行编号-重试编号`，包含两个 DAT、来源清单 `manifest.json`、汇总校验 `sha256sums.txt`，以及独立校验文件 `geosite.dat.sha256`、`geoip.dat.sha256`。每次先上传到草稿，再公开并设为 Latest，保留历史版本便于回滚。

固定下载地址（本仓库为 `anzhujack/geodata`；fork 后替换为自己的仓库）：

```text
https://github.com/anzhujack/geodata/releases/latest/download/geosite.dat
https://github.com/anzhujack/geodata/releases/latest/download/geoip.dat
https://github.com/anzhujack/geodata/releases/latest/download/manifest.json
https://github.com/anzhujack/geodata/releases/latest/download/sha256sums.txt
https://github.com/anzhujack/geodata/releases/latest/download/geosite.dat.sha256
https://github.com/anzhujack/geodata/releases/latest/download/geoip.dat.sha256
```

每个独立校验文件仅包含对应 DAT 的一行 `SHA256  文件名`，每次构建按实际文件重新计算。将 DAT 与对应校验文件放在同一目录后，可分别运行：

```sh
sha256sum -c geosite.dat.sha256
sha256sum -c geoip.dat.sha256
```

本地若要求两个 DAT 一定来自同一次构建，使用附带更新脚本：它只解析一次 Latest，后续下载同一版本标签下的文件，避免恰好发布时两个固定链接跨版本。

## 全量基底与增强分类

`sources.json` 的 `base` 声明如下：

```json
"base": {
  "geosite": "loyal-site",
  "geoip": "loyal-ip"
}
```

每次构建会读取这两个源中的**全部分类**，包括各服务、分类集合、各国家/地区和 ASN 等具名 IP 集合，按上游实际内容继承。`geosite`、`geoip` 下列出的数组仅是**增强映射**，不再是最终输出的分类白名单。未列入增强映射的 Loyalsoldier 分类照常输出；上游新增分类也自动进入产物。

保留 Loyalsoldier 原有分类名称、域名匹配类型和属性。域名在同一分类内去重，IP 可合并为覆盖相同地址集合的网段，因此不是字节原样复制。发布前会检查全部原始标签、域名规则和 IP 地址覆盖是否仍在，结果写入 `manifest.json` 的 `base_retention`；只有你明确写在个人 `.remove.txt` 中的条目可以例外移除。新增别名不得覆盖任何已有标签。

主要增强关系如下，其余分类由 Loyalsoldier 全量提供：

| 类型 | 分类 | 增强方式 |
| --- | --- | --- |
| geosite | cn | 在 Loyalsoldier cn 上合并 DustinWin cn 与 blackmatrix7 ChinaMax 的域名规则 |
| geosite | private | 在 Loyalsoldier private 上合并 DustinWin 与 blackmatrix7 Lan |
| geosite | geolocation-!cn | 保留原名及原规则，合并 DustinWin proxy 与 blackmatrix7 Global |
| geosite | category-ads-all | 保留原名及原规则，合并 DustinWin ads 与 blackmatrix7 Advertising |
| geosite | ai | DustinWin AI + Loyalsoldier 完整 category-ai-!cn + blackmatrix7 OpenAI |
| geosite | openai | 保留 Loyalsoldier OpenAI 原分类，仅补充 blackmatrix7 OpenAI，不混入整个 ai 分类 |
| geosite | telegram、github | Loyalsoldier + blackmatrix7 |
| geosite | youtube、netflix、disney | 三方同类域名合并 |
| geosite | games、games-cn | 继承存在的同名基底分类，再补充 DustinWin + blackmatrix7 Game / GameDownloadCN |
| geosite | apple-cn、google-cn | Loyalsoldier + DustinWin |
| geosite | microsoft-cn、gfw、fakeip-filter、trackerslist、max、primevideo、appletv、tiktok、bilibili、spotify、media、networktest、tld-proxy | 保留同名基底（若有），按配置补充 DustinWin |
| geoip | cn | 原分类合并 DustinWin cn 与 blackmatrix7 ChinaMax 的 IPv4/IPv6 CIDR |
| geoip | private、telegram、netflix | 原分类合并 DustinWin 与 blackmatrix7 的对应 CIDR |
| geoip | media | 保留同名基底（若有），补充 DustinWin |

`geolocation-!cn` 与 `category-ads-all` 是标准名称，个人增删请编辑这两个名字对应的文件。上一版同时提供的短名称 `proxy`、`ads` 已移除：它们的合并内容与标准名称逐条相同，同时存在会让产物多出约 8 MB 而分流结果不变。若你的客户端配置里写着 `geosite:proxy` 或 `geosite:ads`，请改成对应的标准名称——dae 遇到不存在的 geosite 标签会直接拒绝加载。DustinWin 与 blackmatrix7 的补充范围仍由增强映射明确控制，不扫描 blackmatrix7 仓库中与 DAT 无关的进程、端口等规则。

### Discord 分类

`geoip` 额外提供 `discord`，把 Discord 自己的地址块和语音 anycast 段单独列出，供客户端按 IP 分流。Discord 的网页和 WebSocket 走 Cloudflare（`162.159.x.x`），按域名规则就能覆盖；但**语音是 UDP**、连的是 IP，没有域名可供嗅探，只能靠 IP 段兜底。

- 自有块（RIPE RDAP）：Discord Inc. 的 `66.22.192.0/18`、`195.62.89.0/24`、`2a0e:5940::/29`，以及 Discord Netherlands B.V. 的 `188.244.120.0/24`、`2a11:4cc0::/29`。
- 语音 anycast：Discord 语音服务器对外地址在 `66.22.0.0/17`，该块 ARIN 注册名为 RADWARE-CLOUD-SERVICES，由 Radware（AS25773）以 `/24` 粒度宣告。脚本取 RIPE Stat 中该池内当前被宣告的前缀，合并成不可再合并的网段。
- 注意 `66.22.0.0/17` 是 Radware 的注册块，可能同时承载别的客户；只取宣告中的段可以缩小误伤面，但仍不是 100% 精确。介意的话把 `dip(geoip:discord)` 只用于 UDP 端口 50000-65535。
- 自动化：`tools/discord_asn.py` 在每次 GitHub 构建前重新拉取（见工作流 `Refresh Discord ASN geoip list`），失败时沿用仓库里的旧清单并在 Actions 留 warning。本地手动刷新：`python tools/discord_asn.py`，只比对：`python tools/discord_asn.py --check`。
- 客户端里 `dip(geoip:discord)` 要放在 `dip(geoip:cn)` 等宽泛 IP 兜底之前。

### Telegram 地域分类

`geoip` 额外提供 `telegram-sg`、`telegram-us`、`telegram-eu` 三个分类，把 Telegram 自己的网段按**机房所在地**拆开，便于让不同区域的连接走就近出口（例如新加坡走 SG 节点、迈阿密走 US 节点）。

- 网段来源：官方 <https://core.telegram.org/resources/cidr.txt> 的 CIDR，加上 AS59930、AS62041、AS62014、AS44907、AS211157 在 RIPE Stat 的宣告前缀，取并集后按 `/24` 逐个定位。
- 定位方式：每个 `/24` 取 3 个采样 IP 查 ipinfo.io 与 ipwho.is 交叉验证；ip-api 对 Telegram 的归属与这两家大量冲突（把新加坡、迈阿密都标成荷兰），未采用。
- 结果：`telegram-sg` 2560 IP、`telegram-us` 2048 IP、`telegram-eu` 5632 IP。与 Telegram 公开的 DC 布局一致：DC1/DC3 在迈阿密、DC2/DC4 在阿姆斯特丹、DC5 在新加坡。
- 未纳入：俄罗斯（`91.108.11.0/24`、`95.161.66-75`、`95.161.77-79`）、印度（`91.108.20.0/22`，孟买）、安提瓜（`149.154.160.0/24`）。这些地址仍由 `geoip:telegram` 兜底，不会漏路由。
- 只覆盖 IPv4。Telegram 的 IPv6 网段（`2001:b28:f23c::/48` 等）未拆分，需要时仍用 `geoip:telegram`。
- 使用时三条地域规则必须排在 `dip(geoip:telegram)` 之前，否则会被宽泛的 telegram 先吃掉：

```text
routing {
  dip(geoip:telegram-sg) -> sg_group
  dip(geoip:telegram-us) -> us_group
  dip(geoip:telegram-eu) -> eu_group
  dip(geoip:telegram) -> telegram_group
}
```

### AI 分类覆盖

`geosite:ai` 同时合并 DustinWin 的 AI 列表、Loyalsoldier 的完整 `category-ai-!cn` 和 blackmatrix7 OpenAI。它覆盖 Claude/Anthropic、ChatGPT/OpenAI、Gemini、微软 Copilot、GitHub Copilot、Grok、Perplexity、Cursor、Mistral、Meta AI、OpenRouter、Hugging Face、Poe、Windsurf、Groq、Cohere、Midjourney 等，具体域名随上游更新。不能仅根据配置里 blackmatrix7 的 `OpenAI` 文件名判断整个聚合的范围。

例如 Claude 的 `claude.ai`、`claude.com`、`api.anthropic.com` 都应匹配统一的 `ai`。各服务的独立分类也保留，可按需单独分流：

| 服务 | 独立分类 |
| --- | --- |
| Claude / Anthropic | `anthropic` |
| ChatGPT / OpenAI | `openai` |
| Gemini | `google-gemini` |
| GitHub Copilot | `github-copilot` |
| Grok | `xai` |
| Perplexity | `perplexity` |
| Cursor | `cursor` |
| Hugging Face | `huggingface` |
| Poe | `poe` |
| Windsurf | `windsurf` |
| Groq | `groq` |

国内 AI 的完整分类 `category-ai-cn` 同样从 Loyalsoldier 保留，可以独立设置策略；这里不会将该国内聚合整体加入 `ai`，以延续既有 AI 分流范围。

### 去重与冲突

- 完整域名、域名后缀、关键词、正则分别保留，不能仅用域名字符串去重。例如 `full:example.com` 不等价于 `domain:example.com`。
- 同一分类内相同类型、值和属性的规则去重。保留上游域名属性；不把 `@cn` 与无属性记录混为一条。
- IP 按 IPv4、IPv6 分别合并重复和包含/相邻网段，保持地址集合一致。
- 不擅自删除跨分类重复。例如 `youtube` 与 `proxy` 重复是正常的分类关系。`cn` 与 `proxy` 的精确规则重叠会写入 manifest；不同后缀、关键词和正则之间的覆盖关系并不能由该计数完整反映。
- 直连、代理和广告的最终优先级由客户端从上到下的配置决定。尤其要把个人例外及 `*-cn` 放到更宽泛规则之前。不要用“全局去重”破坏服务分类。
- `.dat` 不能表示 Clash 的进程、端口和 ASN 匹配；已识别的此类规则会跳过并统计，未知类型报错。IP 规则进入 geoip，域名规则进入 geosite。它不会自动把 ASN 展开为 IP。

## 自定义增删

目录命名：

```text
custom/geosite/cn.add.txt
custom/geosite/cn.remove.txt
custom/geosite/proxy.add.txt
custom/geosite/ads.remove.txt
custom/geoip/cn.add.txt
custom/geoip/cn.remove.txt
```

域名文件每行一条，支持 `#` 开头注释：

```text
domain:example.com
full:api.example.net
keyword:example
regexp:^.+\.example\.org$
```

无前缀的域名按后缀匹配。增删只影响文件名对应的分类，删除按“匹配类型 + 值”精确删除，不能用删除子域名来抵消上游的父域后缀。例如删除 `full:api.example.com` 不会撤销 `domain:example.com`；这种例外应放在客户端前置规则中。IP 删除也是精确 CIDR 条目删除，不执行从大网段挖掉小网段的集合差操作。

修改现有分类只需新增对应文件，包括未在增强映射中列出的 Loyalsoldier 继承分类。例如可直接建立 `custom/geosite/steam.add.txt` 或 `custom/geoip/us.remove.txt`。若要创建基底中也不存在的全新分类，先在 `sources.json` 对应类型下增加该标签的空来源数组，再添加其 `.add.txt`，使最终分类非空。别名在基础分类构建之后复制；请修改基础分类。

`init_sources.py` 是初始来源配置生成工具；日常只编辑 `sources.json`，**不要再次运行初始化工具覆盖自己的修改**。

## dae / honk 接入

先核对你使用版本的 DAT 查找目录，设置本地下载地址或使用下方脚本。dae 示例：

```text
routing {
  dip(geoip:private) -> direct
  domain(geosite:private) -> direct
  # 先拦广告，再把个人白名单/例外放在宽泛分类之前。
  domain(geosite:category-ads-all) -> block
  domain(geosite:microsoft-cn, geosite:apple-cn, geosite:google-cn, geosite:games-cn) -> direct
  domain(geosite:ai, geosite:telegram, geosite:youtube) -> my_proxy
  domain(geosite:geolocation-!cn) -> my_proxy
  domain(geosite:cn) -> direct
  dip(geoip:telegram) -> my_proxy
  dip(geoip:cn) -> direct
  fallback: my_proxy
}
```

这只是路由片段，`my_proxy` 必须改成你已经定义的代理组；DNS 分流也应同步使用相应分类。honk 的配置语法及分组需以自己的版本为准，DAT 格式一致并不代表配置文件可整份互换。已参考工作区保存的 honk 读取源码：输出会显式编码关键词类型的 `0` 值及 CIDR 前缀；honk 的 `geoip:private` 使用内置地址集合，自定义 DAT 的 `private` 不会覆盖它，若要自定义私有网段应另建标签。honk 会丢弃 `/0` 网段，GeoIP 反向匹配列表也不适合用来兼容该读取器。上游正则是否被具体客户端版本接受，还需该客户端实际加载确认。

Linux / OpenWrt 下载更新：

```sh
# /etc/dae 只是示例：请改成当前服务实际读取 DAT 的目录。
sh scripts/update-geodata.sh anzhujack/geodata /etc/dae
# 确认安装成功后，再按实际服务选择重载命令：
systemctl restart dae
# OpenWrt 例子：/etc/init.d/dae restart 或 /etc/init.d/honk restart
```

脚本依赖 `curl`、`sha256sum`、`awk`，需有目标目录写权限。它会在下载和校验全部成功后安装；旧数据备份为 `.previous`。两个文件各自通过同目录 rename 替换，整个文件对并非原子替换，安装时避免并发重载。脚本不会自动改动或重启你的现有服务。可用 cron 每天 09:30 运行“更新成功再重载”的组合；具体时间晚于 GitHub 构建即可，但构建可能延迟，取到上一版也不影响继续使用。

## 本地构建与验证

只需 Python 3.12 或更新版本，无第三方运行依赖：

```sh
python -m unittest discover -s tests -v
python build.py --config sources.json --output dist
cd dist
sha256sum -c sha256sums.txt
```

`manifest.json` 提供实际下载 URL、上游内容 SHA-256、各分类计数以及转换时跳过的规则信息，便于查错和追踪变更。上游内容随时间改变，同一配置不同日期的结果也会变化。

## 上游与许可

- DustinWin/ruleset_geodata：https://github.com/DustinWin/ruleset_geodata
- Loyalsoldier/v2ray-rules-dat：https://github.com/Loyalsoldier/v2ray-rules-dat
- blackmatrix7/ios_rule_script：https://github.com/blackmatrix7/ios_rule_script
- dae 官方配置示例：https://github.com/daeuniverse/dae/blob/main/example.dae

本项目不改变上游数据的许可条件。发布合并数据时应保留来源及各上游所要求的署名/许可，特别是它们进一步引用的数据源；这里没有为第三方数据授予新的许可。
