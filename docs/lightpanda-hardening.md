# Lightpanda 的 Mihomo 私网保护

## 本次范围与验收

后续本地对齐收尾：

- [x] 核对云端主订阅、三份单服务器订阅与本地源的差异。
- [x] 将现役主策略纳入显式 Mihomo 主配置选项，迁移本机共享计划。
- [x] 对比四份本地产物与云端所有配置字段；核验 Stash 原文件哈希。
- [ ] 回归、独立审查、PR/CI 与文档收尾；保留尚未被客户端接管的保护层。

- [x] 单节点、严格模式、汇总及独立节点的 Mihomo 输出，在现有规则之前拒绝 lightpanda 访问约定的 10 个私网/特殊地址段。
- [x] Stash 不加入保护规则，不重写本机已有 Stash 成品或 iCloud 分发文件。
- [x] 固定构造输入比较改前/改后输出；其他路由行为保持不变。
- [x] Python 回归、Shell 语法、Mihomo 配置检查通过。
- [x] 本机 TUN 下：改前复现、改后 lightpanda 拦截；curl 访问同一个受控服务成功；lightpanda 读取公开 JS 页面成功。
- [x] 当前订阅的规则增强文件持久化，运行内核经本机 API 加载后复测通过；未发布远程订阅。
- [x] 用户重新激活当前订阅后，Clash Verge 生成配置及运行内核均保留 10 条置顶保护规则；流量复测通过。远程订阅重新下载未执行。
- [x] 后续授权：已创建 PR #24，并为现有 Cloudflare 的 4 份生产 Mihomo 订阅定向增加保护；KV/HTTPS 读回与鉴权反向检查通过。详见下方远程发布记录。

## 验收场景（实现前约定）

1. Given lightpanda 请求 fake-IP 域名，When Mihomo 将真实目标解析为 127.0.0.1，Then 在任何 DIRECT 或代理出站规则之前 REJECT，临时 HTTP 服务不收到该请求。
2. Given curl 请求同一域名和端口，When 经过相同 TUN，Then 仍收到临时服务的 HTTP 200 和固定测试标记。
3. Given lightpanda 请求公开 JS 页面，When 页面正常可达，Then HTTP 200 且能读取 JS 生成的正文。
4. Given Stash 目标，When 生成相同构造输入，Then 不新增 Mihomo 保护规则；忽略源码修订注释后输出与改前一致。已有 Stash 成品必须逐字节不变。
5. Given Mihomo 单节点普通/严格模式或汇总/独立节点，When 生成配置，Then 10 条保护规则置顶，进程条件在 IP 条件之前，规则不含 no-resolve，后续原有规则不变。

## 边界

仅保护被 Mihomo 接管且成功识别为 `lightpanda` 的连接。直接内网地址继续由 `lightpanda-safe` 拦截；TUN 路由排除、进程识别失败、全局模式、远端再次解析及其他浏览器不属于这组规则的完整安全保证。此配置不是沙箱。

本机加固阶段未更新其他机器、技能仓库、Notion 或远程订阅；后续远程发布另行核验并在 PR 记录结果。运行验收只访问自建固定响应的临时服务，不读取已有本机服务。

## 实现与查看顺序

1. `core/client_policy.py`：单一网段清单及 `protect_lightpanda`；进程条件在前，IP 条件允许解析。Stash 直接返回原文。
2. `core/gen-clash.py` 与 `core/client_aggregate.py`：完成原有路由转换后再调用保护函数，避免严格模式按逗号处理时破坏 AND 语法；覆盖汇总的独立节点输出。
3. `tests/test_lightpanda_policy.py`：验证普通/严格模式、两种客户端、汇总和独立节点的规则顺序及数量。`tests/test_aggregate.py` 的出站合法性检查增加 AND 的目标提取，仍检查每一条规则，没有跳过或放宽目标集合。
4. `tests/lightpanda_live_probe.py`：显式调用的本机 TUN 验收脚本。临时服务仅监听回环、仅返回随机测试标记，结束必定关闭；公网检查只报告状态和是否取得渲染后的引文，不输出网页正文。

## 2026-11-04 验收记录

修改基线为 `188b523`；以下是本机加固阶段的验收，PR 与云端发布状态以 PR 记录为准。

### 输出对比

使用现有测试中的构造节点、域名及占位凭据；没有使用实际节点凭据建立基准。共 12 份输出：单节点普通/严格模式各 2 份，汇总和 3 个独立节点各 2 份。

| 类别 | 数量 | 改前/改后差异 |
|---|---:|---|
| Mihomo | 6 | 每份新增 10 条置顶保护规则；源码修订注释变化；其他内容相同 |
| Stash | 6 | 仅源码修订注释变化；其他内容逐字节相同 |
| 本机原有客户端文件 | 11 | SHA-256 全部不变 |

只执行了 `aggregate.py render --profile routing --client mihomo`，生成本机 2 份 Mihomo 成品；随后对应 `check` 通过。未渲染或分发 Stash。

### 流量实测

