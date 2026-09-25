---
name: theme-bgm
description: Generate instrumental BGM from music_previous theme references using three detailed prompts and original authored scores around two minutes; screen duration and vocals and export every passing WAV.
---

# Theme BGM

Create new instrumental music for the exact requested `music_previous/<theme>`
folder. Deliver **every passing track** to `music/<theme>/` as WAV. The user chooses
favorites afterward; their listening review never blocks completion.
Name WAVs after the prompt title and take number, e.g. `crossfire-01.wav`.
Do not repeat the theme or run name in WAV filenames. Use distinct titles;
existing files are never overwritten.
Also save **every generated track**, including short or vocal-flagged takes, as
WAV in `outputs/bgm/<theme-run>/all/`, with the same title/take naming. This archive
does not change which tracks qualify for `music/<theme>/`.

## Prepare

1. Read the checkout's `skills/yue2-music/SKILL.md` for model setup and generation.
   Use its public staged API and ABC helpers. This workflow uses **AudioSet AST,
   no Whisper/ASR**, for vocal screening.
2. Analyze every reference recording's tempo and broad style evidence using
   [reference-analysis.md](references/reference-analysis.md). Save estimates,
   ambiguities and the chosen tempo/style adaptation for each reference. Follow
   [prompting.md](references/prompting.md) to search the bundled demo catalog offline
   and adapt relevant YuE2 demo styles into
   **three distinct prompts**. Save each prompt's short intended-style `summary`
   and `difference` from the other two for the final report.
3. Author an original finite ABC score for each prompt, informed by the reference
   analysis. Choose tempo and rhythmic feel from the references, with creative
   latitude over harmony, melody, instrumentation and development. Target roughly
   120 seconds using score tempo and bar count; validate duration and silent vocal
   notation. Supply each score via `abc_file` with `cot="full"` and empty lyrics.
   This is the default: YuE2 renders the supplied score. Let YuE2 compose its own
   score only when the user requests that workflow. See
   [prompting.md](references/prompting.md#scores-and-retry-prompts).
4. Use [workflow.md](references/workflow.md) to prepare and run the batch. Reuse
   the scripts; do not write custom orchestration or per-track reviews.

## Fixed batch rules

- Generate **four candidates** for prompt 1 and finish the entire quartet.
- Accept valid, untruncated music lasting **at least 75 seconds** with **no
  AudioSet vocal flags**. Reject shorter tracks; do not pad or stretch them.
  Compose for about two minutes; 75 seconds is the acceptance floor, not the target.
  Keep ABC checks: no sung words (empty lyrics or empty section tags), rests in
  `Vocal`, melody in `Ins`.
- If at least one passes, advance to the next prompt. If none pass, generate one
  more quartet with fresh seeds, using the supplied retry prompt/score if present.
- After **eight attempts maximum per prompt**, advance even if none pass.
- Repeat for all **three prompt groups**: 12–24 attempts total. Export **all** passes
  after the three groups finish, even if fewer than three tracks pass. For example,
  2 + 4 + 1 passes produce **seven WAVs**.
- Do not rank tracks, require quality ratings, request manual acceptance, or select
  a best three. Reject corrupt, silent or truncated results; report clipping as a
  warning for the user's later review. Infrastructure failures pause the command
  instead of triggering a run of wasted attempts.

`run` handles generation, screening, retry decisions, conversion and export.
Use both GPUs by default: one persistent, isolated YuE2 worker per available GPU,
one track per worker. Each free worker takes the next queued track in the quartet
while CPU vocal screening runs separately. Finish the quartet's screening before
choosing a retry or moving to the next prompt. See the workflow for GPU selection.
Keep the saved prompts, scores, seeds, audits and failures in the output run.
The classifier checks overlapping windows through the ending; a clear screen
means no detected vocals, not a guarantee. Do not claim direct listening.

## Finish

Once the passing WAVs, `all/` archive and selection receipt are saved, the skill is done. Return the
script's `final-results.md`: intended style and distinction per prompt group,
filenames, durations, vocal-screen results, any recorded warnings and pass counts.
Use these saved facts directly; do not perform another analysis or invent a
quality score. Link the output folder/report. An optional `listen.py` page is for
the user's later listening and is never a delivery gate.
