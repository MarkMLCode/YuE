# Analyze references before writing prompts

Analyze every audio file in `music_previous/<theme>` before choosing prompt styles
and tempos. Use `scripts/analyze_references.py` with the generation/audit environment;
it additionally needs `librosa==0.11.0` (`uv pip install --python .venv/bin/python librosa==0.11.0`).
It reuses the AudioSet AST classifier from the vocal audit.

```bash
.venv/bin/python skills/theme-bgm/scripts/analyze_references.py \
  'music_previous/army battle' \
  --output outputs/army-battle-reference-analysis.json \
  --cache-dir .cache/audio-check-models --offline
```

The folder argument includes all supported audio files recursively. The output
retains hashes, durations, estimated beats and BPM, 30-second tempo estimates,
alternative periodicities, and style-label evidence across overlapping windows.
Keep this file with the run and record which reference informed each prompt.

Style inference defaults to `--device auto`: CUDA GPU 0 when available, otherwise
CPU. Use `--device cuda:1` to select another GPU or `--device cpu` to force CPU.
An explicitly requested unavailable GPU reports an error. Tempo estimation and
audio preprocessing remain on CPU; `--tempo-only` does not load the classifier.
Files are processed sequentially, and each style result records its actual device.

## Interpret evidence and choose targets

- Report tempo as an estimate. Compare full-track and section estimates and retain
  half/double-time alternatives. Competing pulses can also reflect meter or
  subdivision ambiguity; do not automatically multiply an estimate by two.
- AudioSet labels support broad instrumentation and genre descriptions. Their
  scores are uncalibrated. Separate measured evidence from creative additions;
  do not claim exact instruments, detailed moods, or personal listening based on
  a filename or weak classifier score.
- Write a short interpretation for each reference, then adapt it into a full YuE2
  prompt using the local demo catalog: musical style, tempo, instruments, rhythmic
  feel, development and ending. Do not merely concatenate classifier labels.
- Record reference BPM alternatives and the chosen target BPM separately. Preserve
  the reference's general feel unless the user requests a change. When faster
  music is requested, explain the chosen increase and describe the audible pulse,
  articulation and rhythmic density as well as specifying BPM.
- Use this evidence to author original ABC compositions as well as style prompts.
  Follow [prompting.md](prompting.md#scores-and-retry-prompts) to set tempo, musical
  development and a roughly two-minute score length. Supply the score with
  `cot="full"` and empty lyrics. Audio analysis does not condition YuE2 directly
  or transcribe the source melody; no automatic vocal-note removal is involved.

For a trial or an explicit tempo check, use `--tempo-only` on representative new
audio and compare it with the target and saved score tempo. Save the findings as
a separate report. Estimates and detector passes do not establish perceptual
similarity or quality; do not add an automatic similarity gate or extra retries.

Methods: [librosa beat tracking](https://librosa.org/doc/0.11.0/generated/librosa.beat.beat_track.html)
and [AudioSet AST](https://huggingface.co/MIT/ast-finetuned-audioset-10-10-0.4593).
