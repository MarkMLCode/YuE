# Revising an existing score

Use this workflow for musical or notation changes to an existing score. Infer the intended edit from the request and prior conversation. Preserve a recognizable opening when asked to develop it; “fix” does not imply replacing the entire composition. If the defect is unspecified, inspect the source first and ask a focused question only if materially different interpretations remain.

## Recover the actual source

- An `.abc` file is direct score input. Preserve its original bytes in a source snapshot before editing.
- A ComfyUI production receipt contains `generation.abc`. Older receipts may expose it in `models.abc`; record the field used and investigate disagreements rather than silently choosing between conflicting scores.
- A direct-score `generation-input.json` has top-level `abc`, `style`, `lyrics`, `title` and `max_duration`.
- For a FLAC/MP3 or track name, locate its production receipt using the parent skill's recovery instructions. Audio alone does not contain an editable symbolic score. Without a saved score, explain that transcription is a separate approximation before treating it as the original score.

A workflow JSON is a graph, not necessarily a completed score. Resolve a literal `score_abc` input or its linked primitive string if present. A workflow containing only a score planner needs the completed generation receipt.

Read the associated title, style/caption, lyrics, sampling settings and measured duration. The actual ABC takes precedence when prose describes music the planner did not write. Record the source path, JSON field if applicable, and SHA-256 of the extracted score. Keep the receipt or source snapshot beside the revision.

## Diagnose the music

Use the installed toolkit's native parser and notation reference from the parent skill. Its CLI saves an inspection without loading models:

```bash
python3 /home/mark/repos/comfy/custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit/third_party/yue2_abc.py inspect source.abc --output source-inspection.json
```

Inspect both voices, chord changes, phrase lengths, repeated passages, register, section boundaries, cadence and nominal duration. Distinguish invalid notation from valid but repetitive music. A section comment or a new instrument in Style does not itself develop the written melody or harmony. Do not treat intentional ostinato, drone or meditative repetition as a defect unless it conflicts with the brief.

Identify the material to retain and passages to change. For an opening that needs development, identify the recognizable motif and where its repetition stops serving the form. Compare score duration with source audio: raising the generation ceiling does not lengthen a short score.

## Make the revision

Choose a musical arc appropriate to the brief. One option is to establish the motif, introduce an answering phrase, create harmonic or rhythmic contrast, return to a changed version of the motif, and write an ending. This is not a required section template.

Develop notes and chords where needed: vary phrase endings, rhythm, contour, harmonic tension, register or cadence. Retain enough of the source to make the relationship audible. Requested alternatives should use materially different musical approaches; new seeds, renamed sections or instrument prompts alone are not alternative scores. Use references for broad musical qualities without defaulting to a particular game, mood or ensemble.

Keep the native two-voice monophonic format and blank `T:` header. Put chord symbols in Vocal. Apply the parent skill’s instrumental-only requirement to revisions and retakes. Inspect pitched Vocal notes, preserve important melodic material in Ins where musically appropriate, and replace Vocal notes with timed rests retaining chord onsets. Resolve overlapping foreground lines deliberately rather than creating unsupported polyphony or silently discarding a theme. Record this as an instrumental adaptation when it changes a recovered score; do not label it an exact-score retake.

Budget duration as `quarter_notes * 60 / BPM`; native Q uses quarter-note BPM even in compound meter. Add purposeful phrases when extension is requested rather than copying an unchanged loop or silently changing tempo. Keep the generation ceiling separate from written duration and requested length.

## Validate the intended invariants

Parse every revision and inspect voice alignment, bar durations, supported chords, ties, accidentals, pitch range and the ending. For melody-preserving reharmonization, compare sounding notes, timing, meter and tempo:

```bash
python3 /home/mark/repos/comfy/custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit/third_party/yue2_abc.py inspect score.abc --output score-inspection.json
python3 /home/mark/repos/comfy/custom_nodes/ComfyUI-MiniMax-Music-Production-Toolkit/third_party/yue2_abc.py compare source.abc score.abc --output melody-comparison.json
```

This comparison does not require equal chord symbols; inspect harmony separately. Whole-score equality is not expected for an authorized melodic or structural revision. Check the particular motif or passages promised unchanged and record intentional differences. Parser success proves structural validity, not musical quality or audio adherence.

## Deliver and optionally render

Write the revised `score.abc`, matching `generation-input.json`, and a short explanation of retained material, changed passages, section development and nominal duration. Keep separate directories for requested alternatives and preserve the source. Put detailed arrangement notes in a sidecar; use the parent skill's concise native instrumental-conditioning guidance for the generation prompt. Align tempo, tonal direction and section tags with the final score rather than copying contradictory source prose.

If workflows are requested, use the existing builder and validator. For the established batch path, use the full production workflow with `--score` or `--score-map`, keeping prompt-only operation supported. Batch preparation currently defaults to a 3–4 minute request and six-minute ceiling; choose an explicit `--length` appropriate to a shorter or longer revision. These controls do not rewrite the score.

Render only when the request or prior authorization includes audio generation. Then continue through the parent skill's queue, export and audio checks. Verify the completed receipt contains the revised ABC, not the source or a newly planned replacement. Report symbolic checks separately from assessment of actual audio.