本机运行内核经 API 确认为 **Mihomo v1.19.32**，`rule` 模式、TUN gVisor、`find-process-mode: strict`。应用附带的 v1.19.33 用于隔离配置检查，不能与运行版本混同。

| 请求 | 改前 | 加载保护规则后 |
|---|---|---|
| lightpanda → `127.0.0.1` | CouldntConnect，服务无请求 | 相同 |
| lightpanda → `localhost` | CouldntConnect，服务无请求 | 相同 |
| lightpanda → `localhost.ptlogin2.qq.com` | CouldntConnect，服务无请求 | 相同 |
| lightpanda → `localhost.weixin.qq.com` | HTTP 200，收到测试标记，服务收到请求 | GotNothing，未收到标记，服务未收到请求 |
| curl → 同一域名、同一测试服务 | HTTP 200，收到标记 | HTTP 200，收到标记 |
| lightpanda → 公开 JS 引文页 | HTTP 200，取得 JS 生成的引文 | HTTP 200，取得 JS 生成的引文 |

改前能访问、改后被拒绝构成反向验证；不能仅凭报错判断拦截，所以同时核对了服务端请求记录。所有临时服务均已关闭。

内核 API 已读回 10 条置顶 AND/REJECT，原有 **393 条规则的类型、目标和顺序保持不变**；API 对 GEOIP payload 的大小写规范化已纳入核对。规则集动态大小不作为路由差异。当前订阅增强文件中的 10 条规则与生成器一致。没有安装 lightpanda 或进程未运行的设备不满足进程条件；本机通过 curl 验证了不匹配该进程的连接仍能访问测试服务，未逐个操作所有桌面应用。

### 验证命令

在仓库根目录执行：

```sh
MIHOMO_BIN='/Applications/Clash Verge.app/Contents/MacOS/verge-mihomo' \
MIHOMO_DATA_DIR="$HOME/Library/Application Support/io.github.clash-verge-rev.clash-verge-rev" \
PYTHON="$PWD/.venv/bin/python" \
.venv/bin/python -m unittest discover -s tests -p 'test_*.py' -q
# 123 tests / OK；无跳过。含真实内核路由测试及配置解析。

for script in deploy.sh deploy-gcp.sh deploy-vps.sh core/*.sh providers/*.sh; do
  bash -n "$script" || exit
done
git diff --check
git ls-files profiles
# 均通过；最后一条无输出。

VPS_PROFILE=routing .venv/bin/python aggregate.py check --profile routing --client mihomo
.venv/bin/python tests/lightpanda_live_probe.py --expect blocked --public
```

`--expect reachable --public` 仅用于加固前的基线复现；不要为重跑基线撤销已生效的保护。此脚本不是普通测试发现的一部分，需要主动执行，避免每次单元测试都访问当前系统网络。

### 持久化与剩余范围

本机当前远程订阅的规则增强层已保存 `prepend`；当前运行内核通过 Unix socket 的配置 API 载入同样的规则，未强制重启、未打印或备份凭据、未改写 Clash Verge 的生成文件。服务启动参数中的 socket 才是实际接口，生成文件记录的 socket 路径在本机不适用。

桌面控制工具中途失效后，用户于 2026-11-04 确认已点击「重新激活订阅」。随后只读核验：Clash Verge 重新生成的配置前 10 条与生成器完全一致，运行内核 v1.19.32 的 403 条规则中恰有 10 条 lightpanda 规则置顶，rule/TUN/strict 仍开启。

重新执行 `tests/lightpanda_live_probe.py --expect blocked --public` 返回成功：lightpanda 访问 `localhost.weixin.qq.com` 为 GotNothing，测试服务无请求；curl 对照仍为 HTTP 200 且收到标记；公开 JS 页面为 HTTP 200 且有渲染引文；直接 IP、localhost 和原 fake-ip-filter 域名仍被拦截。临时服务已关闭。**重新激活订阅后的持久化验收已完成**；远程订阅重新下载未执行。

另一台机器、实际切换 Wi-Fi、逐个验证全部 10 个地址段、远端代理再次解析的目的地址、无头 Chrome 均未测试。本次未把这些项目计入完成。

## 2026-11-04 远程发布记录

PR：<https://github.com/mtmtian/Network-Node/pull/24>。功能代码为 `6fe38af`，本次仅更新既有 Worker 的 CONFIGS KV 对象，未重部署 Worker、创建资源或轮换令牌。Wrangler 通过设备授权登录并使用 macOS 钥匙串；本机部署元数据从现有 Worker 绑定恢复到 Git 忽略的设置文件，原订阅令牌从本机已有订阅恢复到项目指定钥匙串条目，未输出或备份凭据。

### 为什么没有直接覆盖发布

首次远程发布时，本机聚合计划生成按设备区分的旧文件，云端使用共享订阅。对比发现：本地和云端主配置的 10 个节点完全一致，但策略组、DNS、部分路由不同；云端主配置原有 393 条规则，本机对应成品原有 347 条。因而不能用这台机器的完整成品覆盖云端。

