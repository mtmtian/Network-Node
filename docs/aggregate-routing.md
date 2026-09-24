# 双客户端汇总与白名单分流

`aggregate.py` 从明确列出的本地源 profile 生成客户端配置，默认同时输出 Stash 和 Mihomo（Clash Verge Rev）。共用节点来源与分流意图，各自输出原生字段。生成不部署服务器、不切换客户端；发布是显式操作。

## 分流约定

| 顺序 | 流量 | 默认出口 |
|---|---|---|
| 1 | 本机、局域网、私有地址 | DIRECT |
| 2 | AI、Meta 商业相关及共享域名、TikTok Shop/广告、认证与上传依赖、Mac 上的 Antigravity 应用 | 敏感服务主备 |
| 3 | 明确的广告拦截规则 | REJECT |
| 4 | 国内域名白名单 `cn`、`apple-cn` | DIRECT |
| 5 | 普通海外服务清单 | 自动测速 |
| 6 | 所有未匹配的 TCP / UDP | 敏感服务主备 |

准确优先级以生成的 rules 为准：已有业务保护规则保留在广告拦截前。白名单来自 MetaCubeX 的国内域名集合；这是可更新的域名清单，不是“任何 .cn 域名”或“任何大陆 IP”。不再用 `.cn` 后缀、`cn-ip`、`GEOIP,CN` 自动放行。Spotify 和全球 Apple/iCloud 服务没有额外直连豁免，Apple 国内白名单仍可直连。

敏感服务按照 `sensitive` 数组顺序选择，例如 cstone/Reality → gcloud/CDN，不自动扩展到其他节点或 DIRECT。CDN 只改变到 GCP 的入口，不能改变其最终出口信誉。主备切换会改变出口 IP。未匹配流量直接 `MATCH,🛡 敏感服务`，不跟随普通业务组的手动选择。AI 策略组只允许指定敏感主备，不能切到全节点手动组。

普通海外使用 53 个上游服务规则集与 9 项本地补充（76 条），覆盖影音、游戏、新闻、学习、开发下载、通讯和用户指定的金融服务，包括 YouTube、Netflix、Telegram、IBKR、TradingView、Spotify、Twitch、Reddit、Wikipedia、Threads 等。完整来源及取舍见 [普通服务清单来源与边界](ordinary-services-sources.md)。`🌐 普通海外` 默认选择 `⚡ 自动测速`，也可手动改为敏感主备或指定节点。测速组每 300 秒检查所有非 Reality-WARP 节点，不包含 DIRECT；Mihomo 设置 50 ms 切换容差。测速衡量探测延迟，不代表带宽、流媒体解锁或业务可用性。IBKR 按用户选择加入，出口变化可能影响登录会话；未识别的 TWS 地址仍走敏感兜底。

普通规则集在 `core/ordinary-rulesets.json` 按类别维护，少量补充在 `core/ordinary-services.json`；八层路由顺序由 `core/aggregate-rules.yaml.tmpl` 明确声明，不引入全 Google、共享 CDN 或“非大陆即测速”的规则。已知敏感规则优先，国内白名单与广告规则也先于普通清单。新增静态域名若与 AI、Meta 或业务保护域名重叠，或试图放行共享云根域，生成会失败并保留旧成品；动态敏感规则集发生重叠时由顺序保证敏感优先。未知依赖留在敏感兜底，因此清单并不承诺完整覆盖每款应用。域名规则不能区分同域名中的业务用途，例如 Telegram AI 机器人也会跟随 Telegram 出口。

普通服务直接引用 MetaCubeX 固定提交的 MRS 子清单，业务重叠由更早的敏感规则覆盖，不自动跟随远端增加普通服务。Threads 已按用户选择纳入普通组，不因属于 Meta 而统一归入敏感；无法按路径拆分的 Facebook/Instagram 商业与普通请求继续使用敏感出口。Telegram 网段来源为 https://core.telegram.org/resources/cidr.txt （核对日期 2026-09-25）；TradingView widget 域名参考 https://en.tradingview.com/widget-docs/tutorials/web-components/configuring/ 。域名参考数据：https://github.com/MetaCubeX/meta-rules-dat/tree/meta/geo/geosite 。

