# OMB agy 与 balanced 主订阅

同账号、同模型经一个出口返回地区不支持、经另一个出口可以生成时，应固定实际 API 出口。换 DNS 或普通测速不证明模型地区资格。

## 使用方式

将以下选项添加到现有共享汇总计划，不替换 sources、snapshot、sensitive 或身份字段：

```json
{
  "mihomo_main_policy": "balanced",
  "mihomo_agy_proxy": "gcloud/CDN"
}
```

节点名是示例。`mihomo_agy_proxy` 可省略；设置时必须是当前主配置和 sensitive 清单中的 `server/Reality` 或 `server/CDN`，不接受 DIRECT 或规则分隔符。该选择只影响 OMB 官方 ACP / localharness 进程访问 googleapis.com，不接管其他程序的 Google API、浏览器或工具访问的网站。

仅 Mihomo 主配置启用 balanced；Stash、派生单服务器文件及既有 strict/daily 策略保持原行为，不会给不含指定节点的单机输出添加悬空引用。

| 行为 | balanced |
| --- | --- |
| 敏感组 | select 手动选择，不扩展允许节点 |
| 未知流量 | 普通海外组兜底；国内仍靠明确域名白名单 |
| 默认及已列普通海外 DNS | Google + Cloudflare 四个 DoH 地址，不承诺顺序主备 |
| AI / 国内 DNS | 保留 Cloudflare / 国内解析器及原有专门策略 |
| 其他已知敏感业务 DNS | 保留 Quad9 + DNS.SB 冗余 |
| Apple AI | 官方 PCC / 扩展主机及 smoot 后缀优先进入 AI 组 |
| Siri / Private Relay | 保留优先的敏感线路规则 |
| Apple 基础白名单 | Apple/iCloud 基础组首选 DIRECT；国内 Apple 白名单仍在国内组 |

没有将整个 Apple 根域直连。进程规则位于局域网规则之后，Lightpanda 十条保护仍置顶。Apple AI 主机依据：[Apple 企业网络说明](https://support.apple.com/en-us/101555)。网络路由通过不等于 Apple AI、Siri 或 Private Relay 的账号与地区资格已验收。

## 发布及客户端接管

```sh
python3 aggregate.py render --profile routing --client mihomo
python3 aggregate.py check --profile routing --client mihomo
python3 aggregate.py publish --profile routing --client mihomo
python3 subscription.py verify --profile routing
```

先核对节点字段、未涉及的输出和完整规则顺序，并用真实 Mihomo 检查成品。只有规则配置变化时，不必重部署 VPS 或 Worker、创建资源、换密钥或换订阅链接；发布只更新既有 KV 的主配置对象。

Clash 沿用原链接更新。确认下载缓存已有新策略后，去掉此前仅为本任务添加的规则/脚本增强，重新激活，读回内核并验证实际请求。不要清空夹带其他修改的扩展，不改变其他选择。云端发布不代表所有设备已生效。

发布器要求汇总主计划显式声明 mihomo_main_policy。旧计划仍可渲染，但缺省策略不得直接发布主订阅，防止另一台机器漏掉本地选项而自动采用 strict；人为显式选择错误策略仍需靠成品审阅发现。

回退时明确选择旧策略、重新生成发布并更新客户端，不覆盖私有节点，也不恢复未经核对的整份配置。实际设备功能、账号资格、IPv6 和网络切换分别验收。
