# Let YuE2 compose after a frozen opening

Use this path for requests such as “keep the first 30 seconds/16 bars, let YuE generate the rest.” Recover the source from `generation.abc` in the production receipt as described in SKILL.md. Preserve the receipt and source ABC. Do not ask an external LLM or an editing agent to compose the new bars, and do not fix failed suffixes by writing notes yourself.

## Prepare a workflow

Use the normal `generation-input.json` fields: `title`, `abc` (the complete source score), concise instrumental `style`, section-tag-only `lyrics`, and `max_duration` (audio ceiling only). The source score must parse in the native dialect; the selected opening must have no pitched Vocal notes. Optional `continuation_sampling` accepts `max_abc_tokens`, `temperature`, `top_p`, `top_k`, `repetition_penalty`, `penalty_window`, and `max_attempts` (1–3). Defaults match native ABC sampling: 8192 new tokens, temperature 0.7, top-p 0.9, top-k 30, repetition penalty 1.005, window 100, three attempts.

From this skill's directory:

```bash
python3 scripts/build_workflow.py /absolute/path/generation-input.json \
  --comfy-dir /home/mark/repos/comfy \
  --keep-bars 16 --score-only --seed 724101 \
  --name quartet-continuation-01 \
  --output /absolute/path/continuation-01.json
```

Repeat with new names, output paths and distinct seeds for the other two alternatives. Space starting seeds by at least three because a rejected attempt retries with seed +1 and then +2. This creates UI and `.api.json` workflows without queueing them. The existing no-flag builder behavior remains unchanged.

`--keep-seconds 30` is an alternative to `--keep-bars 16`. Seconds snap to the nearest complete source-score bar (ties in distance choose the earlier boundary). It uses parsed bar lengths, meter changes and the score's quarter-note tempo, not timestamps or tempo claims in the original Style prose. Report the selected duration. Cuts within a native four-bar group trim both voices together; compressed rests are expanded when necessary. Notes tied across the boundary remain tied and the generated continuation must resolve them consistently. The opening snapshot can therefore intentionally end in a pending tie; validate the completed score, not that unfinished prefix alone.

For `string-quartet-instrumental-02`, the source receipt is:

`/home/mark/repos/comfy/output/audio/batches/instrumental-2026-09-22/log/string-quartet-instrumental-02.json`

Its actual score is 4/4 at 127 BPM: 16 bars preserve **30.236 seconds**. Do not use the 110 BPM mentioned in its original arrangement prose.

## Validate and run

```bash
/home/mark/repos/comfy/.venv/bin/python scripts/validate_workflow.py \
  /absolute/path/continuation-01.api.json --report /absolute/path/validation.json
```

Validation checks the graph and preservation boundary on CPU. It does not sample YuE2 or prove that a future suffix will pass. Copy the UI JSON into `comfy/user/default/workflows/` for sidebar discovery, or drag it onto the canvas. Keep API JSON outside that folder.

The canvas exposes SOURCE SCORE, ARRANGEMENT, SECTIONS, SEED, and the **YuE2 Continue ABC · Preserve Opening** node. Its `keep_unit` and `keep_value` controls select the frozen opening. `max_abc_tokens` is a continuation token ceiling, not a requested song duration. A duration description can guide composition but does not force a length. Queue a score-only workflow to generate ABC without audio. This needs YuE2, not Gemma or an external LLM.

The custom node is installed at:

`/home/mark/repos/comfy/custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit/score_continuation.py`

It is registered in that toolkit's `__init__.py`; a toolkit update may require restoring this local extension. A running ComfyUI process needs a restart after installation to discover the node. Check active queues before restarting; use a separate local worker if necessary. No ComfyUI core/model edits or new weights are required.

## What generation does

The node appends the preserved ABC tokens after the native `ABC_START` prompt marker, leaves the score open, and invokes YuE2's native ABC sampler. Only the model writes the suffix. The node combines it with the unchanged opening; it does not provide the discarded source suffix to the model.

It checks native notation, aligned voices, added complete bars, unchanged opening pitches/onsets/durations/chords/keys/meter/tempo, and an entirely unpitched Vocal staff. Malformed, truncated and pitched-Vocal attempts are retained as rejected, with at most two replacements. If all three fail, the workflow errors with the diagnostic receipt path; retain that unresolved result instead of silently hand-editing it or retrying indefinitely.

Every execution writes a unique folder under `comfy/output/scores/continuations/`, containing:

- `source.abc` and `opening.abc` snapshots.
- `attempt-N.abc` for every sampled result, including rejected results.
- `receipt.json` with prompts, sampling, requested and actual boundary, each seed, hashes, validation and rejection reasons.
- `score.abc` only when a continuation passes.

Keep the prepared workflow alongside the receipt: it identifies the actual checkpoint. The receipt records the successful retry seed separately from the starting seed. Compare the three suffix hashes and musical events to confirm distinct compositions; a different seed alone does not prove a different result. Describe total bars and nominal duration, plus any obvious symbolic limitations. Score validation is not a listening assessment.

## Rendering later

Omitting `--score-only` creates the continuation **plus existing production audio path**. The continued ABC feeds `MusicGeneration.score_abc` in full mode; mastering and exports retain the existing workflow settings. Queue this only when audio generation is authorized. The production receipt contains the actual performed ABC, while the separate continuation receipt contains its preservation and sampling provenance.

To perform a particular already accepted continuation, put its saved `score.abc` into a fresh generation-input JSON and build **without either keep flag**. That preserves the chosen full score instead of composing another suffix.

Frozen score notes do not freeze waveform samples. A full render is a new performance, including its opening. An unpitched Vocal staff also does not guarantee absence of human voice; follow the skill's listening and vocal-screening rules for every rendered take. A score-only request must finish with an explicit statement that no audio was rendered or voice-screened.
