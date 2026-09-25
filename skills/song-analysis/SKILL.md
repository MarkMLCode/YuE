---
name: song-analysis
description: Analyze a local song or instrumental recording with Music Flamingo and audio measurements. Use for instrumentation, mood, arrangement, production, vocal presence, and reference-song descriptions; use SheetSage2 separately for editable score transcription.
---

# Song analysis

Analyze the actual recording with the local Music Flamingo installation. Resolve this
skill's symlink to find the repository root two directories above it. The installed
runtime is `/home/mark/repos/YuE/.venv-music-flamingo/bin/python`; keep it separate
from YuE because their Transformers versions differ.

## Run

Locate the user's audio, searching `music_previous` with ignored files included when
necessary. Quote paths with spaces. Use a fresh output directory:

```bash
cd /home/mark/repos/YuE
.venv-music-flamingo/bin/python skills/song-analysis/scripts/analyze.py \
  'music_previous/ancient temple/Dark Dungeon.wav' \
  --output outputs/song-analysis/dark-dungeon --device cuda:0
```

The runner defaults to cached weights and does not upload audio. It selects a GPU
with the most free memory when `--device auto` is used. Do not stop other workloads
to free memory. `--device cpu` is available but slow. For a specific question, add
`--question 'Describe the percussion and how it changes through the track.'`.

Read `analysis.md` and `analysis.json`, and return a useful musical analysis with a
link to the report. Cover the sound, prominent instrumental roles, mood, rhythm,
development, production and vocal presence as supported by the results. Exact
instrument names, keys, chords and section timestamps from Music Flamingo are
estimates. Resolve disagreement with the tempo estimator explicitly; its pulse
can be half/double the musical beat. Never infer the music from its filename or
claim personal listening from a model response. Keep the raw response intact; add
review notes when it makes unsupported claims or conflicts with other evidence.
A model saying no vocals is not a dedicated vocal-screening pass.

The report preserves measured file properties, estimated tempo, the complete model
response, prompt, source hash, model revision and runtime versions. A failed run
leaves `error.txt`; do not present it as a completed analysis. Token-limit truncation
is flagged. The runner rejects recordings over the model's 20-minute context limit
instead of silently analyzing only the opening; for longer files, analyze explicit
sections and state their coverage. The model receives mono 16 kHz audio, so do not
treat its comments about stereo imaging as measured evidence.

If the user requests a generation prompt, derive it from the analysis and label
creative additions. This skill itself does not generate music or transcribe a score.

## Installation and recovery

The installed model is `nvidia/music-flamingo-2601-hf` at revision
`6b5be086d52f65a1e204cb0faf70bf54e2741ecd`, cached in `.cache/music-flamingo`.
For a fresh installation, run `bash skills/song-analysis/scripts/install.sh` from
the repository root. The installer creates its own environment and downloads
approximately 16.5 GB of weights; existing YuE packages are untouched.

Model terms: [NVIDIA model card](https://huggingface.co/nvidia/music-flamingo-2601-hf)
specifies noncommercial research use. The runner and the skill do not alter those terms.
