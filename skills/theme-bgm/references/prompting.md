# Write three instrumental prompts

Inspect the requested theme in `music_previous`, including supplied old prompts.
Use the [YuE2 demo site](https://map-yue2.github.io/) as a style reference. Retrieve
relevant examples once per theme; use their actual `tags` (Style prompt) and save
case IDs. The helper parses the site's data as JSON without executing JavaScript:

```bash
.venv/bin/python skills/theme-bgm/scripts/demo_prompts.py \
  --query 'orchestral cinematic hip hop' --output outputs/theme-demo-prompts.json
```

Use `--data-file path/to/cases.js` for an offline snapshot. If fetching fails,
inspect the site or use a saved snapshot; do not invent examples.

## Prompt recipe

Write three compact musical directions. Vary the lead instrument, groove and
energy while keeping the same scene/theme. Transfer genre, instrumentation,
rhythm and development from suitable demos; omit singers, language and lyrics.

> Purely instrumental [genre] BGM for [theme]. [Lead and melodic character] over
> [supporting instruments], [groove/meter] at [tempo]. [Mood and energy]. Aim for
> about two minutes: intro, developed theme, contrasting passage, reprise and
> instrumental cadence with natural decay. Instruments carry every phrase and
> the entire ending. No singing, speech, choir, humming or vocal samples.

Save `summary` (one sentence describing the intended style) and `difference`
(one sentence explaining its contrast with the other prompts). Write these now;
the final report copies them without further analysis. They describe intent,
not a verified account of how the audio sounds.

Keep `lyrics` empty; the script sets it automatically. A duration in the prompt
is a target, not a hard model constraint. The script measures actual audio and
rejects anything under 90 seconds. Avoid vocal-coded textures such as choral pads
and wordless voices; name the instruments that should play sustained passages.

For example, an adventure theme could use a low-string hip-hop march, expansive
orchestral-pop exploration, and light woodwind/pizzicato travel music. Choose
styles that fit the actual theme instead of reusing this trio everywhere.

## Scores and retry prompts

- Prefer a finite ABC score targeting roughly 120 seconds. Read the underlying
  skill's `references/abc-editing.md` when authoring or changing notation.
- Put the tune in `Ins`. Keep `Vocal` as rests, with chord symbols in that voice
  as required by native notation. Use `L:1/32` for newly authored scores.
- Match tempo, meter, structure and score length to the style prompt. When changing
  the ABC unit length, scale note/rest lengths to preserve musical timing.
- Supply an optional `retry_style` and/or `retry_abc_file` upfront for the second
  quartet. Keep the group's musical identity: clarify instrument-led phrases and
  ending, simplify vocal-like textures, or expand an undersized score with real
  musical development. If omitted, retries use the original prompt with new seeds.
- Keep retries within the same eight-attempt group. Never add an open-ended prompt
  revision loop, stretch/pad audio, or relax the 90-second/vocal checks.

Silent vocal notation does not prevent YuE2 from producing voices in audio.
AudioSet screening remains required. No Whisper, transcription, or subjective
quality scoring belongs in this workflow.
