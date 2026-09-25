#!/usr/bin/env bash
set -euo pipefail
skill_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
repo_dir="$(cd -- "$skill_dir/../.." && pwd -P)"
cd "$repo_dir"
if [[ ! -x .venv-music-flamingo/bin/python ]]; then
  uv venv --python 3.12 .venv-music-flamingo
fi
uv pip install --python .venv-music-flamingo/bin/python -r "$skill_dir/scripts/requirements.txt"
.venv-music-flamingo/bin/python - <<'PY'
from huggingface_hub import snapshot_download
from transformers import MusicFlamingoForConditionalGeneration
print(snapshot_download(
    'nvidia/music-flamingo-2601-hf',
    revision='6b5be086d52f65a1e204cb0faf70bf54e2741ecd',
    cache_dir='.cache/music-flamingo',
))
PY
