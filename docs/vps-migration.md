# VPS migration runbook

The migration contract is intentionally conservative: build a new isolated profile, verify it, import the new client config, and keep the old server available for rollback. The deployment never deletes or disables the source VPS.

## Current CStoneCloud boundary

As checked in the authenticated panel on 2026-08-20, CStoneCloud provides:

- power on/off, reboot, hard power actions, VNC, OS reinstall and rescue mode;
- a reusable SSH-key list with an explicit bind action for the instance;
- Debian 12 x64 and Ubuntu 24.04 x64 images;
- an authentication selector and generated root password in the reinstall dialog.

The password is displayed in clear text. Do not put it in screenshots, shell arguments, repository files or chat. If it is exposed before reinstall, cancel and generate another value; if it was already applied, rotate it.

The public help center still does not expose a supported non-interactive VPS API or CLI for these operations:

- <https://www.cstonecloud.com/index.php?rp=%2Fannouncements%2F1%2FTOSandAUP.html>
- <https://www.cstonecloud.com/knowledgebase>

Therefore this repository automates from the first stable provider boundary: a Debian/Ubuntu host with a public IP and working root SSH. Power, reinstall, rescue and key binding remain explicit panel actions; the project does not scrape or browser-automate the authenticated panel.

## Panel handoff

1. Create or reuse an SSH public key in the panel. Never upload the private key.
2. Reinstall with a supported Debian/Ubuntu x64 image. If the authentication selector offers the saved SSH key, prefer it; otherwise use a newly generated root password.
3. Bind the saved key to the instance after reinstall if it is not already bound. Reinstall may replace `authorized_keys`, so do not assume an older binding survived.
4. From a new local terminal, verify key-only root login before running this project. Do not close the panel/VNC recovery path until this succeeds.
5. Use `--install-key` only when key binding did not produce a working login. Enter the root password interactively; never put it on the command line.

Do not test reinstall or key-removal behavior on the active node merely to validate this runbook. Confirm it during a replacement-node migration where rollback remains available.

## One-command host handoff

Prepare a local keypair once. Keep the private key local and ensure the matching `.pub` file exists beside it.

For a replacement server with the panel-bound key already verified, use cstone's non-secret settings:

```bash
./deploy-vps.sh \
  --profile cstone-next \
  --host <NEW_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" \
  --copy-config-from cstone
```

This sequence:

1. Checks Debian/Ubuntu, x86_64/aarch64, root or passwordless sudo, and systemd before creating profile state.
2. Copies only `profiles/cstone/deploy.conf`. It never copies `.secrets.env`, SSH keys, or generated client YAML.
3. Generates independent credentials under `profiles/cstone-next/`.
4. Creates and verifies the `mt` sudo user before disabling root/password SSH.
5. Installs the server stack and fails the deployment if any required systemd unit is inactive.
6. Generates `clash-configs/cstone-next-*.yaml` without changing cstone's files.

If panel key binding is unavailable or unsuccessful, add `--install-key` to the deployment command. It uses `ssh-copy-id`; the root password is entered interactively and is never stored by this project. To validate an already keyed host without changing it:

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

A dedicated `providers/cstonecloud.sh` is justified only if the provider supplies a documented, non-interactive API/CLI for OS reinstall, SSH-key injection and instance/IP status. The current authenticated web controls are useful recovery and bootstrap tools, but their destructive actions and unstable UI contract make browser automation a poor default.
