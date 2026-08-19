# 仓库总览与维护说明

这份说明回答三个问题：仓库各部分负责什么、一次部署如何流转、日常修改应该改哪里。

## 一句话定位

这是一个“共享代理核心 + 多 provider 入口 + 每台服务器独立 profile”的自托管节点部署仓库。

- 共享核心负责协议、密钥、服务端配置、Cloudflare 可选出口和 Stash-first/Mihomo-compatible YAML 生成。
- provider 只负责服务器生命周期、连接方式和防火墙。
- profile 负责把某一台服务器的地址、密钥、SSH 私钥和客户端状态隔离开。

## 目录职责

```text
deploy-gcp.sh / deploy-vps.sh  用户入口
deploy.sh                      旧 GCP 入口兼容别名
core/                          共享部署核心
providers/                     GCP / 通用 VPS 生命周期适配器
config/                        不含密钥的默认配置模板
profiles/<profile>/            本地敏感状态，不提交
clash-configs/                 生成的客户端 YAML，不提交
tests/                         部署、生成器、下载、Stash 兼容断言和 Mihomo 集成测试
docs/                          架构、排障和运维说明
```

### `core/` 内部边界

| 文件 | 责任 |
|---|---|
| `common.sh` | profile 路径、配置/密钥加载、密钥写入和日志辅助函数 |
| `secrets.sh` | 本地生成或复用端口、UUID、密码和可选 CDN 凭据 |
| `deploy.sh` | 编排共享部署流程，调用 provider 和客户端生成器 |
| `cloudflare.sh` | 创建/复用 Tunnel、配置 Ingress、写入 CNAME 和连接 Token |
| `setup-server.sh` | 在远端安装 Xray、Hysteria2、AnyTLS、cloudflared 和 systemd 服务 |
| `download.sh` | 远端二进制下载、重试和超时 |
| `gen-clash.py` | 每个设备生成一份 Stash-first、Mihomo-compatible YAML |

## 部署路径

### CStoneCloud / 已有 Debian/Ubuntu VPS（当前主路径）

```bash
./deploy-vps.sh --profile cstone-next --host <VPS_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" \
  --install-key --copy-config-from cstone
```

VPS 适配器负责可选的交互式公钥安装、远端 readiness、创建 `mt` 管理员、UFW 和文件上传。每台 VPS 必须使用唯一 profile，避免误读另一台服务器的状态。迁移时只复制旧 profile 的非密钥 `deploy.conf`，不会复制凭据或客户端 YAML。

### GCP（当前未使用）

`deploy-gcp.sh` → `providers/gcp.sh` → `providers/gcp-provision.sh` → `core/deploy.sh`

GCP adapter 暂时保留，负责项目预检、静态 IP、VM、防火墙和 IAP SSH；它不属于当前 cstone 运行路径。

## 一次部署的实际顺序

```text
入口脚本
  ↓
provider 预检与读取 profile
  ↓
已有 VPS：只读检查 OS、架构、权限与 systemd
  ↓
生成/复用本地凭据
  ↓
CDN_ENABLE=true 时：先完成 Cloudflare API / Tunnel / DNS
  ↓
连接并加固服务器，配置 UFW
  ↓
上传 server-env.sh 和安装脚本
  ↓
安装并重启服务，回收 Reality 公钥
  ↓
按设备生成 <profile>-<device>.yaml
```

Cloudflare 阶段在服务器修改之前执行。这样 Token、权限或 DNS 配置错误会在本地提前停止，不会先改防火墙再失败。

新机迁移与回滚见 [VPS 迁移运行手册](vps-migration.md)，Xray、Hysteria2、AnyTLS 和 systemd 的保留/退出条件见 [协议栈评估](protocol-stack.md)。

## 节点和流量关系

默认部署会生成三条直连节点，开启 CDN 后增加一条 CDN 节点：

```text
US-Reality  ───────────────→ VPS IP:443
US-Reality-WARP ───────────→ VPS IP:WARP_REALITY_PORT → WARP → 互联网（可选，手动节点）
US-HY2      ───────────────→ VPS IP:随机 UDP 端口
US-AnyTLS   ───────────────→ VPS IP:随机 TCP 端口
US-CDN      → cdn.example.com → Cloudflare → Tunnel → VPS localhost:8080
```

