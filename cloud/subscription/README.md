# 私有 Mihomo 订阅

使用 Workers Free 与私有 KV，通过 `<worker>.<account>.workers.dev` 提供订阅，无需个人域名。源配置仍在本地，云端仅存验证后的 Mihomo YAML。账户/KV 标识与端点保存在被 Git 忽略的 `wrangler.jsonc` 和 `endpoint.json`，不要把个人部署信息提交到公共仓库。

## 日常使用

在仓库根目录运行：

```bash
python3 aggregate.py render --profile routing
python3 aggregate.py publish --profile routing --client mihomo
python3 subscription.py verify --profile routing
python3 subscription.py copy-link --profile routing
python3 subscription.py import --profile routing
```

`import` 从钥匙串读取令牌，通过标准输入调用 macOS URL handler，使用 `clash-verge://install-config?url=...`。通用 `clash://` 可能被其他客户端注册，因此这里明确指定 Verge。copy-link 每次复制一个链接；日常仅需主配置。系统接受 URL 请求不等于客户端下载成功，必要时使用 copy-link 手动粘贴。已有同一订阅时无需重复导入。调用后客户端可能直接添加订阅；若客户端尚无当前配置，还可能选中它。工具不会主动开启 TUN 或系统代理。未执行导入前不能宣称客户端已经导入或运行通过。

单 VPS 文件从主配置同源生成，例如 `routing-cstone`、`routing-lax`、`routing-gcloud`。使用 `python3 subscription.py publish --profile routing --server gcloud` 发布，copy-link/import/verify 同样接受 --server。共享计划开启 standalone 后，render/check 同时处理所有文件。详见 [单服务器输出](../../docs/aggregate-routing.md#按主配置节点生成单服务器文件)。

`set-token` 首次生成 256-bit 随机令牌并保存在 macOS 钥匙串（服务名 `Network-Node subscriptions`）；已有令牌会复用，不会无故失效旧链接。云端 secret 仅存 SHA256 校验值。完整订阅 URL 属于密码，不写普通文件、命令参数、日志或回复；剪贴板和客户端订阅数据库需要保密。若需撤销泄露令牌，应明确轮换钥匙串条目与云端校验值，并重新导入所有客户端；重新运行 set-token 本身不是轮换。

## 初始部署与维护

已有部署复用当前本地设置，不重复创建 namespace。新部署先确认自己的账户与免费套餐，在本目录执行：

```bash
npm ci
cp wrangler.example.jsonc wrangler.jsonc
cp endpoint.example.json endpoint.json
# 填写 account_id，删除模板中的 kv_namespaces 占位项；填好 endpoint.json
npm test
npx wrangler kv namespace create CONFIGS --binding CONFIGS --update-config
npm run check
npm run deploy
# 回到仓库根目录
python3 subscription.py set-token
python3 aggregate.py publish --profile routing --client mihomo
```

这里的配置文件使用 JSON 语法（Wrangler 接受 JSONC，但发布器按 JSON 读取），不要添加注释或尾随逗号。namespace 创建成功后必须保留返回的绑定 ID；不因后续步骤失败重复创建。

代码部署和 secret put 都是云端写操作。没有设置 TOKEN_SHA256 时所有请求均拒绝，初次部署到写入 secret 之间也不公开配置。Worker 仅支持 GET/HEAD、固定文件路径、单个格式有效的令牌；鉴权在 KV 读取前完成。无公开目录、上传接口或公共存储桶。应用不记录 URL/正文，关闭 Worker observability、日志与 traces，保留平台聚合指标；不承诺云平台完全没有底层访问元数据。

发布器检查本地成品与源一致，再上传固定字节快照；KV API 读回、HTTPS 内容对比、无令牌/错误令牌反向检查都通过才报告成功。验证下载使用 Verge User-Agent；本次默认 Python User-Agent 被 CF 边缘以 1010 拒绝，Verge 标识正常。HTTP 重定向一律拒绝，避免携带令牌跳到其他站点。响应为 private/no-store，建议 24 小时更新。

KV 是最终一致存储，更新后其他地区可能延迟 60 秒或更久。若 HTTPS 仍是旧版本，等待后运行 verify；不要反复上传。验证失败不会自动回滚已写入对象。当前网络下载成功不证明大陆无代理首连可达；必要时先导入本地 YAML。单次发布限制为 1 MiB；免费额度耗尽会失败，本工具不会升级套餐。

## 验证

- `npm test`：真实 workerd + 本地 KV，检查未授权、错误/重复令牌、令牌撤销、无 secret、未知对象、HEAD、禁止写入与内容一致性。
- 仓库 Python 测试含真实 Mihomo 隔离路由验证；`subscription.py verify` 验证实际云端成品。
- 本次验证主配置及单 VPS 成品的 Mihomo schema；未改变运行客户端，未实测 Claude 登录和长连接。

参考：[Verge URI 与响应头](https://www.clashverge.dev/guide/url_schemes.html)、[Verge 协议解析实现](https://github.com/clash-verge-rev/clash-verge-rev/blob/main/src-tauri/src/utils/resolve/scheme.rs)、[Workers 价格](https://developers.cloudflare.com/workers/platform/pricing/)、[KV 免费额度](https://developers.cloudflare.com/kv/platform/pricing/)、[KV 一致性](https://developers.cloudflare.com/kv/concepts/how-kv-works/)。
