# Write three instrumental prompts

Start with [reference analysis](reference-analysis.md) for every recording in the
requested `music_previous/<theme>` folder, including any supplied old prompts.
Use estimated tempo and broad style evidence to guide the three directions;
record which reference informed each prompt and explain any requested tempo change.
Use the bundled [demo catalog](demo-catalog.json) as a style reference. It contains
all examples from the [YuE2 demo site](https://map-yue2.github.io/), including their
original fields and links. Search it locally; use the actual `tags` (Style prompt)
and save selected case IDs with each run. Normal searches make no network requests:

```bash
.venv/bin/python skills/theme-bgm/scripts/demo_prompts.py \
  --query 'orchestral cinematic hip hop' --output outputs/theme-demo-prompts.json
```

Refresh the complete catalog only when an update is wanted:

```bash
.venv/bin/python skills/theme-bgm/scripts/demo_prompts.py --refresh
```

The catalog records its source, download time, and source SHA-256. Refresh parses
the site's data as JSON without executing JavaScript and replaces the catalog only
after successful validation. If refresh fails, continue using the existing catalog.
Audio and score links are retained; their media files are not downloaded.
`--data-file path/to/cases.js` remains available for another offline snapshot.
Run-specific `demo-prompts.json` files record selected references and catalog
provenance; they are not a second download. Do not invent examples.

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

Keep `lyrics` empty for the default authored-score workflow; its form is already
in the ABC. If the user requests a workflow using lyric structure, only empty
section tags are allowed, for example
`[Verse]\n\n[Pre-Chorus]\n\n[Chorus]\n\n[Bridge]\n\n[Chorus]\n\n[Outro]`.
The runner preserves these tags and rejects sung words. A duration in the prompt
is a target, not a hard model constraint. The script measures actual audio and
rejects anything under the batch's saved minimum (75 seconds by default). Avoid vocal-coded textures such as choral pads
and wordless voices; name the instruments that should play sustained passages.

For example, an adventure theme could use a low-string hip-hop march, expansive
orchestral-pop exploration, and light woodwind/pizzicato travel music. Choose
styles that fit the actual theme instead of reusing this trio everywhere.

## Scores and retry prompts

- By default, author a new finite ABC score for each prompt and pass it through
  `abc_file` with `cot="full"`. YuE2 renders this supplied composition rather than
  generating a new score. Read the underlying skill's `references/abc-editing.md`
  before authoring notation. Use model-generated planning only when requested.
- Take inspiration from each reference's tempo, rhythmic character and broad
  instrumentation. Preserve faster motion when supported by the reference; do
  not impose a slow theme-wide default. Resolve uncertain beat levels explicitly.
  Creative liberties are welcome when they improve the composition: explain
  material departures, and distinguish authored choices from detected facts.
- Write original motifs, harmonic movement, development, contrast, reprise and
  a deliberate instrumental ending. Do not claim a transcription or copy source
  melodies. Vary phrases and orchestration rather than merely repeating one bar.
- Target roughly 120 seconds by calculating the score length. With a quarter-note
  tempo, `seconds = bars × quarter_notes_per_bar × 60 / BPM`; in 4/4 the beat count
  is 4, and in 6/8 it is 3. For example, 60 bars at 120 BPM, 48 bars at 96 BPM,
  and 64 bars at 128 BPM each last 120 seconds in 4/4. Round to sensible phrase
  lengths near the target and validate `nominal_duration_seconds` with the ABC
  helper. Actual audio can run longer or shorter; report its measured duration
  without cropping, padding or time stretching to manufacture a two-minute file.
- Put the tune in `Ins`. Keep `Vocal` as rests, with chord symbols in that voice
  as required by native notation. Use `L:1/32` for newly authored scores.
- Match tempo, meter, structure and score length to the style prompt. When changing
  the ABC unit length, scale note/rest lengths to preserve musical timing.
- Supply an optional `retry_style` and/or `retry_abc_file` upfront for the second
  quartet. Keep the group's musical identity: clarify instrument-led phrases and
  ending, simplify vocal-like textures, or expand an undersized score with real
  musical development. If omitted, retries use the original prompt with new seeds.
- Keep retries within the same eight-attempt group. Never add an open-ended prompt
  revision loop, stretch/pad audio, or relax the batch's duration/vocal checks.

Silent vocal notation does not prevent YuE2 from producing voices in audio.
AudioSet screening remains required. No Whisper, transcription, or subjective
quality scoring belongs in this workflow.