- 只有 `US-CDN` 使用域名和 Cloudflare Tunnel。
- `US-Reality-WARP` 直连 VPS，但仅该节点的 Xray 出站经过 WARP；它不隐藏 VPS 入口，只保留为手动可选节点，不加入自动测速或自动故障切换。
- `CDN_ONLY=false` 时，直连节点继续保留，适合先灰度验证 CDN。
- `CDN_ONLY=true` 时，服务端关闭 Reality/Hysteria2/AnyTLS 直连入口，只保留 Cloudflare WS；切换前必须重新生成并导入 YAML。
- `WARP_ENABLE=true` 与 `CDN_ONLY=true` 互斥。
- `🛟 自动故障切换`、`⚡ 自动测速` 只是客户端策略组，不是额外的服务器节点。
- `PRIVACY_MODE=true`（默认）让 `🇨🇳 国内流量` 首次默认走代理；客户端可手动切到 `DIRECT`，`false` 则让该组首次默认直连。直连时，`geosite:cn` 域名使用阿里云 / 腾讯云的加密 DoH，避免明文 DNS 和海外解析造成的 CDN 绕路；国内 DoH 服务商仍能看到查询出口 IP。其他域名继续使用经代理路由的 Cloudflare / Google DoH。局域网与原有 Apple/Spotify 规则不受影响。
- CN 判定依次使用 MetaCubeX `cn` 域名集、`cn-ip` 地址集和 Mihomo `GEOIP,CN` 兜底；AI、Google、Apple、Telegram、广告等更高优先级规则先匹配，`private`/LAN 则始终固定直连。
- `🤖 AI 隐私出口` 只使用共享 Xray IPv4 出口，按 Reality → CDN（启用时）故障切换；STUN 同组且不受 `PRIVACY_MODE` 影响，避免 AI HTTP 与 WebRTC UDP 因双栈或 WARP 显示不同地址。
- AI 域名使用 MetaCubeX `category-ai-!cn`；Anthropic/Claude 的核心域名、认证/CDN、监控与第三方组件、Anthropic IP 段/ASN、NTP 和 STUN 使用高优先级静态规则，置于广告拦截及所有直连规则之前。`IP-ASN` 需要客户端加载 ASN 数据库，NTP 需要代理节点支持 UDP；中国 AI 域名仍不在该集合内。

## Profile 和文件安全边界

每台服务器只允许有一个本地状态包：

```text
profiles/<profile>/
├── deploy.conf       # 本机部署参数
├── .secrets.env      # 端口、UUID、密码、Token
└── ssh/              # 本机 SSH 私钥
```

这些内容全部属于敏感本地状态，不应提交、上传或粘贴到聊天。生成的 YAML 也含真实地址和凭据，因此默认只保存在本机/设备同步目录，不进入 Git。

公共代码只应依赖环境变量和 profile 状态，不要把某台服务器的 IP、域名、Token 或 SSH 文件写进 `core/`、`providers/`、`README.md` 或测试样例。

客户端文件默认使用 `<profile>-<device>.yaml` 命名。如果某台服务器需要更短的设备文件名，可在该 profile 的 `deploy.conf` 设置 `CLIENT_FILE_PREFIX`；前缀和设备名只允许字母、数字、点、下划线和连字符。生成器先验证全部设备凭据并原子替换每份 YAML，全部新文件就绪后才清理当前前缀的旧文件；这只改变 `clash-configs/` 下的文件前缀和清理范围，不改变 profile 状态目录，也不会让不同服务器共用凭据。

### 交接时的文件边界

交接或同步仓库时，只同步公共代码、测试和不含凭据的文档。以下内容始终留在本机或设备同步目录，不应进入提交、压缩包、工单或聊天：

- `profiles/` 下的 `deploy.conf`、`.secrets.env` 和 `ssh/` 私钥；
- `clash-configs/` 下的客户端 YAML；
- 本机 MCP、浏览器或其他工具配置，例如 `config/mcporter.json`。

如果部署时临时通过 `VPS_SSH_KEY=/path/to/private-key` 指定了外部私钥，交接前应将它放回对应的 `profiles/<profile>/ssh/`，并确认权限为 `600`。仓库只记录使用方式，不记录私钥路径、内容或服务器凭据。

## 常用维护动作

### 重跑同一台服务器

```bash
./deploy-vps.sh --profile <profile> \
  --ssh-key "$PWD/profiles/<profile>/ssh/id_rsa.pem"
```

重跑会复用本地凭据和已有管理员。只有修改服务端参数、协议凭据或组件版本时，才需要重跑；只改客户端规则时不需要重启服务器。

### 只重新生成客户端 YAML

```bash
NETWORK_NODE_PROFILE=<profile> python3 core/gen-clash.py
```

### 启用 CDN

1. 域名托管到 Cloudflare。
2. 在 `profiles/<profile>/.secrets.env` 写入最小权限 `CF_API_TOKEN`。
3. 在 `profiles/<profile>/deploy.conf` 设置 `CDN_ENABLE=true`、`CDN_ONLY=false`、`CDN_HOSTNAME` 和 `CDN_TUNNEL_NAME`。
4. 重跑对应部署入口。
5. 导入新 YAML，先测试 `US-CDN`，确认后再考虑 CDN-only。

脚本会自动创建/复用 Tunnel、配置 CNAME、生成连接 Token 和客户端节点，不需要手动填写 Tunnel CNAME 目标。

## 修改时的判断规则

- 协议、systemd、服务端入站：改 `core/`。
- GCP/VPS 登录、服务器创建、UFW、文件传输：改 `providers/`。
- 默认参数：改 `config/deploy.conf.example`。
- 用户操作路径和故障处理：改 `README.md` 或 `docs/`。
- 新增或修复行为：先补 `tests/`，再改实现。
- 客户端共享 YAML：优先使用 Stash 已文档化的格式；Mihomo-only 语法必须拆分客户端目标并补回归测试。
- 不要为了单台服务器的特殊值修改共享核心；放入对应 profile。

## 发布前检查

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
bash -n deploy.sh deploy-gcp.sh deploy-vps.sh core/*.sh providers/*.sh
git diff --check
git ls-files profiles
```

最后一条必须没有输出。生成的 profile、SSH 私钥、`.secrets.env` 和客户端 YAML 都不应进入提交。

交接说明至少应记录：当前分支和提交、已验证的测试/语法检查、主动维护的 profile 名称，以及未同步的本地敏感状态；不要在交接文本中粘贴节点密码、UUID、Token、私钥或客户端 YAML 内容。
