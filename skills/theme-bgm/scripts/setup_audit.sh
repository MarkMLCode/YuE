#!/usr/bin/env bash
# Keep audio-classifier dependencies separate from YuE2's generation environment.
set -euo pipefail
bgm_repo="${1:-$PWD}"
bgm_scripts="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if [[ ! -d "$bgm_repo/src/yue2" ]]; then
  echo "Pass the YuE repository root." >&2
  exit 1
fi
export UV_CACHE_DIR="${UV_CACHE_DIR:-$bgm_repo/.cache/uv}"
if [[ ! -x "$bgm_repo/.venv-bgm-audit/bin/python" ]]; then
  uv venv --python 3.12 "$bgm_repo/.venv-bgm-audit"
fi
uv pip install --python "$bgm_repo/.venv-bgm-audit/bin/python" -r "$bgm_scripts/requirements-audit.txt"
