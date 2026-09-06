# Architecture

The repository keeps protocol behaviour and client routing rules in one shared core while isolating provider-specific lifecycle operations and credentials behind adapters and profiles.

## Entry points

- `deploy-gcp.sh` loads the Google Cloud adapter.
- `deploy-vps.sh` is the active CStoneCloud/generic Debian/Ubuntu path and requires an explicit profile.
- `deploy.sh` is a compatibility alias for the GCP entry point.

Deployment entry points hand control to `core/deploy.sh`. `node.py` handles local status, validation, rendering and drift checks without connecting to a server.

## Provider seam

Each provider adapter implements the same shell interface:

- `provider_init`: parse provider-specific arguments.
- `provider_preflight`: validate local tools and authentication.
- `provider_readiness` (optional): validate remote OS, architecture, privilege and systemd without changing the target.
- `provider_configure`: create or load provider configuration.
- `provider_provision`: obtain and secure a reachable host.
- `provider_install`: copy and execute the shared server installer.
- `provider_print_summary`: print provider-specific handoff details.

The shared pipeline owns key generation, optional Cloudflare setup, server-environment construction, Reality public-key recovery, and Clash/Mihomo configuration generation.

## Data flow

```text
entry point -> provider adapter preflight/config
            -> shared secrets -> optional Cloudflare API setup
            -> provider host setup -> shared server install
            -> shared client config generation
```

Cloudflare setup runs before host changes when `CDN_ENABLE=true`. This makes missing
API tokens, permissions, or DNS access fail locally before the VPS firewall or services
are changed. The host installer receives only the generated connector token; the API
token used to manage Cloudflare remains local.

Provider state is isolated below `profiles/`:

```text
profiles/
├── cstone/                    # current active VPS profile
│   ├── deploy.conf
│   ├── .secrets.env
│   └── ssh/id_rsa.pem
└── cstone-next/               # replacement/new VPS, independent credentials
    ├── deploy.conf
    ├── .secrets.env
    └── ssh/                    # optional local-only key storage

clash-configs/
├── cstone-{mac,iphone}.yaml
└── cstone-next-{mac,iphone}.yaml
```

The entire `profiles/` tree is gitignored. This keeps host lifecycle state and credentials separate while both providers continue to consume the same protocol installer and routing-rule template.

Each profile owns its state and optional host credentials. Generated client YAML is centralized in `clash-configs/` and an exact ownership manifest prevents overlapping prefixes from deleting another profile's files. Unknown legacy files and manually edited stale files are retained. The VPS entry point rejects missing or unsafe profile names to prevent accidental cross-provider writes.

The client pipeline is `settings.py` (literal configuration and validation) → `gen-clash.py` (device nodes) → `client.yaml.tmpl` and `client_policy.py` (shared rules, explicit Stash/Mihomo fields, strict/daily routing) → `client_output.py` (locked output ownership and atomic file replacement). Daily routing is the default: known AI dependencies take priority, ordinary domestic traffic goes direct, and domestic DNS follows the domestic group. Strict mode is opt-in and has two groups and two remote rule sets, routing all public application traffic through the shared Xray IPv4 exit.