Stash 的 `PROTOCOL,STUN` 无法直接迁移到 Mihomo。本方案不靠 STUN 协议或常见端口补丁实现隐私兜底：两个客户端都将未命中白名单的未知 TCP/UDP 送往敏感主备。明确命中国内域名白名单的 UDP 仍直连；命中普通服务清单的 UDP 使用普通海外组，这是恢复测速后明确允许的例外。Mihomo 的 TUN 排除本机、RFC1918、链路本地和 CGNAT 地址，保护局域网与 Tailscale 等私网路由。DNS 劫持仅处理进入 TUN 的 DNS，不代表应用自带加密 DNS 也会被接管。

IPv6 沿用当前配置的关闭状态；不能据此宣称操作系统所有 IPv6 出口均已封堵。完整隐私验收还需实际客户端接管、IPv6、WebRTC 与应用自带 DNS 测试。

Agent 的模型 API 请求与访问资料网站的请求分别匹配规则。普通网站出口变化不会自动改变模型 API 出口；但网站会看到它收到的连接出口，Agent 也可能从定位、验证码或工具返回内容中得知变化。X 当前不在普通清单中，继续走敏感兜底。已保留 Antigravity 的进程优先规则；无法据此保证独立浏览器、子工具或远程抓取服务也走同一出口。

## 一份方案、两份客户端文件

新汇总计划参考 `config/aggregate.json.example`：

```json
{
  "sources": [
    {"profile": "primary", "name": "cstone"},
    {"profile": "backup", "name": "gcloud"}
  ],
  "sensitive": ["cstone/Reality", "gcloud/CDN"],
  "credential_identity": "mac"
}
```

`credential_identity` 只指定复用源 profile 中哪套已存在的凭据。它不是新的设备输出维度，不创建用户、不改服务器、不删除其他身份。选择 `mac` 后，同一 Stash 文件可供 Mac/iPhone 使用，两者共享该身份，不能再单独撤销。文件与头部不标记设备。Mac 进程规则保留在共享文件中；iOS 不执行进程规则，依靠域名分流。

```bash
python3 aggregate.py render --profile routing
python3 aggregate.py check --profile routing
# 仅重建某一端，另一端不受影响
python3 aggregate.py render --profile routing --client mihomo
```

输出（权限 600，目录 700）：

```text
clash-configs/stash/routing.yaml
clash-configs/mihomo/routing.yaml
```

旧版 `devices/client` 计划仍能读取，默认也会生成两种客户端，但每个客户端目录继续保留原设备维度。切换到上述 `credential_identity` 计划才合并身份。旧目录下未审计的 `routing-mac.yaml` / `routing-iphone.yaml` 不自动删除。单服务器 `node.py render --profile <profile>` 也默认输出 `stash/<prefix>.yaml` 和 `mihomo/<prefix>.yaml`，两者复用 `CLIENT_IDENTITY`（未指定时优先 mac）。服务器账号清单保留，不再按设备输出。

若只有已有的客户端文件、缺少原始汇总/服务器 profile，可一次性导入其内嵌节点：

```bash
uv run --with PyYAML==6.0.2 python aggregate.py import --profile routing --source /path/to/routing-mac.yaml
python3 aggregate.py render --profile routing
```

导入仅支持已知的 VLESS/HY2/AnyTLS 节点以及明确的「敏感服务」fallback 主备；不接受外部节点 provider，也不复制旧文件的分流规则。导入后，节点以客户端中性的 JSON 存入 `profiles/routing/nodes.json`（600），汇总计划引用此快照。主备必须支持 UDP，以免不支持 UDP 的出口导致规则继续向下匹配。导入拒绝覆盖已有 profile；服务器凭据变更后须维护私有快照或切回完整源 profile 生成方式，不能假设快照会自动感知服务器变化。只有首次 YAML 导入需要 PyYAML，日常快照生成仍只用 Python 标准库。

