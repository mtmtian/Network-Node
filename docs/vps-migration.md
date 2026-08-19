# VPS migration runbook

The migration contract is intentionally conservative: build a new isolated profile, verify it, import the new client config, and keep the old server available for rollback. The deployment never deletes or disables the source VPS.

## Current CStoneCloud boundary

As checked on 2026-08-20, CStoneCloud's public site documents a panel-provided Linux `root` password and SSH on port 22, but its public help center does not expose a supported VPS API or CLI for reinstalling the OS, injecting a key, or reading lifecycle state:

- <https://www.cstonecloud.com/index.php?rp=%2Fannouncements%2F1%2FTOSandAUP.html>
- <https://www.cstonecloud.com/knowledgebase>

Therefore this repository automates from the first stable provider boundary: a Debian/Ubuntu host with a public IP and working root SSH. It does not scrape the authenticated panel or drive an unknown interactive console.

## One-command host handoff

Prepare a local keypair once. Keep the private key local and ensure the matching `.pub` file exists beside it.

For a replacement server that should use cstone's non-secret settings:

```bash
./deploy-vps.sh \
  --profile cstone-next \
  --host <NEW_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" \
  --install-key \
  --copy-config-from cstone
```

This sequence:

1. Uses `ssh-copy-id` to install the public key when the new host initially exposes only a root password. The password is entered interactively and is never stored by this project.
2. Checks Debian/Ubuntu, x86_64/aarch64, root or passwordless sudo, and systemd before creating profile state.
3. Copies only `profiles/cstone/deploy.conf`. It never copies `.secrets.env`, SSH keys, or generated client YAML.
4. Generates independent credentials under `profiles/cstone-next/`.
5. Creates and verifies the `mt` sudo user before disabling root/password SSH.
6. Installs the server stack and fails the deployment if any required systemd unit is inactive.
7. Generates `clash-configs/cstone-next-*.yaml` without changing cstone's files.

If the public key is already installed, omit `--install-key`. To validate an already keyed host without changing it:

```bash
./deploy-vps.sh --profile cstone-next --host <NEW_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" --check-only
```

## Cutover and rollback

1. Import a `cstone-next` YAML on one device and verify Reality plus at least one fallback.
2. Import the remaining device configs only after that smoke test passes.
3. Keep the old cstone server and client profile until the new node has been stable for the chosen observation window.
4. Cancel or erase the old VPS only as a separate, explicit provider action. This repository deliberately has no automatic destroy path.

## Provider lifecycle automation later

A dedicated `providers/cstonecloud.sh` is justified only if the provider supplies a documented, non-interactive API/CLI for OS reinstall, SSH-key injection and instance/IP status. If the panel's "command-line tool" has a product name or a redacted help screen, capture that interface first; do not automate it with brittle keystroke scripts by default.
