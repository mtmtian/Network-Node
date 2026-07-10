# Architecture

The repository keeps protocol behaviour and client routing rules in one shared core while isolating provider-specific lifecycle operations behind adapters.

## Entry points

- `deploy-gcp.sh` loads the Google Cloud adapter.
- `deploy-vps.sh` loads the generic Debian/Ubuntu VPS adapter.
- `deploy.sh` is a compatibility alias for the GCP entry point.

All entry points hand control to `core/deploy.sh`.

## Provider seam

Each provider adapter implements the same shell interface:

- `provider_init`: parse provider-specific arguments.
- `provider_preflight`: validate local tools and authentication.
- `provider_configure`: create or load provider configuration.
- `provider_provision`: obtain and secure a reachable host.
- `provider_install`: copy and execute the shared server installer.
- `provider_print_summary`: print provider-specific handoff details.

The shared pipeline owns key generation, optional Cloudflare setup, server-environment construction, Reality public-key recovery, and Clash/Mihomo configuration generation.

## Data flow

```text
entry point -> provider adapter -> shared secrets -> provider host setup
            -> shared server install -> shared client config generation
```

Provider state is isolated below `profiles/`:

```text
profiles/
├── gcloud/
│   ├── deploy.conf
│   ├── .secrets.env
│   └── clash-configs/gcloud-{mac,iphone}.yaml
└── dmit/
    ├── deploy.conf
    ├── .secrets.env
    └── clash-configs/dmit-{mac,iphone}.yaml
```

The entire `profiles/` tree is gitignored. This keeps host lifecycle state and credentials separate while both providers continue to consume the same protocol installer and routing-rule template.
