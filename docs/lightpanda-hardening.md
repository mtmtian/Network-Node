# Lightpanda 的 Mihomo 私网保护

## 本次范围与验收

- [x] 单节点、严格模式、汇总及独立节点的 Mihomo 输出，在现有规则之前拒绝 lightpanda 访问约定的 10 个私网/特殊地址段。
- [x] Stash 不加入保护规则，不重写本机已有 Stash 成品或 iCloud 分发文件。
- [x] 固定构造输入比较改前/改后输出；其他路由行为保持不变。
- [x] Python 回归、Shell 语法、Mihomo 配置检查通过。
- [x] 本机 TUN 下：改前复现、改后 lightpanda 拦截；curl 访问同一个受控服务成功；lightpanda 读取公开 JS 页面成功。
- [x] 当前订阅的规则增强文件持久化，运行内核经本机 API 加载后复测通过；未发布远程订阅。
- [x] 用户重新激活当前订阅后，Clash Verge 生成配置及运行内核均保留 10 条置顶保护规则；流量复测通过。远程订阅重新下载未执行。
- [ ] 后续授权：创建 PR，并将同样的 Mihomo 保护发布到现有 Cloudflare 私有订阅；先核对云端节点和策略组，禁止用不完整的本机配置覆盖远程内容。发布结果记录在 PR 中。

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
