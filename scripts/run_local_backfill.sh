#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p logs
rm -rf site/wp-content/uploads/ai
# shellcheck disable=SC1091
source .venv-ai/bin/activate
exec python -u scripts/generate_ai_images.py --local --force
