#!/usr/bin/env python3
"""Estimate tempo and AudioSet style evidence from complete reference recordings."""
import argparse
import importlib.metadata
from pathlib import Path

import librosa
import numpy as np
import soundfile as sf
from scipy.signal import find_peaks, resample_poly

from common import digest, write

AUDIO_SUFFIXES = {'.wav', '.flac', '.mp3', '.ogg', '.m4a'}


def style_device(requested):
    import torch
    if requested == 'auto':
        return torch.device('cuda:0' if torch.cuda.is_available() else 'cpu')
    device = torch.device(requested)
    if device.type not in {'cpu', 'cuda'}:
        raise ValueError('Style device must be auto, cpu, cuda, or cuda:N')
    if device.type == 'cuda':
        if not torch.cuda.is_available():
            raise ValueError('CUDA was requested but is unavailable; use --device cpu')
        if device.index is not None and device.index >= torch.cuda.device_count():
            raise ValueError(f'CUDA device {device.index} is unavailable')
    return device


def audio_paths(inputs):
    paths = set()
    for path in inputs:
        if path.is_dir():
            paths.update(p.resolve() for p in path.rglob('*')
                         if p.is_file() and p.suffix.lower() in AUDIO_SUFFIXES)
        elif path.is_file():
            paths.add(path.resolve())
        else:
            raise FileNotFoundError(path)
    if not paths:
        raise ValueError('No reference audio found')
    return sorted(paths)


def tempo_analysis(mono, sr):
    target_sr, hop = 22050, 256
    y = resample_poly(mono, target_sr, sr).astype(np.float32)
    onset = librosa.onset.onset_strength(y=y, sr=target_sr, hop_length=hop)
    tempo, beats = librosa.beat.beat_track(onset_envelope=onset, sr=target_sr,
                                          hop_length=hop, units='time')
    bpm = float(np.asarray(tempo).reshape(-1)[0])
    # Report alternative periodicities without choosing a faster octave for the user.
    ac = librosa.autocorrelate(onset - onset.mean(), max_size=int(4 * target_sr / hop))
    peaks, _ = find_peaks(ac)
    candidates = [(60 * target_sr / (hop * lag), float(ac[lag] / ac[0]))
                  for lag in peaks if lag > 0 and ac[0] > 0
                  and 40 <= 60 * target_sr / (hop * lag) <= 240 and ac[lag] > 0]
    candidates.sort(key=lambda x: x[1], reverse=True)
    segments = []
    for start in range(0, len(y), 30 * target_sr):
        chunk = y[start:start + 30 * target_sr]
        if len(chunk) < 10 * target_sr:
            continue
        value, _ = librosa.beat.beat_track(y=chunk, sr=target_sr, hop_length=hop)
        segments.append({'start_seconds': start / target_sr,
                         'bpm': float(np.asarray(value).reshape(-1)[0])})
    return {'estimated_bpm': bpm, 'half_time_bpm': bpm / 2, 'double_time_bpm': bpm * 2,
            'beat_times_seconds': np.asarray(beats).tolist(), 'segments': segments,
            'autocorrelation_candidates': [{'bpm': b, 'strength': s} for b, s in candidates[:8]],
            'method': 'librosa onset-strength dynamic-programming beat tracker; default 120 BPM prior',
            'limits': 'Estimated pulse, not verified meter or musical beat level. Half/double-time ambiguity and tempo changes are possible.'}


def style_analysis(mono, sr, classifier_bundle):
    import torch
    from audit import window_starts
    model_path, extractor, classifier = classifier_bundle
    device = next(classifier.parameters()).device
    y = resample_poly(mono, 16000, sr).astype(np.float32)
    predictions, windows = [], []
    labels = classifier.config.id2label
    for start in window_starts(len(y), 160000, 80000):
        features = extractor(y[start:start + 160000], sampling_rate=16000, return_tensors='pt')
        features = {name: value.to(device) for name, value in features.items()}
        with torch.inference_mode():
            scores = classifier(**features).logits.sigmoid()[0].cpu().numpy()
        predictions.append(scores)
        top = np.argsort(scores)[-10:][::-1]
        windows.append({'start_seconds': start / 16000,
                        'top_labels': {labels[int(i)]: float(scores[i]) for i in top}})
    scores = np.stack(predictions)
    mean = scores.mean(axis=0)
    order = np.argsort(mean)[-30:][::-1]
    return {'model': model_path, 'device': str(device),
            'top_mean_labels': {labels[int(i)]: float(mean[i]) for i in order},
            'label_maxima': {labels[int(i)]: float(scores[:, i].max()) for i in order},
            'windows': windows,
            'limits': 'AudioSet labels are uncalibrated evidence for instrumentation/genre, not a definitive style description or personal listening.'}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('audio', nargs='+', type=Path, help='Audio files or folders (searched recursively)')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--tempo-only', action='store_true')
    p.add_argument('--device', default='auto',
                   help='Style inference device: auto (CUDA when available), cpu, cuda, or cuda:N. Tempo remains on CPU.')
    p.add_argument('--ast-model', default='MIT/ast-finetuned-audioset-10-10-0.4593')
    p.add_argument('--ast-revision')
    p.add_argument('--cache-dir')
    p.add_argument('--offline', action='store_true')
    args = p.parse_args()
    if args.output.exists():
        p.error('Choose a fresh output file')
    paths = audio_paths(args.audio)
    bundle = None
    if not args.tempo_only:
        from audit import load_classifier
        try:
            device = style_device(args.device)
        except (ValueError, RuntimeError) as exc:
            p.error(str(exc))
        bundle = load_classifier(args.ast_model, args.ast_revision, args.cache_dir, args.offline)
        bundle[2].to(device)
        print(f'Style analysis device: {next(bundle[2].parameters()).device}; tempo analysis: CPU', flush=True)
    tracks = []
    for path in paths:
        x, sr = sf.read(path, dtype='float32', always_2d=True)
        if not len(x) or not np.isfinite(x).all():
            raise ValueError(f'Empty or non-finite audio: {path}')
        mono = x.mean(axis=1)
        track = {'path': str(path.resolve()), 'sha256': digest(path),
                 'seconds': len(x) / sr, 'sample_rate': sr, 'channels': x.shape[1],
                 'rms': float(np.sqrt(np.mean(x*x))), 'tempo': tempo_analysis(mono, sr)}
        if bundle:
            track['style_evidence'] = style_analysis(mono, sr, bundle)
        tracks.append(track)
        print(f'{path.name}: {track["tempo"]["estimated_bpm"]:.1f} BPM', flush=True)
    write(args.output, {'tracks': tracks,
          'versions': {name: importlib.metadata.version(name) for name in
                       ('librosa', 'numpy', 'scipy', 'soundfile')},
          'purpose': 'Reference evidence for prompts; do not infer style from filenames alone.'})


if __name__ == '__main__':
    main()
