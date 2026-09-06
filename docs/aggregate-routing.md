# 多服务器汇总与日常分流

`aggregate.py` 将显式列出的本地 profile 汇总成每设备一份客户端配置。默认以 Stash 为目标，支持显式生成 Mihomo。单服务器部署与配置生成入口保持独立；汇总不访问云端、不修改服务端或自动切换客户端。

## 默认行为与手动排查

| 分流入口 | 默认策略 | 可手动调整 |
|---|---|---|
| AI / Meta 服务（包括 Antigravity 应用、Facebook、Instagram、WhatsApp 等） | 敏感服务主备 | 手动选择 |
| 海外流量，包括未匹配请求 | 自动测速 | 手动选择 |
| 国内流量 | DIRECT | 自动测速、手动选择 |
| Apple 基础服务 | DIRECT；Siri 等既有海外规则仍进入海外流量 | 自动测速、手动选择 |
| 屏蔽流量 | REJECT | 自动测速、手动选择、DIRECT |

敏感服务主备按 `sensitive` 数组的顺序执行，示例为 **cstone/Reality → gcloud/CDN**。只引用这些指定节点，不自动退到 GCP 直连、其他服务器、WARP 或 DIRECT。CDN 保护本地到 GCP 的入口；出口仍是 GCP，不能改善目的站对 GCP IP 的信誉判断。切换备用时出口 IP 会改变。主备全部不通时敏感服务失败，用户可以主动切换到手动选择排查。

所有业务组的手动入口指向同一个「手动选择」组，完整节点列表只出现一次。操作顺序：先在「手动选择」中选节点，再把需要排查的业务组切到「手动选择」。这会影响所有已经选择手动的业务组；其他业务组的默认策略不变。排查结束后恢复该业务组的第一个选项。若以后需要多个业务同时固定到不同节点，应增加各自的独立选择组。

普通海外和未匹配流量共用一个入口，不再经过「代理流量 → 代理策略 → 兜底」多层选择。Spotify 保留原有直连行为，使用显式 DIRECT 规则，不显示独立分组，也不会跟随海外流量组选线。局域网保持直连，避免改动业务分流后影响本地设备访问。

「自动测速」每 300 秒测试一次，参与范围是启用来源中当前生成的普通节点；WARP 如已生成，只在手动列表中出现。「敏感服务」每 60 秒检查一次，采用固定优先顺序。它们都跳过不健康节点。HTTP 延迟探测不能等同于下载带宽、IP 信誉或某个网站的业务可用性；连得上测速 URL 但网站异常时需要手动切换。Stash 的测试地址/超时沿用生成器中的节点级 `benchmark-url` / `benchmark-timeout`，不假定 Mihomo 的组级 `url` / `tolerance` 在 Stash 生效。

## 配置与生成

在汇总 profile 下保存 `aggregate.json`，格式参考 [配置示例](../config/aggregate.json.example)：

```bash
mkdir -p profiles/routing
chmod 700 profiles/routing
cp config/aggregate.json.example profiles/routing/aggregate.json
chmod 600 profiles/routing/aggregate.json
python3 aggregate.py render --profile routing
python3 aggregate.py check --profile routing
```

修改 `sources` 中的 profile 名称以匹配实际服务器。`name` 是节点显示前缀，必须唯一；最终名称如 `cstone/Reality`、`gcloud/CDN`。`devices` 显式列出要生成的设备，敏感主备的每个来源都必须具备对应设备凭据。普通来源缺少某设备时，仅从该设备的节点池中省略；明确指定的敏感主备缺失时，整个生成失败并保留已有输出。

输出为 `clash-configs/routing-mac.yaml`、`clash-configs/routing-iphone.yaml`，权限为 `600`，目录为 `700`。各设备只应导入自己的文件。需要 Mihomo 时使用 `--client mihomo`；同名文件会被替换，不能把该目标的文件当成 Stash 配置。

汇总从源 profile 重新生成节点，不依赖已有客户端 YAML 或 iCloud 副本。临时生成目录为私有目录，用后清理；凭据继续归各源 profile 管理，不写进公开规则。生成期间使用 profile 操作锁；遇到部署、换 IP 或源文件变化时停止，避免混合两版状态。源节点生成/校验失败发生在写入前，保留旧输出；发布阶段沿用逐文件原子替换，并非跨文件事务，磁盘写入失败后应修复问题并重新 render/check。

源 profile 的 `CLIENT_CONFIG_ENABLE=false` 会将普通来源移出汇总；若它被指定为敏感主备，则报错，要求明确调整主备计划。不会生成空策略组，因为 Stash 会把空组视为 DIRECT。

增加节点、修改端口/密码、GCP 换 IP、停用来源之后，都需要重新执行 `aggregate.py render` 并更新设备分发副本。`check` 会从当前源重新计算并判断漂移；不会修改现有 YAML，也不测试网络在线状态。源 profile 的 `AI_STRICT_MODE`、国内组偏好只影响其单服务器配置，汇总始终使用本文定义的日常分流策略。

## DNS 与规则边界

AI 和 Meta 的明确域名/域名集共用敏感服务的加密解析器地址，解析器连接路由到「AI / Meta 服务」组，因此切换该组到手动节点时，其 DNS 也跟随选择。普通海外 DNS 使用独立解析器，经海外流量组，避免依赖敏感主备。国内 DNS 沿用国内组；节点域名由 `proxy-server-nameserver` 独立启动解析。规则集下载经普通海外组，避免敏感线路同时故障时影响规则更新。

DNS 分组覆盖静态精确/后缀规则及对应 AI、Meta geosite 集合。域名规则无法推断未知第三方依赖或请求归属；原有 DOMAIN-KEYWORD、IP、协议规则与 DNS 策略也不是逐条等价。新增网站依赖时仍需补精确规则；通配 DNS 规则可能优先于 geosite，见 [Stash DNS 文档](https://stash.wiki/features/dns-server)。

Meta 的静态域名和远程域名集优先于广告拦截、国内分流和普通兜底；AI 认证、上传、监控等已知依赖由共享敏感服务清单生成。汇总仅增补策略，不复制维护另一份完整业务规则。

## 验证

运行时只依赖 Python 标准库。测试使用 PyYAML 独立解析生成的 YAML，验证引用、循环、DNS 路由和客户端字段：

```bash
python3 -m pip install -r requirements-test.txt
python3 -m unittest discover -s tests -p 'test_*.py'
```

真实连通性、Stash 导入后的组选择和设备网络差异，需要在各设备上验证。规则策略类型依据 [Stash 策略组文档](https://stash.wiki/proxy-protocols/proxy-groups)。

Antigravity 应用规则、AI 清单来源、Stash 版本要求及已知覆盖限制见 [AI 分流覆盖说明](ai-routing-coverage.md)。
