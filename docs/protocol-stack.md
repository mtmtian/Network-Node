# Protocol stack assessment

Assessment date: 2026-08-20. This document records the role of each component; it is not a claim that every fallback is regularly used.

| Component | Current role | Decision | Rationale |
|---|---|---|---|
| Xray + VLESS/REALITY | Primary TCP path and optional Cloudflare/WARP routing | Keep | This is the main client path and the only component that also owns the optional Xray routing topology. Project X currently describes REALITY as a strong direct transport-security option. |
| Hysteria2 | UDP/QUIC fallback | Keep | It fails differently from the TCP primary path and is useful on lossy or high-BDP routes when UDP is available. The official server installer also assumes systemd on mainstream Linux. |
| AnyTLS | Secondary TCP fallback | Observe, then consider opt-in/removal | It overlaps the TCP primary path. Its upstream calls `anytls-go` a protocol reference implementation rather than a feature-complete production client. That is a reason to reduce reliance, not enough evidence to silently remove an existing fallback. |
| systemd | Process supervision and boot persistence | Keep | It provides restart policy, dedicated service users, capabilities and filesystem hardening. Replacing it with ad-hoc background processes would reduce reliability and security. |

Primary references:

- Xray REALITY: <https://xtls.github.io/en/config/transports/reality.html>
- Hysteria installation and systemd service: <https://v2.hysteria.network/docs/getting-started/Server-Installation-Script/>
- AnyTLS upstream: <https://github.com/anytls/anytls-go>
- systemd execution environment: <https://www.freedesktop.org/software/systemd/man/latest/systemd.exec.html>

## Version posture

The repository pins versions so a routine redeploy cannot silently upgrade a live node. At assessment time:

- Xray is pinned to `v26.3.27`; newer GitHub releases exist, but the visible recent series is marked pre-release. Do not auto-follow latest.
- Hysteria is pinned to `app/v2.10.0`; upstream latest is `app/v2.12.1`. This is a staged upgrade candidate after client compatibility and one-node smoke testing.
- AnyTLS `0.0.13` matches the latest upstream release visible at assessment time.

Version refresh should be a separate change with release-note review, generated-config validation and a live canary. It should not be bundled into new-provider onboarding.

## REALITY target risk

The template currently uses `1.1.1.1:443` with empty SNI. Xray's official documentation warns that unauthenticated REALITY traffic is forwarded to the configured target; a special/CDN target can turn the VPS into an unintended forwarding path after scanning. The docs also warn that fallback rate limiting creates its own fingerprint.

Do not mechanically add a fixed rate limit or pick another global CDN hostname. The better follow-up is to choose and validate a target appropriate to the server ASN, then update `REALITY_TARGET` and `REALITY_SNI` per profile. Until that decision is tested on cstone, the existing value remains unchanged to avoid breaking the active node.

## AnyTLS exit criterion

Do not remove AnyTLS based only on lack of recent manual use. First confirm that clients are not selecting it during a defined observation window and that Reality plus Hysteria cover the required failure modes. If that evidence holds, make AnyTLS opt-in for new profiles, verify cstone migration, and only then remove its firewall rule, binary, unit, secret and generated node as one coordinated change.
