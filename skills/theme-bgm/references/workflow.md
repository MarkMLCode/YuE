# Run the workflow

Run from the YuE checkout with its generation environment ready. Use a fresh,
lowercase run-folder name each time. Leave `music_previous` intact.

## 1. Write prompts

First follow [reference-analysis.md](reference-analysis.md) to analyze every source
recording. Save the analysis and a reference-to-prompt mapping with the run.
Then author one original two-minute ABC score for each direction as described in
[prompting.md](prompting.md#scores-and-retry-prompts). Validate each score's structure,
nominal duration, vocal rests and instrumental melody before generation. Save the
scores beside the prompts JSON and reference them with `abc_file` as shown below.

Save a JSON array of exactly three objects to `outputs/theme-prompts.json`:

```json
[
  {
    "title": "Departure march",
    "abc_file": "departure-march.abc",
    "summary": "Determined orchestral hip-hop led by low strings.",
    "difference": "The most rhythmic and forceful of the three directions.",
    "style": "Purely instrumental adventure BGM: low strings, brass answers, bass and a steady hip-hop beat at 96 BPM. Aim for two minutes with an intro, developed motif, contrast, reprise and instrument-led cadence. No singing, speech, choir, humming or vocal samples.",
    "seed": 1000
  },
  {
    "title": "Open horizons",
    "abc_file": "open-horizons.abc",
    "summary": "Expansive orchestral-pop exploration with soaring strings and piano.",
    "difference": "Broader and more flowing than the march or the small travel ensemble.",
    "style": "Purely instrumental exploration BGM: lyrical strings and piano over orchestral-pop drums at 108 BPM. Aim for two minutes of evolving themes, a quieter contrast and a broad instrumental reprise. Piano and strings carry the complete ending. No singing, speech, choir, humming or vocal samples.",
    "seed": 2000
  },
  {
    "title": "Traveling companions",
    "abc_file": "traveling-companions.abc",
    "summary": "Light chamber-folk travel music with flute, mandolin and pizzicato strings.",
    "difference": "The smallest ensemble and gentlest pulse, with playful articulated melodies.",
    "style": "Purely instrumental traveling-party BGM: flute and mandolin trade themes over pizzicato strings and gentle frame drum at 96 BPM. Aim for two minutes with introduction, developed theme, contrast, varied reprise and a plucked instrumental cadence. No singing, speech, choir, humming or vocal samples.",
    "seed": 3000
  }
]
```

Adapt this example to the theme using [prompting.md](prompting.md). Required fields:
`style`, `summary`, `difference`. Include `abc_file` for the default authored-score
workflow; omitting it asks YuE2 to compose its own plan, which is reserved for an
explicit user request. Optional: `title`, `seed`, `demo_case_ids`,
`retry_style`, `retry_abc_file`, `lyrics` (empty section tags only).
Omitting `lyrics` keeps the field empty. ABC paths are relative to the prompts
JSON. Scores are validated and copied into the batch; original files stay intact.
Write retry prompts in advance if useful, staying within each group's description.

## 2. Prepare and run

```bash
.venv/bin/python skills/theme-bgm/scripts/bgm.py prepare \
  --theme 'adventure begins' --prompts outputs/theme-prompts.json \
  --output outputs/bgm/adventure-begins-01

.venv/bin/python skills/theme-bgm/scripts/bgm.py run \
  --run outputs/bgm/adventure-begins-01
```

`run` generates four per prompt, screens each eligible track with AudioSet, retries
four only when the first quartet has zero passes, then advances. After three groups
it converts every passing native FLAC to **24-bit PCM WAV**, preserving samples,
sample rate and duration, and saves them in `music/<exact theme>/`. There is no
ranking, minimum total pass count, or manual acceptance step.
The minimum duration is saved in `batch.json` during preparation. New batches
default to 75 seconds; use `prepare --min-seconds N` for a user-requested minimum.
Generation, screening, status and export use that batch's value. Older batches
retain their saved threshold, including 90-second runs.
It also saves every generated track as WAV to `<run>/all/`, including rejected
tracks. Attempts that failed before producing audio have no WAV to archive.

By default, `run` uses all visible CUDA GPUs with at least 24 GiB initially free.
On the two-GPU machine, each GPU gets its own persistent worker process and YuE2
pipeline. Workers take the next queued track as soon as they finish; no GPU runs
two tracks at once. Separate processes isolate random seeds and CUDA state.
The runtime retains its normal model offloading during decoding; each worker
reuses its pipeline across tracks rather than reopening the model files each time.
AudioSet screening runs one track at a time on CPU, overlapping GPU generation.
All four tracks must finish screening before retrying or changing prompt groups.

To select GPUs explicitly, add `--devices cuda:0 cuda:1`. Use `--device cuda:0`
for one GPU, or `--device cpu` for an explicit CPU run. `--min-free-gib` adjusts
the initial memory check. Auto mode skips GPUs below that limit; explicit GPU
selection reports insufficient memory. Do not stop unrelated services. Memory
availability is checked at startup, not reserved against other applications.

Short tracks are rejected before vocal screening. For separate audit dependencies, run:

```bash
bash skills/theme-bgm/scripts/setup_audit.sh "$PWD"
.venv/bin/python skills/theme-bgm/scripts/bgm.py run \
  --run outputs/bgm/adventure-begins-01 \
  --audit-python .venv-bgm-audit/bin/python
```

The separate environment starts one audit process per eligible track. Install no
Whisper/ASR. Optional model flags: `--model`, `--vae`, `--revision`,
`--vae-revision`, `--offline`. Audit flags: `--ast-model`, `--ast-revision`,
`--cache-dir`. Use cached models with `--offline`; check available GPU memory
without stopping unrelated services.

## 3. Read the result

- `music/<theme>/*.wav`: every passing track, named `<title>-<take>.wav`, e.g.
  `crossfire-01.wav` or `war-drums-05.wav`. Titles become lowercase filename-safe
  slugs; take numbers retain the original attempt number. Use distinct titles
  that do not collide with existing music; WAV names omit the theme/run name.
- `music/<theme>/selection-<run>.json`: provenance, measurements and prompt summaries.
- `<run>/final-results.md`: automatic brief report with intended styles and their
  differences, filenames, durations, screen results, warnings and per-group counts.
- `<run>/candidates/`: every request, ABC plan, native result, audit and decision.
- `<run>/all/`: all generated audio as title/take-named WAVs, regardless of duration
  or vocal flags. `index.json` records each track's outcome, issues and source.

Return the report directly. Style notes describe the intended prompt; detector
scores are not music quality ratings. The user's listening/selection happens
**after delivery** and does not block this skill.

Rerun the same `run` command after interruption: completed candidates stay saved;
a saved native result resumes at screening. An interrupted generation without a
complete result counts as a failed attempt. Completed takes are preserved even
when workers finish out of order. Audit/setup errors stop new dispatches;
already-running work finishes and stays available for resumption. Only one
runner may control a batch at a time.
Completed exports are verified and reused; existing music is never overwritten.
Use `bgm.py status --run <run>` for counts or `bgm.py export --run <run>` to retry
only the final export. Older batch formats remain untouched; prepare a new run
for these rules. Optional: `listen.py --run <run>` builds a local player.
Use `bgm.py archive --run <run>` to create or backfill `all/` from saved audio,
including a partially completed run, without generation or another audio audit.
