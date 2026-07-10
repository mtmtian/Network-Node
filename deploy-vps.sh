#!/usr/bin/env bash
# Entry point: configure an already-provisioned Debian/Ubuntu VPS (DMIT, etc.).
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROFILE_NAME="${VPS_PROFILE:-dmit}"
. "$PROJECT_DIR/core/common.sh"
. "$PROJECT_DIR/providers/vps.sh"
. "$PROJECT_DIR/core/deploy.sh"
run_deploy "$@"
