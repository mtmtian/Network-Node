#!/usr/bin/env bash
# Entry point: provision and configure a Google Cloud node.
set -euo pipefail
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
. "$PROJECT_DIR/core/common.sh"
. "$PROJECT_DIR/providers/gcp.sh"
. "$PROJECT_DIR/core/deploy.sh"
run_deploy "$@"
