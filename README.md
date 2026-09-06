# Self-hosted Network Node

一套共享代理核心。当前主路径是把 CStoneCloud 或其他已有 Debian/Ubuntu VPS 接入独立 profile；仓库仍保留未启用的 Google Cloud adapter。

One shared proxy core. The active path configures an existing CStoneCloud or other Debian/Ubuntu VPS; the unused Google Cloud adapter remains available.

- Primary: VLESS + Reality
- UDP fallback: Hysteria2
- TCP fallback: AnyTLS
- One YAML per device; credentials managed automatically within each profile

## 快速开始

公共依赖：本机安装 `python3`、`openssl` 和 OpenSSH。

### CStoneCloud / 已有 Debian/Ubuntu VPS

新机安装 Debian/Ubuntu 后，优先在 CStoneCloud 面板的「SSH 密钥」页面绑定本机公钥，然后复制当前 CStoneCloud profile 的非密钥配置、生成全新凭据并部署：

```bash
./deploy-vps.sh \
  --profile cstone-next \
  --host <VPS_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" \
  --copy-config-from cstonecloud-cuii-a
```

绑定后先用一个新终端验证 root 公钥登录。若面板没有注入公钥，再加 `--install-key`：它会调用系统 `ssh-copy-id` 并交互式提示输入 root 密码；密码不会写入项目、参数或日志。该私钥旁需要存在同名 `.pub` 公钥文件。

部署前也可先做不改远端、不创建 profile 的 readiness 检查：

```bash
./deploy-vps.sh --profile cstone-next --host <VPS_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" --check-only
```

`VPS_PROFILE` / `--profile` 必须为每台 VPS 使用唯一名称，例如 `cstonecloud-cuii-a`、`cstone-next`、`los-angeles-02`。
不要裸跑 `./deploy-vps.sh`，这样可以避免新服务器误用已有 profile。

VPS adapter 会执行以下安全步骤：

1. 验证初始 root 公钥登录。
2. 创建并验证独立的 `mt` sudo 用户。
3. 配置 UFW，只开放 SSH 和三个代理端口。
4. 确认 `mt` 可以登录后才禁用 root 和密码登录。
5. 安装三套协议并生成设备 YAML。

重跑时会直接复用已经创建的 `mt` 用户，不再依赖 root。

主机、SSH 端口、管理员、私钥路径及 `--ssh-interface` 会自动保存在 profile 的 `connection.conf`。
保存过连接设置后，重跑只需 `./deploy-vps.sh --profile <profile>`；显式命令参数优先于保存值。
复制 profile 只继承协议偏好，默认关闭 CDN、清空原域名并使用新 Tunnel 名，避免误改另一台机器的资源。

不要把私钥复制到服务器、Git 跟踪文件或聊天中。

首次部署后可以把主机专用私钥放在 `profiles/<profile>/ssh/`，也可以继续通过
`VPS_SSH_KEY=/path/to/private-key` 显式指定。后续重跑时使用同一个 `VPS_PROFILE`，脚本会复用该 profile 的 IP、端口和本地密钥。

完整迁移边界、回滚顺序和 CStoneCloud 控制台限制见 [VPS 迁移运行手册](docs/vps-migration.md)。协议与进程管理取舍见 [协议栈评估](docs/protocol-stack.md)。

### Google Cloud（当前未使用）

