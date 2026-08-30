#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
exec "$HOME/.hermes/scripts/dakota-qa-gate.sh" --repo "$ROOT" --mode test "$@"
