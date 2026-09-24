# 普通规则集的来源与维护

核对日期：2026-09-25。普通服务由 **53 个远程规则集 + 9 项本地补充** 组成。普通域名明细不再复制到仓库和主配置中。

## 单一维护入口

| 文件 | 维护内容 |
|---|---|
| `core/aggregate-rules.yaml.tmpl` | 有顺序的八层路由；敏感与业务保护先于国内/普通 |
| `core/ordinary-rulesets.json` | 上游固定提交、按用途分类的服务名单 |
| `core/ordinary-services.json` | 76 条本地精确域名/后缀/Telegram 网段；保留九项收窄清单 |
| `core/sensitive-services.json` | 两个客户端共用的 AI 核心域名与依赖补充 |

`ordinary_policy.py` 校验本地域名与敏感域名不重叠，并拒绝共享云根域、重复服务、活动分支和泛海外类别。生成器把以上意图转换为 Stash/Mihomo 原生配置，日常 render 不联网。

## 复用上游

直接使用 [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat) 的 MRS 服务子清单，固定提交 `0f3410e013082b242f381750899a533078914f34`。仓库标注 GPL-3.0；相关上游包括 MIT 的 [v2fly/domain-list-community](https://github.com/v2fly/domain-list-community) 及 GPL-2.0 的 [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script)。不使用 Global/Proxy、非 CN、整个开发或社交类别作为测速兜底。

配置引用形式：`https://raw.githubusercontent.com/MetaCubeX/meta-rules-dat/<固定提交>/geo/geosite/<服务>.mrs`。两个客户端都支持 MRS domain/ipcidr；无需部署额外规则托管站，也没有给 iPhone 留下必须复制的本地 sidecar 文件。

| 分类 | 规则集 |
|---|---|
| media | disney, hbo, primevideo, vimeo, dailymotion, deezer, soundcloud, tidal, lastfm |
| games | steam, epicgames, gog, playstation, xbox, nintendo, ubisoft, ea, blizzard, riot, rockstar |
| social | discord, signal, line, threads |
| news | bbc, cnn, nytimes, bloomberg, reuters, wsj, economist, ft, theguardian |
| learning | coursera, edx, khanacademy, stackexchange |
| development | npmjs, python, docker, rust, golang, debian, ubuntu, archlinux, sourceforge, kubernetes, homebrew, fedora, readthedocs, ruby, flutter, dart |

本地保留 YouTube、Netflix、Telegram、IBKR、TradingView、Spotify、Twitch、Reddit、Wikipedia 的收窄清单。其中 IBKR/TradingView 属于用户指定补充，其他清单避免共享域、关联业务或无关服务被整个上游包带入测速。Telegram 14 条 CIDR 来自 [官方网段](https://core.telegram.org/resources/cidr.txt)。Hulu 已包含在 Disney 规则集中。

## 敏感边界与例外

- AI、Meta 商业及共享域名、TikTok Shop、广告/归因后台和已知依赖先匹配敏感主备。AI 策略组只允许指定敏感组，不再通向全节点手动组；兜底直接引用敏感组。
- Threads 的 threads.net/threads.com 按用户要求走普通测速；共享 Meta 资源仍可能被前面的敏感规则接管。
- 上游 LINE 包中的 line.biz、linemyshop.com、lineshoppingseller.com，以及 HBO 包中的 brightline.tv，在前面显式送往敏感组。依据 [LINE 官方商业页面](https://www.lycbiz.com/jp/) 与 [BrightLine](https://brightline.tv/)。
- 上游包含的五个品牌顶级域名空间 bbc/bloomberg/hbo/playstation/xbox 仍以敏感规则覆盖，保留上一版的保守边界。
- Google、Microsoft、GitHub、GitLab、Notion、Figma、Zoom 等混合平台未整体加入普通测速；X 仍保留敏感兜底。同域名内的普通内容与 AI/广告用途无法按页面路径分开。
- 固定版本避免普通清单在无人审阅时扩展。动态 AI 与业务保护优先于普通规则，未知目的地址继续走敏感主备。

## 更新与故障行为

更新只需修改 manifest 的提交或服务名单，审阅完整上游子清单与敏感/共享域重叠，再运行结构测试、真实内核和分流验收。不要手工维护一份逐域名镜像。Mihomo 的普通规则下载显式使用敏感组；Stash 依靠 raw.githubusercontent.com 的前置敏感路由。

首次使用需要下载规则；客户端会缓存。某个普通规则下载失败、且没有可用缓存时，其未匹配流量继续走敏感兜底。已有国内或敏感规则命中的流量仍按更早规则处理。HTTP 404 无缓存场景已用真实 Mihomo 验证。敏感上游下载失败时，已知敏感域名仍有本地补充；无法保证未知、重叠或分类错误的域名被语义识别。

配置中引用规则集不代表其在真实设备上已下载成功。启用后需核对 provider 状态；本地文件和发布验证不能替代客户端实际加载检查。

官方格式依据：[Stash 规则集合](https://stash.wiki/rules/rule-set)、[Mihomo Rule Providers](https://wiki.metacubex.one/en/config/rule-providers/)。