GCP 节点通过 `./deploy-gcp.sh` 管理，与普通 VPS 共用协议和分流配置。GCP profile 保存 `GCP_ACCOUNT`，后续操作固定使用该账号；更换赠金账户可以改绑现有项目的结算账户，无需重建服务器。流程见 [Provider Onboarding](docs/provider-onboarding.md#google-cloud-account-and-billing-changes)。

## 目录结构

```text
deploy-gcp.sh / deploy-vps.sh   用户入口
deploy.sh                       旧 GCP 命令的兼容入口
providers/                      GCP、普通 VPS adapter
core/                           共享部署流水线、密钥、协议安装、规则与 YAML 生成
config/                         不含密钥的配置模板
docs/                           架构说明与排障文档
profiles/<profile>/             每台服务器独立状态与 ssh/（不提交）
clash-configs/                  所有 profile 的客户端 YAML（不提交）
```

GCP 和 VPS 真正变化的只有服务器生命周期、连接方式与防火墙；协议和客户端规则只维护一份。详细 seam 和 provider interface 见 [架构说明](docs/architecture.md)。

想快速理解整个仓库，先看[仓库总览与维护说明](docs/repository-guide.md)；它把入口、部署链路、profile、直连/CDN 节点和日常操作放在一处。

独立的 VPS 库存监控已迁至
[`vps-stock-opencli`](https://github.com/mtmtian/vps-stock-opencli)，不再属于本仓库的代码或测试边界。

## 配置

首次运行会从 `config/deploy.conf.example` 创建当前 profile 的本地状态。GCloud 固定使用
`profiles/gcloud/`；普通 VPS 使用 `VPS_PROFILE` 对应的 `profiles/<profile>/`。整个
`profiles/` 目录都已被 Git 忽略。

| 配置 | 默认值 | 说明 |
|---|---|---|
| `CLIENT_CONFIG_ENABLE` | `true` | 设为 `false` 跳过此 profile 的客户端输出，保留状态与凭据；不操作服务器 |
| `CLIENT_TARGET` | `stash` | 生成 Stash 或 `mihomo` 对应字段 |
| `AI_STRICT_MODE` | `false` | 默认日常分流：AI 优先保护、国内默认直连；`true` 才将全部公网统一到 AI 线路 |
| `REALITY_PORT` | `443` | Reality 监听端口 |
| `REALITY_TARGET` / `REALITY_SNI` | `1.1.1.1:443` / 空 | Reality 目标与客户端 SNI |
| `HY2_PORT` | 随机 | Hysteria2 UDP 端口 |
| `HY2_PORT_RANGE` | 空 | 可选端口跳跃范围，例如 `30000-30010` |
| `HY2_OBFS_ENABLE` | `false` | 可选 Salamander 混淆；开启后不再表现为标准 HTTP/3 |
| `HY2_ACME_ENABLE` | `false` | 可选 Cloudflare DNS-01 真实证书 |
| `ANYTLS_PORT` | 随机 | AnyTLS TCP 端口 |
| `DEVICES` | `mac iphone` | 每设备独立 Reality/HY2 凭据及 YAML；AnyTLS 为 profile 共享密码，自动管理 |
| `PRIVACY_MODE` | `false` | 仅日常分流生效：国内组默认直连；`true` 则默认代理 |
| `CDN_ENABLE` | `false` | 可选 Cloudflare Tunnel 出口 |
| `CDN_ONLY` | `false` | 仅使用 Cloudflare WS，并关闭直连代理端口 |
| `WARP_ENABLE` | `false` | 可选 Reality-WARP 节点；仅该节点的 Xray 出站经过 WARP |
| `WARP_SOCKS_PORT` | `40000` | 服务器本机 WARP SOCKS5 端口，不对公网开放 |
| `WARP_REALITY_PORT` | 随机 | Reality-WARP 直连端口；开启 WARP 时自动生成 |
| `PROJECT_ID` / `REGION` / `ZONE` | GCP 默认值 | 只由 GCP adapter 使用 |

每个 profile 内的敏感文件均已 gitignore：

- `.secrets.env`
- `deploy.conf`
- `connection.conf`
- `ssh/`

不要提交、转发或粘贴这些文件的内容。

配置采用字面值 `KEY=value`，支持引号和行末注释；不会执行 shell 或展开 `$HOME`、`$(...)`。
明确填写的端口优先于已保存状态；端口和 WS 路径留空时复用自动生成的值。

**密码无需记忆。** 每个 profile 自动生成并复用凭据，位置固定为 `profiles/<profile>/.secrets.env`。
运行 `python3 node.py status --profile <profile>` 可查看文件位置，不显示密码。备份时保存完整 profile（包括 `ssh/`），
不要只备份客户端 YAML。Reality、HY2、CDN 和 WARP 使用独立设备凭据；AnyTLS 官方服务端使用每 profile 一个密码。
移除设备并重新部署时，工具会自动轮换 AnyTLS 密码、删除该设备的旧凭据；剩余设备需要导入新 YAML。
单独运行 `render` 不轮换密码，也不会在服务器上撤销设备。

## 导入客户端

部署成功后，每个平台默认得到两份名称明确的 YAML：

- `clash-configs/gcloud-mac.yaml`
- `clash-configs/gcloud-iphone.yaml`
- `clash-configs/<profile>-mac.yaml`
- `clash-configs/<profile>-iphone.yaml`

生成器通过精确文件归属清单管理输出，不按前缀通配符删除。`cstone` 与 `cstone-next` 可以安全共存；
不同 profile 指定相同输出文件会报错。旧版本未登记的文件、移除设备后被手工修改的文件会保留。
客户端 YAML 权限为 `600`，输出目录为 `700`，因为其中含节点地址、UUID 和密码；
这可阻止同一台电脑上的其他系统用户读取。iCloud 副本用于设备同步，不作为项目源状态。

- Stash（首要兼容目标）：从配置文件页面导入本地或 iCloud YAML
- Clash Verge：Settings → Profiles → Import
- 其他客户端：使用支持 Reality、Hysteria2 和 AnyTLS 的 Mihomo/Clash.Meta 兼容客户端

`CLIENT_TARGET=stash` 为默认目标，使用 Stash 的 HY2 `auth`、`up-speed/down-speed`、DNS `follow-rule` 和 STUN 协议规则；
`CLIENT_TARGET=mihomo` 生成 Mihomo 字段和 TUN 设置。两种目标共用源规则，但不能把同一份 YAML 视为两端字段完全等价。
Stash 的节点域名独立解析功能需要 iOS/tvOS 3.6 或 macOS 4.3 及以上版本。

**默认使用日常分流：普通国内网站直连，AI 核心服务及已知依赖优先走 AI 线路。**
`AI_STRICT_MODE=false`、`PRIVACY_MODE=false` 为默认值。静态内网规则最先匹配，AI/认证/第三方依赖保护先于广告拦截和国内域名/IP 分流，
因此一个已识别的 AI 依赖即使解析到国内地址，也不会被后面的 CN 规则抢走。普通国内网站由 `.cn`、CN 域名集和 CN 地址规则送入国内流量组，首次默认 `DIRECT`。

AI 组只按 Reality → CDN（启用时）切换，使用同一 VPS 的 Xray IPv4 出口，不加入 HY2、AnyTLS 或 WARP。
普通海外流量保留 Reality → CDN → HY2 → AnyTLS 故障切换；Apple 基础服务和 Spotify 保留原有直连策略，WARP 仅供手动选择。
未匹配任何规则的流量默认代理，不会因开启国内直连而将全部未知请求直连。

AI 动态规则使用 MetaCubeX `category-ai-!cn`，既有监控/认证依赖保护保留在广告规则之前，
并补充 [OpenAI 官方网络白名单](https://help.openai.com/en/articles/9247338-network-recommendations-for-chatgpt-errors-on-web) 中的 WorkOS、Statsig、功能开关、支付和 Apple 集成域名。
规则引擎无法判断未知第三方请求属于哪个页面；发生漏网请求时应补精确依赖规则。广告规则仍可能拦截尚未识别的依赖，可临时将广告组切到代理排查。

国内域名使用国内加密 DoH，并把这些解析器 IP 显式关联到国内流量组，默认直连；手动切换国内组时，这部分 DNS 连接也跟随该组。
其他业务 DNS 使用固定经 AI 组出站的 Cloudflare/Google DoH。节点域名仍通过单独的直连加密 DNS 启动解析，避免代理尚未建立时的递归依赖。
DNS 服务商可看到其收到的查询及来源；客户端配置只控制进入其规则引擎的流量。

**严格模式保留为可选项，不默认启用。** 设置 `AI_STRICT_MODE=true` 后，国内网站、Apple、Spotify 和未知第三方请求也进入 AI 线路，
只保留 AI 与广告两个策略组、两个远程规则集，不依赖 GeoIP/ASN 数据库完成公网兜底。HY2、AnyTLS、WARP 节点仍被生成，但严格模式不会选择它们。
AI 入口全部不可用时，公网业务失败；国内业务 DNS 分支也被移除。希望国内网站直连时保持 `AI_STRICT_MODE=false`。

如需真正隐藏源站 IP，把 `CDN_ENABLE=true` 和 `CDN_ONLY=true` 同时设置；这会关闭直连 Reality/Hysteria2/AnyTLS，保留 Cloudflare WS 入口。

### WARP 出站（低延迟优先的可选路径）

`WARP_ENABLE=true` 会在 VPS 上安装 Cloudflare WARP 的 SOCKS5 代理，并额外生成 `US-Reality-WARP`：客户端仍直连 VPS，只有该节点的 Xray 出站经过 WARP。现有 `US-Reality`、`US-HY2` 和 `US-AnyTLS` 不变。

这条路径不隐藏 VPS 入口 IP，因此不能和 `CDN_ONLY=true` 同时启用。WARP 只接入 Xray/Reality，Hysteria2 和 AnyTLS 暂不走全局策略路由；服务端会每 60 秒检查一次真实 SOCKS 出口并尝试自愈。

`HY2_PORT_RANGE`、`HY2_OBFS_ENABLE`、`HY2_ACME_ENABLE` 均为可选增强：开启后需要重新部署服务端并重新生成客户端 YAML；默认关闭时不改变已有协议行为。

修改 `DEVICES` 后重跑同一个 profile 的入口，即可增加或撤销设备。

自签名 HY2 证书在下次成功部署后自动回传 SHA256 指纹并写入 YAML；已有 profile 尚无指纹时保留原兼容行为。
ACME 证书使用可持久写入的 `/var/lib/hysteria/acme`。AnyTLS 的临时自签名证书与 HY2 ACME 相互独立，
目前仍需跳过证书链验证，且官方服务端密码会出现在服务进程参数中；严格模式不选择该节点。

### Cloudflare CDN 首次启用

先把域名接入 Cloudflare，并在目标 profile 的 `.secrets.env` 写入最小权限 API Token：

```text
Account → Cloudflare Tunnel → Edit
Zone → Zone → Read
Zone → DNS → Edit
```

Zone 资源只选择目标域名。然后在该 profile 的 `deploy.conf` 设置：

```text
CDN_ENABLE=true
CDN_ONLY=false
CDN_HOSTNAME=cdn.example.com
CDN_TUNNEL_NAME=<profile>-cdn
```

重新运行对应部署入口即可自动创建/复用 Tunnel、配置 Ingress、写入橙云 CNAME 并生成 `US-CDN`。
首次保持 `CDN_ONLY=false`；CDN-only 切换前会从本机验证已经部署的 CDN 通道。缺少 API Token 或
Cloudflare 权限不足时，部署会在修改服务器前停止，不会留下半套 VPS 配置。

CDN 用于本地网络无法直连 VPS IP 时的备用入口，最终仍从同一 VPS 出网。服务端检查 Tunnel
实际连接数，本机再检查所有设备的 TLS → WebSocket → VLESS → HTTPS 请求，全部通过才生成 YAML。
也可单独运行 `python3 node.py cdn-check --profile gcloud`；这个命令忽略 HTTP 代理环境变量，
不回退到 Reality，但操作系统的 TUN 仍可能影响底层网络，不能代替手机移动网络实测。
本机运行 TUN 时可在 profile 设置 `PROBE_INTERFACE=en0`（换成实际物理网卡）；工具会将
AliDNS DoH 查询和 CDN/IP 探测连接都绑定到该网卡，避免系统 fake-IP 或其他代理造成假阳性。
该设置只影响本机验收，不改变客户端流量和 GCP 管理代理；目前支持 macOS/Linux。

自动故障切换组每 60 秒检查，关闭 lazy；Stash 节点显式设置 5 秒测试超时。这个间隔是检查频率，
不是保证的恢复时限，已有长连接仍可能需要重连。

### GCP IP 故障恢复

```bash
python3 node.py ip-check --profile gcloud     # 只读核对预留地址、VM 绑定和本地记录
python3 node.py ip-sync --profile gcloud      # 云端绑定正确时，同步本地 IP 和 YAML
python3 node.py ip-rotate --profile gcloud    # 显示换 IP 计划
python3 node.py ip-rotate --profile gcloud --apply
```

换 IP 不重装服务、不轮换协议凭据：保留旧静态地址，预留并绑定新地址，经本机 Reality TCP
端口验收后更新 `IP_NAME`、`STATIC_IP` 和 YAML。失败会尝试恢复旧绑定及 YAML；云端仍有未完成
操作时停止反向修改，保留恢复记录，稍后运行 `ip-rollback --profile gcloud --apply`。
TCP 可达不等于 Reality 认证通过，仍需在设备上验证实际代理流量。

新地址确认可用并完成设备同步后，先运行 `ip-finalize --profile gcloud` 查看释放计划，再加
`--apply` 永久释放未使用的保留地址。释放后不能回滚；保留地址可能持续计费，不应长期忘记清理。
存在上次恢复记录时不能再次换 IP。所有操作固定使用 profile 的账号和项目，并与 GCP 部署互斥。

源 YAML 位于 `clash-configs/`；iCloud 是分发副本，需要同步文件并让各设备重新加载。
此工具不会自动修改 iCloud、删除旧客户端配置、判断 IP 已被封，或循环申请地址。

## 重跑与维护

- 两个入口均按幂等方式设计，会复用已有服务器和本地密钥。
- 本地管理：`python3 node.py <status|validate|render|check> --profile <profile>`。四个命令均不访问服务器；`render` 只更新本地 YAML。
- 停用机器可在其 profile 设置 `CLIENT_CONFIG_ENABLE=false`；生成和一致性检查会提示跳过，`status` 可查看启停状态。旧 YAML 不会自动删除，可移入 `clash-configs/archive/<profile>/` 保存；恢复输出时将开关改回 `true`。
- `check` 只读检查 YAML 是否对应当前源，`validate` 检查配置完整性；修改规则不必重跑完整部署。
- 临时指定输出目标：`python3 node.py render --profile <profile> --client mihomo`。同一 profile 使用同一组输出文件名，切换目标会替换这些 YAML。
- 服务端组件版本固定；升级须同时核验并更新 `core/download.sh` 的 SHA256。下载缓存按摘要复用，每次使用仍校验。
- 远端安装使用独立临时目录和部署锁；二进制及 Xray 配置保存 `.previous`，Xray 先校验再替换。这不是全服务自动回滚。
- SSH 先检查语法和生效配置再 reload；UFW 开放新端口后移除已登记的旧端口，不清空其他应用的规则。
- GCP 旧命令 `./deploy.sh` 仍可使用，但会提示改用 `./deploy-gcp.sh`。
- 通用排障见 [Troubleshooting](docs/troubleshooting.md)。
- 新服务器接入和隔离规则见 [Provider Onboarding](docs/provider-onboarding.md)。

## English

### Choose one entry point

```bash
# Active path: configure an existing CStoneCloud/Debian/Ubuntu VPS
./deploy-vps.sh --profile cstone-next --host <VPS_PUBLIC_IP> --ssh-key "$HOME/.ssh/cstone_ed25519" --copy-config-from cstonecloud-cuii-a

# Google Cloud: provision or maintain a node using its saved account
./deploy-gcp.sh
```

Both entry points run the same shared pipeline:

1. Validate provider-specific requirements.
2. Generate per-device credentials locally.
3. Provision or secure a reachable host.
4. Install BBR, Xray/Reality, Hysteria2, AnyTLS, systemd units, and security updates.
5. Recover the Reality public key and generate one Stash-first, Mihomo-compatible YAML per device.

The provider adapters only own host lifecycle, connectivity, and firewall behaviour. Key generation, server configuration, routing rules, optional Cloudflare setup, and client generation remain in `core/`.

For a non-default VPS key:

```bash
VPS_PROFILE=<profile> VPS_SSH_KEY=/path/to/private-key ./deploy-vps.sh <VPS_PUBLIC_IP>
```

Never copy private keys or `.secrets.env` into Git-tracked files, onto the server, or into chat.

## License

MIT — see [LICENSE](LICENSE).
