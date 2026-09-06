# AI 与 Antigravity 的覆盖边界

核对日期：2026-09-07。目标是让已知海外 AI 服务及其必要登录依赖使用敏感线路，同时为 Antigravity 增加应用级分流；不把所有 Google Cloud、AWS 或 Azure 流量都当成 AI。

## Antigravity：应用优先，域名补充

汇总 Mac 配置在静态局域网规则之后、普通业务和广告规则之前，将以下应用包内的可执行文件送到「AI / Meta 服务」：

- `/Applications/Antigravity.app/`：本机核对版本 2.12.2，含主程序、Electron 辅助程序与 `Contents/Resources/bin/language_server`。
- `/Applications/Antigravity IDE.app/`：当前未安装；这是 2.12.2 Hub 安装代码内明确的独立 IDE 安装目标。

Stash 使用 `PROCESS-NAME` 的包路径前缀模式，末尾 `/` 必须保留；Mihomo 使用单独生成的 `PROCESS-PATH-REGEX`，不能混用两种语义。默认经过敏感服务主备，排查时把「AI / Meta 服务」切到「手动选择」即可。没有增加外显分组。单服务器配置复用同一批域名与应用规则，但出口仍是其既有「AI 隐私出口」组；本文的手动切换步骤指汇总配置。

[Stash Mac 4.2.0 更新记录](https://stash.wiki/en/release-notes/macos)明确新增了末尾 `/` 的进程路径前缀匹配。本机 Stash 为 4.2.0，满足这项规则的版本要求。应用规则依赖客户端能识别连接的本机进程；浏览器登录、应用启动的外部 `curl` / Python / Node、远端 SSH 执行和不在这些包内的工具不继承应用身份。应用移到其他目录后应修改路径。iOS 不支持进程规则，因此只在设备名 `mac` 的配置中输出，其他设备仍依靠域名规则。参见 [Stash 规则类型](https://stash.wiki/rules/rule-types)。

应用规则覆盖包内程序发出的公网业务、更新、插件与遥测请求；局域网优先直连。不能由此声称所有 DNS 查询也带有应用身份：应用未知域名仍可能使用普通海外解析器，所以核心 API 和登录域名需要明确 DNS 策略。

## 同源的域名与 DNS

`core/sensitive-services.json` 是人工维护的必要域名清单，供单服务器生成器与汇总生成器共同使用。汇总 DNS 策略从生成后的精确域名和后缀规则推导，避免两张人工列表漂移。例如 `rum.browser-intake-datadoghq.com` 同时进入 AI 业务与敏感 DNS，修复原先只有宽泛关键词命中的缺口。

| 服务 | 本轮重点锚点 | 核对来源 |
|---|---|---|
| OpenAI / ChatGPT | API、网页、WebSocket、登录、上传、功能开关和指定 Sentry/Datadog 依赖 | [OpenAI 网络建议](https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web) |
| Claude / Anthropic | API、网页、MCP、下载与内容域名 | [Claude Code 网络配置](https://code.claude.com/docs/en/network-config)及原有静态清单 |
| Antigravity / Google AI | 主站、实验开关、Cloud Code、AI Code、生成接口、Google OAuth、userinfo、Vertex AI | 本机 2.12.2 的 `app.asar`、`language_server`；[Antigravity 企业文档](https://antigravity.google/docs/enterprise/) |
| Vertex AI | 根端点及明确地区的 `*-aiplatform.googleapis.com` 主机 | [Google API 参考](https://cloud.google.com/vertex-ai/docs/reference/rest)；新增区域仍需维护 |
| Runway / Replicate / fal | `api.dev.runwayml.com`、`api.replicate.com`、`fal.run` 等 | [Runway API](https://docs.dev.runwayml.com/api.md)、[Replicate HTTP API](https://replicate.com/docs/reference/http/)与[输出文件域名](https://replicate.com/docs/topics/predictions/output-files)、[fal 模型端点](https://docs.fal.ai/model-apis/model-endpoints) |
| Cursor、Windsurf、Copilot、Grok、OpenRouter、Hugging Face、v0 | 产品域名静态锚点与动态 AI 集合 | [MetaCubeX AI 集合快照](https://github.com/MetaCubeX/meta-rules-dat/blob/8964c30fc18a52dfc6761d30c664faaac0c219b1/geo/geosite/category-ai-%21cn.list)，并补充 [v0 当前产品域名](https://v0.app/) |

Antigravity 包内明确包含 `daily-cloudcode-pa.googleapis.com`、`aicode.googleapis.com`、`generativelanguage.googleapis.com`、`oauth2.googleapis.com`、`www.googleapis.com/oauth2/v2/userinfo`、`antigravity-unleash.goog` 等。企业 API、Vertex AI 与导出端点在包内存在，不表示当前个人账号每次都使用。动态集合中的 Antigravity 端点也提升为静态锚点，避免依赖首次规则下载。

HTTPS 规则只能按主机分流，不能区分加密 URL 路径。因此 `www.googleapis.com` 的非 AI API、Google 账号登录，以及既有 `challenges.cloudflare.com`、Stripe/Intercom 等共享依赖，也会进入敏感线路。这是保障登录链路的明确取舍；没有将整个 `googleapis.com`、`googleusercontent.com`、`storage.googleapis.com` 或 `www.gstatic.com` 静态归入敏感服务。

移除 `datadog`、`sentry`、`sift` 的全局关键词和 `sentry.io` 整站静态规则，改用已确认的具体租户/主机。既有 STUN 与 NTP 隐私规则保留，它们是协议/端口策略，不代表对应域名全部属于 AI。Meta 仍合并在同一个服务入口；Spotify 继续显式 DIRECT，国内 AI 未统一强制出海。

## 仍然存在的限制

动态 AI MRS 集合与 DNS geosite 分别更新，可能短期不同步；静态清单保证已列出的必要域名，不承诺覆盖所有 AI、第三方登录、插件、自建 API、新增地区或临时 CDN。Azure OpenAI 与 AWS Bedrock 的所有租户/地区尚未穷举，避免为补 AI 而接管整个公有云。出现具体问题时用连接记录核对域名、进程、规则和实际出口。

Stash 的 `default-nameserver` 只填写 IP，业务 DNS 保持 DoH。[独立节点域名解析](https://stash.wiki/features/dns-server)的 `proxy-server-nameserver` 官方要求 macOS 4.3 / iOS 3.6 及以上；本机 4.2.0 尚不满足这项已有配置要求，不能宣称独立 bootstrap 已在本机验证。应用分流的 4.2.0 支持与这项 DNS 能力是两件事。

自动主备只检查测速地址，不识别 AI 服务的地区限制、账号风控或业务 403。应用规则测试、域名/DNS 回归与 Mihomo 配置检查不能替代实际 Stash 的连接记录验收。
