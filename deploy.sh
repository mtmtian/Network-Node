#!/usr/bin/env bash
# Backward-compatible GCP entry point. New code should use deploy-gcp.sh explicitly.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
printf '\033[1;33m! deploy.sh 保留用于兼容；建议改用 ./deploy-gcp.sh\033[0m\n' >&2
exec "$ROOT/deploy-gcp.sh" "$@"
