---
name: comfy-score-music
description: Compose, fix, develop or model-continue native YuE2 ABC scores from an existing ABC file or song generation JSON, create alternatives and matching prompts, and prepare or run the local ComfyUI Music Production Toolkit. Use for score revision and score-driven production rather than audio-cover transcription.
---

# ComfyUI music from a score

Use `/home/mark/repos/comfy` as the local ComfyUI checkout unless the user supplies another location. Read its `AGENTS.md` before modifying files there. The local setup is documented in `LOCAL_SETUP.md`; the installed toolkit is `custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit`.

## Instrumental only

The user’s standing requirement for this skill is **instrumental music only**, including every alternative, regeneration and retake. Exclude all human vocal sounds: sung or spoken words, lead or backing vocals, choir, humming, chants, scat, breathy vocal textures and vocal chops. Do not inherit vocal instructions from source receipts, prompts or templates. A later explicit user request may change this requirement; otherwise do not offer or introduce vocal versions.

Keep Vocal entirely unpitched: chord labels and timed rests only. Put the instrumental foreground melody in Ins and describe instrument roles in Style. Lyrics must contain section tags only. Check these invariants before queueing every take, including recovered scores. Use concise instrumental conditioning and preserve detailed arrangement prose in a sidecar as described below.

Screen every rendered alternative for vocals. Listening is the decisive check; ASR and speech-activity detection are supporting diagnostics and can miss wordless vocals. Do not present a take with detected vocals as a passing instrumental: preserve and label the failed take, correct its conditioning or score, and render a replacement within the authorized generation scope. After two failed replacements for an alternative, retain the diagnostics and report that it remains unresolved rather than retrying indefinitely. If listening is unavailable, disclose that the instrumental requirement has not been fully verified; never infer voice-free audio from a silent Vocal staff alone.

## Always provide three alternatives

For every song generation, regeneration or score-fix request, **produce three alternatives**, even when the user asks for a single named track without specifying a count. Follow a different count only when the user explicitly requests it. For follow-ups such as “two more,” add that many to the existing takes without regenerating or overwriting them. Preparation-only requests get three prepared alternatives; this rule does not authorize rendering when the user only requested preparation.

For rendered alternatives, use distinct seeds and output names, preserve each workflow and receipt, and check every result. Use idle independent GPU workers in parallel when available; queue the remaining takes without interrupting unrelated jobs. Distinguish different performances of one score from different compositions.

## Let YuE2 continue a preserved opening

When the user wants **YuE2 itself to compose the rest** while keeping the opening, read [Model-generated score continuation](references/continue-score.md). Use the builder's `--keep-bars N` or `--keep-seconds S`; add `--score-only` when only score generation is authorized. Do not hand-author, repair or substitute a continuation. The installed `YuE2ContinueABC` node gives the actual opening to YuE2 as an unfinished ABC token prefix, generates the suffix, checks the frozen notes/chords/timing and rejects pitched Vocal notes. It saves every attempt and permits at most three attempts per alternative. Produce three independently seeded alternatives unless another count is requested.

Prefer whole bars. Seconds select the nearest complete bar using the actual ABC tempo/meter; report the selected bars and nominal seconds. This preserves symbolic music, not the original audio performance, and cannot guarantee the eventual render is voice-free. Plain `score_abc` still means a complete score and does not continue it.

## Fix or develop a score from a file

For requests such as “fix this song's score,” “keep the opening but make it go somewhere,” or “make alternatives from this JSON,” read [Revising an existing score](references/revise-score.md). It covers source extraction, musical diagnosis, motif preservation, development, validation and matching generation prompts. An exact-score retake follows the recovery instructions below instead; changing seeds or production does not fix the composition.

## Recover an existing batch track