两个客户端完整生成后才开始写出；每个客户端分别维护归属清单。持有所有源 profile 的操作锁，避免混入部署/换 IP 中间状态。生成失败保留旧输出；磁盘故障时逐文件原子替换不构成跨文件事务，应修复后重新 render/check。

## 按主配置节点生成单服务器文件

共享计划设置 `"standalone": true` 后，默认 render 同时生成主配置与每个服务器别名的独立文件，每份都有 Stash / Mihomo 两种格式。例如 `routing-cstone.yaml`、`routing-lax.yaml`、`routing-gcloud.yaml`；文件名的 routing 表示来自主配置，后缀是服务器名，不是设备名。

单服务器文件直接复用主配置当次生成的节点、凭据、DNS、规则与规则集，不再从旧部署目录另取一份节点。每个节点必须采用合法的 `server/protocol` 名称；会检查每台服务器可用的 Reality/CDN 敏感出口，无可用出口则停止生成。AI 优先复用主配置在该服务器上指定的线路；该服务器不在主配置敏感主备中时，单机文件使用其 Reality/CDN。这只是单机使用方式，不代表该出口具有住宅属性或已通过 AI 账号风控。单机文件无法提供跨服务器主备；主配置仍是日常推荐。

```bash
python3 aggregate.py render --profile routing
python3 aggregate.py check --profile routing
# 将主配置与三台服务器的 Stash 文件一起发布到 iCloud
python3 aggregate.py publish --profile routing --client stash
# 每个 HTTPS 发布显式指定需要的服务器
python3 subscription.py publish --profile routing --server cstone
python3 subscription.py publish --profile routing --server lax
python3 subscription.py publish --profile routing --server gcloud
python3 subscription.py copy-link --profile routing --server gcloud
```

历史部署目录不是当前汇总节点的清单。以主配置中的服务器别名为准，使用带主配置前缀的单机文件，避免误选历史部署生成的同名文件。退役节点或旧分设备输出不自动删除，清理前核对使用者及归属。

主配置快照仍是源，节点参数变化后应先更新源再 render/publish。

## 客户端适配

- HY2：Stash `auth` / `server-cert-fingerprint` / `up-speed,down-speed`；Mihomo `password` / `fingerprint` / `up,down`。
- DNS：Stash `follow-rule`，Mihomo `respect-rules`；节点 bootstrap 单独解析。
- 测速：Stash 使用节点 benchmark 参数；Mihomo 使用策略组测速 URL。主备只做健康检查，不改变指定顺序。
- 应用规则：Stash 的包路径前缀与 Mihomo 的 `PROCESS-PATH-REGEX` 分别生成。
- TUN：Mihomo 显式配置 TUN、DNS 劫持、私网排除；Stash 由应用管理增强模式。
- DNS：敏感域名使用敏感组解析器；国内白名单使用国内解析器；其余解析器默认也通过敏感主备。已知解析器端点和节点 bootstrap 是必要的解析基础设施，不能与业务白名单完全等同。

Clash Verge 的应用设置可能覆盖订阅里的 TUN/DNS/端口设置。成功导入不代表已经启用 TUN，也不证明最终规则未被全局/订阅扩展改写。检查客户端最终运行配置和连接日志，不能只检查源 YAML。

## 发布与导入

### Stash：iCloud

```bash
python3 aggregate.py publish --profile routing --client stash
# 可显式指定已存在的分发目录
python3 aggregate.py publish --profile routing --client stash --icloud-dir /path/to/Stash/Documents
```

