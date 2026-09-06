# shared helpers — source this file. POSIX-bash 3.2 compatible (macOS default).

PROJECT_DIR="${PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PROFILE_NAME="${PROFILE_NAME:-gcloud}"
STATE_DIR="${NETWORK_NODE_STATE_DIR:-$PROJECT_DIR/profiles/$PROFILE_NAME}"
CLIENTS_DIR="${NETWORK_NODE_CLIENTS_DIR:-$PROJECT_DIR/clash-configs}"
SSH_DIR="$STATE_DIR/ssh"
CONF_FILE="$STATE_DIR/deploy.conf"
SECRETS_FILE="$STATE_DIR/.secrets.env"
CONFIG_TEMPLATE="$PROJECT_DIR/config/deploy.conf.example"

# --- logging ---
say() { printf '\033[1;36m▸ %s\033[0m\n' "$*"; }
ok()  { printf '\033[1;32m✓ %s\033[0m\n' "$*"; }
warn() { printf '\033[1;33m! %s\033[0m\n' "$*" >&2; }
die() { printf '\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# --- config / secrets loading ---
load_conf() {
  local values
  values="$(python3 "$PROJECT_DIR/core/settings.py" conf-shell "$STATE_DIR")" || return
  eval "$values"
}
load_secrets() {
  local values
  values="$(python3 "$PROJECT_DIR/core/settings.py" settings-shell "$STATE_DIR")" || return
  eval "$values"
}

# secret_get KEY  -> prints current value from .secrets.env (empty if absent)
secret_get() {
  [ -f "$SECRETS_FILE" ] || return 0
  python3 - "$PROJECT_DIR/core" "$SECRETS_FILE" "$1" <<'PY'
import sys
sys.path.insert(0, sys.argv[1])
from settings import load_kv
print(load_kv(sys.argv[2]).get(sys.argv[3], ""), end="")
PY
}

# setkv KEY VALUE  -> replace-or-add in .secrets.env and export into env
setkv() {
  local k="$1" v="$2" tmp
  touch "$SECRETS_FILE"; chmod 600 "$SECRETS_FILE"
  tmp="$(mktemp "$STATE_DIR/.secrets.XXXXXX")"
  grep -vE "^$k=" "$SECRETS_FILE" > "$tmp" 2>/dev/null || true
  printf '%s' "$v" | python3 -c 'import shlex, sys; print(sys.argv[1] + "=" + shlex.quote(sys.stdin.read()))' "$k" >> "$tmp"
  mv "$tmp" "$SECRETS_FILE"; chmod 600 "$SECRETS_FILE"
  export "$k=$v"
}

# ensure_secret KEY VALUE  -> set only if currently absent/empty
ensure_secret() {
  local cur; cur="$(secret_get "$1")"
  [ -n "$cur" ] || setkv "$1" "$2"
}

# indirect var read, bash-3.2 safe:  varval NAME
varval() { eval "printf '%s' \"\${$1:-}\""; }