此次在内存中读取现有生产 KV 原文，经已审查的 `protect_lightpanda` 增补规则；独立 YAML 解析确认仅多出 10 条置顶规则，移除新增部分后与原文逐字节一致。每个候选经 Mihomo `-t` 校验，配置通过 stdin 输入，没有把含凭据的云端原文存为临时文件。写入前再次核对原文 SHA-256，拒绝覆盖检查后发生变化的对象；每个对象仅写入一次，并完成 KV 与 HTTPS 读回。

这是一项有明确基线的定向发布，当时**本机聚合计划尚未与远程完整策略对齐，也没有绕过标准发布器后声称 `subscription.py verify` 通过**。该计划及生成源现已按下节对齐，保留云端已有策略。

| 生产对象 | 节点数（未变） | 规则数 | 发布后 SHA-256 |
|---|---:|---|---|
| routing | 10 | 393 → 403 | `702858e1bdd8fc403b90a4fa3aaf6b62d104cb1160f50474034c63cd4d163953` |
| routing-cstone | 3 | 347 → 357 | `0b720e56a77ccfa16ee1b52288b3b8aba29f222b8b08e20396f167d2f14f57bd` |
| routing-gcloud | 4 | 347 → 357 | `f1a6782d66225611a05ec82c57b8330adb424a0b7bdd43e6cc94302ad8b765e1` |
| routing-lax | 3 | 347 → 357 | `ca207db4edc65c60c9df7ff83e8f458f36b566b3c61de937da9b8eb8c4d966a1` |

四个对象均：HTTP 200、HTTPS 内容 SHA-256 与已验证候选一致、恰有 10 条保护规则；缺少令牌和错误令牌的访问均为 HTTP 404。每份只增加 651 字节。历史测试对象 `routing-test-20260926` 未修改，Stash 未修改。

云端发布不等于所有设备已刷新。本机增强层暂时保留，避免尚未下载新订阅时出现保护空档；若客户端合并时不去重，刷新后可能有同样的规则重复，但不会改变拒绝结果。确认设备已采用云端规则后再清理该本地增强，不在此次远程发布中删除。其他设备的实际下载与运行仍待各机验收。


## 本地生成源对齐与收尾

2026-11-04，以已发布的四份 HTTPS 订阅为独立基线，在内存中验证完整 YAML 配置对象相等后，迁移本机 routing 为共享 mac 凭据身份，并开启 standalone 与 `mihomo_main_policy: daily`。源服务器状态、凭据和账号清单未改。选项及路由定义见 [汇总策略](aggregate-routing.md#mihomo-主订阅的现役日常策略)。主配置使用 daily；三份独立文件沿用原严格策略。

- 四份本地成品的所有配置字段与云端相等：主配置 10 节点 / 403 规则，cstone 3 / 357，lax 3 / 357，gcloud 4 / 357。全部恰有 10 条保护规则。
- `aggregate.py check` 和标准发布器的 `verified_file` 源/归属检查通过；四份真实成品均经 Mihomo v1.19.33 `-t` 校验。今后可走标准发布命令，不需要再次手工补丁。
- **字段相等不等于文件字节相等**：本地模板注释、排版及修订标记不同。本轮未为统一注释重写云端；`subscription.py verify` 的逐字节一致条件不作为本轮已通过项。下次标准 publish 会发布这些等价的新序列化字节，并执行其逐字节读回检查。
- 固定构造输入 8 份默认策略输出，改前/改后仅模板修订及两处说明注释变化，配置字段及规则均不变；开启 daily 只改变 Mihomo 主配置，净增 46 条规则、替换 3 条出口，并恢复对应 DNS、两组选择行为和规则下载出口。测试中的四个生产基线哈希在实现前采集，不含节点凭据；完整规则顺序、DNS、67 个 provider、8 个策略组均参与比较。
- 本轮开始时实际盘点的 7 份 Stash 本地/iCloud YAML，SHA-256 全部不变。迁移共享计划不会自动渲染或分发 Stash；未来主动渲染的命名影响已在汇总文档说明。
- 126 项 Python 测试通过，无跳过；Shell 语法、diff 检查通过。新增验收先在旧生成器确认无法接受 daily 计划，再确认新生成器与独立生产基线相符；非法策略值和旧设备计划边界另有回归。

可复跑的只读云端对比（需要既有钥匙串令牌与 PyYAML，不输出凭据）：

```sh
VPS_PROFILE=routing .venv/bin/python aggregate.py check --profile routing --client mihomo
VPS_PROFILE=routing .venv/bin/python tests/subscription_policy_probe.py \
  --profile routing --server cstone --server lax --server gcloud
```

客户端只读复核：Clash 运行 403 条规则、10 条 Lightpanda 保护，rule/TUN/strict 开启，生成规则与对齐后的本地源一致。订阅下载缓存仍为 393 条、无保护规则，因此暂留 10 条本地增强。只有确认更新订阅已下载云端版本后，才能删除重复增强并重新激活验收；本地仓库的对齐不依赖这一步。

收尾边界：PR #24 未合并，保留当前分支以供审阅；只存在当前一个 worktree。原有 profiles、部署元数据、依赖环境、旧客户端文件及未审计缓存均保留。记忆与其他项目不在本次写入范围。