默认发布到 macOS Stash iCloud 容器的 `Documents`，共享计划下文件名为 `routing.yaml`。发布前检查源配置是否过期；拒绝覆盖归属不明的同名文件和符号链接。其他订阅、旧分端文件保持原样。命令不主动调用 Stash 切换或重载接口，但客户端可能自行监测、同步或重载文件，因此 iCloud publish 不能视为完全没有运行影响。本地写入成功与 iPhone 已收到同步是不同验证阶段。

### Clash Verge：私有 HTTPS

采用 Cloudflare Workers Free + 私有 KV + `workers.dev`，无需购买或续费个人域名。账户应维持 Workers Free；部署不要求付费套餐或 R2。端点只读取本地验证后的 Mihomo 成品，不上传 profiles 或服务器管理文件。部署与维护见 [订阅服务](../cloud/subscription/README.md)。

```bash
python3 aggregate.py render --profile routing
python3 aggregate.py publish --profile routing --client mihomo
python3 subscription.py verify --profile routing
python3 subscription.py copy-link --profile routing
# 或调用 Verge URL scheme，并在客户端检查结果
python3 subscription.py import --profile routing
```

随机订阅令牌保存在 macOS 钥匙串；Worker 仅保存 SHA256 校验值。无令牌、错误令牌与未知路径返回 404，不提供公开目录。响应禁止缓存，关闭 Worker 请求日志和跟踪，避免完整 URL 被应用日志记录。完整 URL 等同订阅密码；复制后只粘贴到可信客户端。客户端本身需要保存 URL，因此客户端数据仍应视为私密。

发布先校验源与成品一致，写 KV 后读回，再从 HTTPS 端点逐字节核对并测试未授权访问。KV 有跨区域传播延迟，若端点仍是旧版本，稍后运行 verify，不重复写入。写入后的验证失败不意味着自动回滚。订阅默认建议每 24 小时更新，最终周期由客户端决定。

`workers.dev` 不依赖个人域名续费，但中国大陆首次下载的可达性取决于网络；当前代理下成功下载不代表关代理后也可用。可随时从本地 `clash-configs/mihomo/routing.yaml` 首次导入，再设置订阅。导入和订阅下载不代表 TUN 已启用或客户端扩展未改写规则。

官方依据：
- https://www.clashverge.dev/guide/url_schemes.html
- https://developers.cloudflare.com/workers/platform/pricing/
- https://developers.cloudflare.com/kv/platform/pricing/
- https://developers.cloudflare.com/kv/concepts/how-kv-works/

## 验证

```bash
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -p 'test_*.py'
```

真实内核校验与隔离路由测试：设置 `MIHOMO_BIN` 为 Mihomo 可执行文件、`MIHOMO_DATA_DIR` 为已有公开地理数据库所在目录，再执行：

```bash
python3 -m unittest discover -s tests -p 'test_aggregate*.py'
```

`test_aggregate_runtime.py` 使用真实 Mihomo、回环 HTTP 出口和确定性规则集夹具，验证敏感域名优先于国内与普通清单、国内/局域网直连、清单内服务使用测速出口、未知域名与非白名单 `.cn` 使用敏感兜底。夹具让测速组选中 BACKUP、敏感主备仍选 PRIMARY，以实际响应区分两种出口；同时覆盖 Google 共享域及伪装成 YouTube 的域名。域名直连使用受控 NXDOMAIN 和内核日志验证路由选择，不外连真实站点。测试还将兜底故意改为 DIRECT，确认能识别错误。设置 `ORDINARY_RULESET_DIR` 指向固定提交的完整 MRS 文件目录（以服务名命名）时，测试用真实上游数据并从控制接口核对全部规则集已加载；未设置时使用最小离线规则集夹具。另以真实 HTTP 404 验证普通规则无缓存时回到敏感兜底。它不启用 TUN，不改系统代理，不证明真实节点连通性、UDP 转发或 Stash/iPhone 的实际运行状态。
