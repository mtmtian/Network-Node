#!/usr/bin/env bash
# Entry point: provision and configure a Google Cloud node.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PROFILE_NAME=gcloud VPS_PROFILE=gcloud
STATE_DIR="${NETWORK_NODE_STATE_DIR:-$PROJECT_DIR/profiles/gcloud}"
python3 "$PROJECT_DIR/core/profile_lock.py" "$STATE_DIR" bash -c '
  set -euo pipefail
  PROJECT_DIR="$1"; shift
  . "$PROJECT_DIR/core/common.sh"
  . "$PROJECT_DIR/providers/gcp.sh"
  . "$PROJECT_DIR/core/deploy.sh"
  run_deploy "$@"
' bash "$PROJECT_DIR" "$@"