For a named rendered track, look first under `/home/mark/repos/comfy/output/audio/batches/<batch-name>/log/<track-stem>.json` (use `rg --files /home/mark/repos/comfy/output/audio/batches` to locate it). This production receipt contains the actual `generation.abc`, `generation.yue2` sampling settings, `generation_seed`, duration ceiling, `style`/`caption`, `lyrics`, title and exported paths in `outputs`. The neighboring `.md` is a readable report. Audio usually lives in the batch's `original-flac/`, `highres-44flac/` and `highres-44mp3/` folders. Queue records and prepared jobs live separately under `/home/mark/repos/comfy/batches/<batch-name>/`; use those if the receipt needs corroboration.

For a same-score retake, copy the receipt and extract `generation.abc` exactly before preparing new inputs. An instrumental filename and tag-only Lyrics do not imply a silent Vocal staff. If Vocal contains pitched notes, the instrumental-only requirement takes precedence: preserve important melody in Ins, resolve overlaps deliberately, and replace Vocal notes with timed rests retaining chord onsets. Label this an instrumental score revision, not an exact-score retake, and record the changes. Otherwise preserve the source score exactly. Use a new output name, save the new seed and conditioning, and verify the completed receipt's ABC against the intended score. A standalone retake may use the direct-score builder; this does not replace the existing batch runner.

## Prepare the composition

Preserve the source and write revisions separately. Agree on fixed musical material from the request. Composition alternatives should change phrases, harmony, rhythm or form rather than merely renaming or transposing the same score. For retakes or a focused score repair, use the same corrected score with distinct seeds unless different compositions are requested. Keep the instrumental-only requirement, requested length and ensemble; do not default to cave music.

Use the installed native-dialect checker at `third_party/yue2_abc.py` in the toolkit. Its `parse_abc(text)` validates two monophonic voices, aligned measures, supported chord symbols and note durations. The local notation guide is `docs/references/YUE2_ABC_REFERENCE.md`. Keep the required blank `T:` header; put the title in the request JSON. For instrumentals, Vocal carries chord labels and rests while Ins carries the foreground instrumental melody. Instrument assignments and additional accompaniment belong in Style.

Calculate score duration from the parsed quarter-note duration and tempo; compound-meter Q is still the quarter-note tempo. Inspect the musical arc, not just syntax. Keep the arrangement and section-only instrumental Lyrics aligned with the score. A ceiling leaves space for the ending; it is neither a target duration nor a guarantee of score adherence.

Write `generation-input.json` with `title`, `style`, `lyrics`, `abc`, and `max_duration`. Always explicitly request instrumental music with no human voice, no sung/spoken words, lead/backing vocals, choir or humming. Style should describe instruments, texture and the actual section development. The score replaces the planner; it does not replace the timbre/arrangement description.

## Instrumental conditioning after a rendered failure

Detailed chronological arrangement prose caused the direct-score renders in this project to sing passages from Style despite a silent Vocal staff. For direct instrumental renders, keep the full arrangement notes in a sidecar, and send concise musical descriptors in the native `style` field: instrumental identity, instruments, mood, tempo/meter, tonal areas and production character. Keep native `lyrics` limited to section tags matching the score. Do not send score-supervision sentences such as “follow the supplied ABC” or “the Vocal staff is silent” to the acoustic model. The ABC carries the actual development. Preserve the original score and full harmony mode when testing this repair, and save the exact revised inputs.

Unfiltered Whisper hallucinated generic phrases on the corrected instrumental takes. Treat ASR as a diagnostic: text closely matching the supplied prose is stronger evidence of leakage than generic “thank you” strings. Speech-activity detection can provide a second check, but neither method proves absence of wordless vocals or replaces listening. Report this distinction rather than claiming an automated voice-free guarantee.

## Build and validate

The local toolkit's `MusicGeneration.score_abc` optional input passes a nonempty authored score unchanged to `YuE2GenerateMusic` and skips `YuE2GenerateABC`. This is a local extension to `music_generation.py`; it may need reapplying after a toolkit update. A blank input retains the original automatic-planner behavior. It is supported for the **YuE2** new-song profile, not **YuE2 Cover**. Use **full** mode for authored harmony. The receipt records `abc_source: supplied_score` and does not claim ABC sampling settings were used.

Run the builder from any directory with absolute paths as needed:

