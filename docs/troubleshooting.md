# Troubleshooting Notes

## Node Timeout But Server Is Running

This note records a real failure mode: the client showed proxy node timeouts, while the GCP VM and proxy services were still running normally.

### Symptoms

- The client imports the generated YAML successfully.
- All proxy nodes show timeout during testing.
- Rule providers may still load, or may be unrelated to the failure.
- The VM is running and the proxy ports are reachable from the public Internet.

### Root Cause

The generated client YAML pointed to an outdated IP address in `profiles/gcloud/.secrets.env`:

- `STATIC_IP` in `profiles/gcloud/.secrets.env` had an old value.
- The existing VM had a different current external IP.
- Service credentials and ports were correct, but clients were connecting to the wrong address.

When the client reports the node itself as timeout, check the server address first. Routing rules only decide where traffic goes after a proxy connection exists; they do not normally break the proxy handshake itself.

### Checks

Use the profile-aware read-only check. It pins the account/project and compares
the reservation's owner, tier and address against the VM and local state without displaying credentials.

```bash
python3 node.py ip-check --profile gcloud
```

If the cloud reservation and VM disagree, fix the intended binding first. Re-running
deployment now stops on this mismatch instead of publishing the unattached reservation.

### Fix

1. When the cloud binding is correct but the local IP is stale, synchronize the IP and regenerate YAML:

```bash
python3 node.py ip-sync --profile gcloud
```

2. Synchronize distribution copies and reload the regenerated YAML on each device. Verify the active client actually uses the new node configuration.

If the direct IP is blocked from the client network, first test the independent CDN entrance:

```bash
python3 node.py cdn-check --profile gcloud
```

This verifies authenticated VLESS traffic through CF and a verified HTTPS target. It does
not change the GCP egress IP, and OS-level TUN routing can still affect the local test.
For address replacement, rollback and release of retained addresses, use the
[GCP recovery commands](../README.md#gcp-ip-故障恢复). Do not delete the old reservation
before validating the new connection and synchronizing devices.

Restarting the VM is not required when only the generated client YAML is wrong. Re-run the same provider entry point or restart services only when the server-side ports, credentials, or service configs changed.

### Prevention

- Treat each `profiles/<provider>/` directory as one local state bundle; keep generated clients in `clash-configs/` with the profile prefix and never mix provider state or `ssh/` files.
- If a static IP is deleted or the VM external IP changes, regenerate client YAML immediately.
- Do not commit profile `.secrets.env`, SSH keys, or generated client YAML; they contain real server details and credentials.

## 中文总结：节点 Timeout 但服务端正常

这次问题不是规则集导致的。客户端显示“节点 timeout”时，优先怀疑节点地址、端口、防火墙、服务状态或协议兼容；规则集只影响连接建立后的分流。

本次根因是本地 `profiles/gcloud/.secrets.env` 里的 `STATIC_IP` 仍是旧地址，而 GCP 上现有 VM 的外部 IP 已变化。服务端 `xray`、`hysteria`、`anytls` 都正常运行，端口也开放，密钥/UUID 与本地配置一致；客户端只是连到了错误地址。

处理方式：

1. 运行 `python3 node.py ip-check --profile gcloud`。
2. 云端绑定正确但本地记录过期时，运行 `python3 node.py ip-sync --profile gcloud`。
3. 同步 iCloud 等分发副本，并在客户端重新加载、验证实际代理连接。

只修正客户端 YAML 时不需要重启 VM。只有服务端端口、凭据或 systemd 服务配置发生变化时，才需要重跑原平台入口或重启相关服务。

风险点：如果 VM 没有绑定保留静态 IP，重启或重建后外部 IP 可能再次变化。生产使用建议确认静态 IP 存在且绑定到 VM。
