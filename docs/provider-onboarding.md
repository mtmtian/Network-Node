# Provider Onboarding

Use one profile per server. A profile name is a local namespace for the server's address, generated credentials, client YAML, and optional SSH key; it is not a provider account password.

## Existing Debian/Ubuntu VPS

1. Install Debian 12/13 64-bit or Ubuntu 24.04 LTS.
2. Prefer binding a saved public key in the provider panel, then verify root key login from a new terminal. If that fails, use the provider's root password interactively with `--install-key`. Keep the private key on the local machine only.
3. Run the generic VPS entry point with an explicit, unique profile name. For a CStoneCloud replacement that should inherit the current profile's non-secret settings:

```bash
./deploy-vps.sh --profile cstone-next --host <VPS_PUBLIC_IP> \
  --ssh-key "$HOME/.ssh/cstone_ed25519" \
  --copy-config-from cstonecloud-cuii-a
```

Add `--install-key` only if the provider did not install the public key. Use a different profile for every server, for example `cstonecloud-cuii-a`, `cstone-next`, or `new-york-01`. Do not run `./deploy-vps.sh` without a profile. Copying a profile resets `CLIENT_FILE_PREFIX`, disables CDN, clears its hostname/path, and assigns a new Tunnel name. Confirm a distinct hostname before enabling CDN on the new server.

If a local TUN/VPN intercepts SSH traffic, pass the physical interface explicitly, for example `--ssh-interface en0`. This applies `BindInterface` to both SSH and SCP without changing the server or disabling the local proxy.

Connection options are saved automatically in `profiles/<profile>/connection.conf`. Later runs only need `./deploy-vps.sh --profile <profile>`; explicit CLI options take precedence. Credentials remain in `.secrets.env` and need not be memorized. `python3 node.py status --profile <profile>` shows their location without showing their values.

The first run creates `profiles/<profile>/deploy.conf` and `.secrets.env`, secures the host, creates the `mt` sudo user, installs the shared protocols, and writes:

```text
clash-configs/<profile>-mac.yaml
clash-configs/<profile>-iphone.yaml
```

After the first successful run, root login is disabled and `mt` is the maintenance user:

```bash
ssh -i "$HOME/.ssh/cstone_ed25519" mt@<VPS_PUBLIC_IP>
```

## Google Cloud account and billing changes

Use `./deploy-gcp.sh` for the existing Google Cloud profile. Its first successful configuration saves `GCP_ACCOUNT` in `profiles/gcloud/deploy.conf`; preflight verifies that account can refresh its authorization, and provisioning, SSH, and SCP use it explicitly. Switching the global gcloud account does not change the profile's account. SSH private keys stay in the profile's `ssh/` directory.

If IAP needs the workstation's local proxy, set `GCP_HTTP_PROXY` to its HTTP proxy URL in that profile. The deployment process passes it to gcloud; it does not change client routing or server egress. Keep the local proxy running while using IAP. Leave it empty where direct access works.

When only promotional credits are expiring, prefer changing the billing account attached to the existing Cloud project. Verify the destination account is open and the credit has been redeemed with a scope covering Compute Engine. Grant the destination user the project roles needed for billing and node administration before changing the billing link. Personal projects can require an invitation to add another Owner; use the required service roles when full ownership transfer is unnecessary.

Changing the billing link keeps the VM, IP, credentials, and client YAML. Verify the new billing association and node connectivity, then save the intended administration account as `GCP_ACCOUNT`. Do not delete the old VM or project as a billing migration step. Charges incurred before the switch remain on the original billing account; monthly credits and budget alerts do not impose a hard spending cap.

## Adding another provider lifecycle

Use `deploy-vps.sh` when the provider already exposes a reachable Debian/Ubuntu host. Add a new adapter under `providers/` only when the provider needs different lifecycle, authentication, or firewall operations. Keep shared protocol installation, secrets, routing, and client generation in `core/`.

## Profile isolation checklist

- Choose a new profile name before touching a new host.
- Keep `deploy.conf`, `.secrets.env`, and `ssh/` inside that profile only.
- Keep generated YAML in `clash-configs/`; never stage `profiles/`, SSH keys, or client YAML.
- Regenerate one profile's clients with:

```bash
python3 node.py render --profile <profile>
```

The default client is Stash with daily split routing (`AI_STRICT_MODE=false`, `PRIVACY_MODE=false`): ordinary domestic traffic goes direct and known AI dependencies take priority on the AI route. Set `CLIENT_TARGET=mihomo` for Mihomo. Strict routing of all public traffic, including domestic sites, requires explicitly setting `AI_STRICT_MODE=true`. Removing a device and deploying automatically rotates the profile's shared AnyTLS password; remaining devices must import fresh YAML. Rendering alone does not revoke server credentials.

- Before pushing, verify:

```bash
git ls-files profiles
```

The command must print nothing.