```bash
python3 scripts/build_workflow.py /path/generation-input.json \
  --comfy-dir /home/mark/repos/comfy --seed 42001 --name my-score \
  --output /path/my-score-workflow.json
```

Without continuation flags, this creates a frontend workflow and matching `.api.json`, derived from `user/default/workflows/YuE2_Gemma_Music_Production.json`. It preserves that workflow's audio-stage settings, removes LLM/planning/transcription/artwork branches, supplies the score directly, and saves original FLAC, processed FLAC/MP3 and production reports under `output/audio/score-music/`. It does not queue a render or overwrite existing workflow files. The builder depends on that local workflow's node IDs; recheck it if the base workflow changes.

Use the ComfyUI environment for non-rendering validation:

```bash
/home/mark/repos/comfy/.venv/bin/python scripts/validate_workflow.py \
  /path/my-score-workflow.api.json --report /path/workflow-validation.json
```

The validator uses ComfyUI's actual prompt validator and expands the generation node on CPU, checking exact score delivery, full mode and provenance without loading weights or starting a server. Its route registry is only for node imports; no server listens. Also run the skill creator's `quick_validate.py` when editing this skill.

Copy a prepared UI workflow into `comfy/user/default/workflows/` for sidebar discovery, or give the user the JSON to drag into ComfyUI. Keep the API file outside that sidebar folder. The workflow exposes SCORE, ARRANGEMENT, SECTIONS, TITLE, OUTPUT NAME and SEED; keep SECTIONS tag-only. Regenerating from the request JSON keeps source provenance current; direct canvas edits change the actual saved ABC but retain the original request's provenance fields. Full production metadata always contains the score actually sent.

## Existing batch workflow with optional scores

For the user's existing batch process, keep `comfy/local_setup/batch_music.py` and its default full `YuE2_Gemma_Music_Production.json` workflow. Do not substitute the reduced score-only canvas workflow, which lacks the batch's prompt nodes.

- No score flags: preserve the original planner and all workflow choices.
- `prepare ... --score /path/song.abc`: use that score for every selected prompt/copy.
- `prepare ... --score-map /path/scores.json`: map selected library-relative prompt paths to ABC filenames; relative filenames resolve beside the map. Unmapped prompts retain workflow defaults. This flag and `--score` are mutually exclusive.

The script validates and embeds each ABC, saves a score snapshot/hash/duration in the batch, and puts the score into the LLM's arrangement context. Scored jobs use full mode and skip only ABC planning. Unlike the reduced direct-score workflows, this path retains the existing LLM stage and its server requirement, plus the saved artwork/finishing choices. `run`, worker routing, output verification and resume work unchanged and do not reread source score files. A duration warning means the score exceeds the existing generation ceiling; choose a suitable ceiling if a complete performance is needed.

Run batch regression checks after modifying this integration:

```bash
/home/mark/repos/comfy/.venv/bin/python -m unittest discover \
  -s /home/mark/repos/comfy/local_setup -p test_batch_music.py -v
```

## Render only within the requested scope

If the request is scores/workflow preparation, stop after validation and clearly say no audio was rendered. If audio generation is authorized, use the existing local server or `./start-comfy.sh`; the reduced direct-score workflow needs no Gemma/LLM server or artwork model, while the optional-score batch path retains its existing LLM and artwork settings. Check the queue before submission. Use a unique output name and submit the prepared `.api.json` to the local `/prompt` endpoint once; save its returned prompt ID. Monitor `/history/<prompt_id>` and reconcile the queue/history after interruptions before retrying, so a lost HTTP response does not create duplicate takes. Never stop unrelated jobs or download models without the user's authorization.

Confirm successful history and actual exported files. Check duration, clipping, absence of all human vocal sounds, phrase development, transitions and a complete ending. Apply the instrumental-only acceptance rule to every take. Compare original and mastered FLAC; mastering/artifact reduction may help presentation but cannot repair a repetitive composition or guarantee better results. Preserve prompts, score, seed, receipt and validation results, and distinguish symbolic checks from actual audio listening. Enable optional refinement only when requested or supported by a concrete listening issue; YuE2's model default leaves it off.
