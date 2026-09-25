#!/usr/bin/env python3
"""Analyze a local recording with Music Flamingo and independent audio measurements."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import subprocess
import time
import traceback

ROOT = Path(__file__).resolve().parents[3]
MODEL = 'nvidia/music-flamingo-2601-hf'
REVISION = '6b5be086d52f65a1e204cb0faf70bf54e2741ecd'
PROMPT = """Analyze the supplied recording based only on its audible content. Give a
clear, detailed musical analysis in Markdown covering:
1. Overall musical style and character.
2. Prominent instruments or sound families and their musical roles. Distinguish
confident identifications from uncertain or synthesized sounds.
3. Mood, intensity and atmosphere, and what musical details create them.
4. Tempo feel, rhythmic patterns, groove and percussion. Treat any BPM or meter
as an estimate; do not invent precise values if the pulse is unclear.
5. Melody, harmony and tonality. Avoid asserting exact keys, chords or notes when
uncertain; this is an analysis, not a score transcription.
6. How the arrangement develops from opening through middle to ending, including
repetition, entrances, transitions and dynamic changes. Use approximate timestamps
only if you can support them from the recording.
7. Audible production and texture: acoustic/electronic character, reverb, layering,
and density. Do not make claims about stereo width from this mono input.
8. Whether there are vocals, intelligible lyrics, choir or vocal-like textures;
distinguish those from instrumental timbres and mark uncertainty.
Be specific to this audio, avoid imagined narrative or unsupported artist identities,
and state important uncertainties. Do not assign a numerical quality score."""


def write_json(path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, allow_nan=False) + '\n')


def decode(path):
    import numpy as np
    info = json.loads(subprocess.check_output([
        'ffprobe', '-v', 'error', '-select_streams', 'a:0',
        '-show_entries', 'stream=sample_rate,channels:format=duration', '-of', 'json', str(path)
    ], text=True))
    if not info.get('streams'):
        raise ValueError('File contains no audio stream')
    duration = float(info['format'].get('duration', 0))
    if duration > 1200:
        raise ValueError('Recording exceeds 20 minutes; select explicit sections to analyze')
    raw = subprocess.check_output([
        'ffmpeg', '-v', 'error', '-i', str(path), '-map', '0:a:0', '-t', '1201',
        '-ac', '1', '-ar', '16000', '-f', 'f32le', '-'
    ])
    y = np.frombuffer(raw, dtype='<f4').copy()
    if len(y) == 0 or not np.isfinite(y).all():
        raise ValueError('Audio is empty or contains non-finite samples')
    if len(y) > 1200 * 16000:
        raise ValueError('Decoded recording exceeds 20 minutes; select explicit sections')
    stream = info['streams'][0]
    return y, {
        'duration_seconds': len(y) / 16000,
        'source_sample_rate_hz': int(stream['sample_rate']),
        'source_channels': int(stream['channels']),
        'analysis_sample_rate_hz': 16000,
        'analysis_channels': 1,
    }


def estimate_tempo(y):
    import librosa
    import numpy as np
    tempo, beats = librosa.beat.beat_track(y=y, sr=16000, hop_length=256, units='time')
    bpm = float(np.asarray(tempo).reshape(-1)[0])
    sections = []
    for start in range(0, len(y), 30 * 16000):
        chunk = y[start:start + 30 * 16000]
        if len(chunk) < 10 * 16000:
            continue
        t, _ = librosa.beat.beat_track(y=chunk, sr=16000, hop_length=256)
        sections.append({'start_seconds': start / 16000,
                         'estimated_bpm': float(np.asarray(t).reshape(-1)[0])})
    return {
        'estimated_bpm': bpm, 'half_time_bpm': bpm / 2, 'double_time_bpm': bpm * 2,
        'beat_times_seconds': beats.tolist(), 'sections': sections,
        'method': 'librosa beat_track; onset strength and default 120 BPM prior',
        'limits': 'Estimated pulse, not verified tempo or meter; half/double-time ambiguity is possible.',
    }


def choose_device(name, torch):
    if name == 'auto':
        if not torch.cuda.is_available():
            return torch.device('cpu')
        index = max(range(torch.cuda.device_count()), key=lambda i: torch.cuda.mem_get_info(i)[0])
        return torch.device(f'cuda:{index}')
    device = torch.device(name)
    if device.type not in {'cpu', 'cuda'}:
        raise ValueError('Use auto, cpu or cuda:N')
    if device.type == 'cuda':
        if not torch.cuda.is_available() or (device.index or 0) >= torch.cuda.device_count():
            raise ValueError(f'Requested device {device} is unavailable')
    return device


def run(args):
    import torch
    from huggingface_hub import snapshot_download
    from transformers import AutoProcessor, MusicFlamingoForConditionalGeneration
    started = time.monotonic()
    source = args.audio.expanduser().resolve(strict=True)
    y, measured = decode(source)
    print(f'Analyzing all {measured["duration_seconds"]:.2f} seconds', flush=True)
    prompt = PROMPT + ('\n\nAdditional user question:\n' + args.question if args.question else '')
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    record = {
        'status': 'running', 'source_path': str(source), 'source_sha256': digest,
        'measured': measured, 'model_id': MODEL, 'model_revision': REVISION,
        'prompt': prompt, 'versions': {p: importlib.metadata.version(p) for p in
                                    ['torch', 'transformers', 'accelerate', 'librosa', 'soundfile']},
    }
    write_json(args.output / 'analysis.json', record)
    print('Estimating rhythm on CPU', flush=True)
    record['tempo_estimate'] = estimate_tempo(y)
    write_json(args.output / 'analysis.json', record)
    device = choose_device(args.device, torch)
    dtype = torch.bfloat16 if device.type == 'cuda' else torch.float32
    snapshot = snapshot_download(MODEL, revision=REVISION, cache_dir=str(ROOT / '.cache/music-flamingo'),
                                 local_files_only=True)
    print(f'Loading Music Flamingo on {device}', flush=True)
    processor = AutoProcessor.from_pretrained(snapshot, local_files_only=True)
    model = MusicFlamingoForConditionalGeneration.from_pretrained(
        snapshot, local_files_only=True, dtype=dtype, device_map=str(device),
        attn_implementation='sdpa',
    ).eval()
    messages = [{'role': 'user', 'content': [
        {'type': 'text', 'text': prompt}, {'type': 'audio', 'audio': y}
    ]}]
    # Supplying the decoded array keeps filenames and metadata out of the model prompt.
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    inputs = processor(text=[text], audio=[y], sampling_rate=16000, return_tensors='pt').to(device)
    inputs['input_features'] = inputs['input_features'].to(dtype)
    print('Generating musical analysis', flush=True)
    with torch.inference_mode():
        output = model.generate(**inputs, max_new_tokens=args.max_new_tokens,
                                do_sample=False, use_cache=True)
    tokens = output[0, inputs['input_ids'].shape[1]:]
    response = processor.decode(tokens, skip_special_tokens=True).strip()
    if not response:
        raise RuntimeError('Music Flamingo returned an empty response')
    eos = model.generation_config.eos_token_id
    eos = eos if isinstance(eos, list) else [eos]
    truncated = len(tokens) >= args.max_new_tokens and int(tokens[-1]) not in eos
    record.update(status='complete', model_response=response, device=str(device),
                  dtype=str(dtype), generated_tokens=len(tokens), truncated=truncated,
                  generation={'do_sample': False, 'max_new_tokens': args.max_new_tokens},
                  elapsed_seconds=round(time.monotonic() - started, 2))
    write_json(args.output / 'analysis.json', record)
    (args.output / 'model-response.md').write_text(response + '\n')
    bpm = record['tempo_estimate']['estimated_bpm']
    report = (f'# Song analysis: {source.stem}\n\n'
              f'Local Music Flamingo interpretation of the complete recording. '
              f'Instrumentation, tonality and structural descriptions are model estimates. '
              f'The model response is retained verbatim and may contain unsupported claims; '
              f'mono input cannot establish stereo imaging.\n\n'
              f'## File measurements\n\n'
              f'- Duration: {measured["duration_seconds"]:.2f} seconds\n'
              f'- Source: {measured["source_sample_rate_hz"]} Hz, {measured["source_channels"]} channels\n'
              f'- Model input: mono, 16000 Hz\n\n'
              f'## Independent rhythm estimate\n\n'
              f'Estimated pulse: **{bpm:.1f} BPM**; half/double-time alternatives '
              f'{bpm/2:.1f}/{bpm*2:.1f} BPM. This is not a verified musical tempo.\n\n'
              f'## Music Flamingo interpretation\n\n{response}\n\n'
              f'## Provenance\n\nModel: `{MODEL}`\n\nRevision: `{REVISION}`\n\n'
              f'Source SHA-256: `{digest}`\n\n'
              f'Full prompt, per-section tempo estimates and runtime details: [analysis.json](analysis.json)\n')
    if truncated:
        report += '\n**Incomplete response:** generation reached the token limit.\n'
    (args.output / 'analysis.md').write_text(report)
    print(f'Saved {args.output / "analysis.md"}', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('audio', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--device', default='auto')
    parser.add_argument('--question')
    parser.add_argument('--max-new-tokens', type=int, default=1800)
    args = parser.parse_args()
    if not args.audio.is_file():
        parser.error('Audio file does not exist')
    if args.max_new_tokens < 1:
        parser.error('--max-new-tokens must be positive')
    if args.output.exists():
        parser.error('Choose a fresh output directory; existing reports are preserved')
    args.output.mkdir(parents=True)
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TOKENIZERS_PARALLELISM', 'false')
    try:
        run(args)
    except Exception:
        (args.output / 'error.txt').write_text(traceback.format_exc())
        path = args.output / 'analysis.json'
        if path.exists():
            record = json.loads(path.read_text())
            record['status'] = 'failed'
            write_json(path, record)
        raise


if __name__ == '__main__':
    main()
