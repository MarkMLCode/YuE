#!/usr/bin/env python3
"""Full-track AudioSet vocal screening; never claims human audition."""
import argparse
import importlib.metadata
import importlib.util
from functools import lru_cache
from pathlib import Path

from common import digest, write

VOCAL_LIMITS = {"Speech": .05, "Singing": .03, "Choir": .01, "Humming": .01,
                "Chant": .01, "Rapping": .03, "Whispering": .01,
                "Male singing": .01, "Female singing": .01, "Child singing": .01,
                "Synthetic singing": .01, "Vocal music": .01, "A capella": .01}


def window_starts(samples, size, hop):
    starts = list(range(0, max(samples - size + 1, 1), hop))
    last = max(0, samples - size)
    return starts if starts[-1] == last else starts + [last]


def snapshot(name, revision, cache, offline, patterns):
    from huggingface_hub import snapshot_download
    if Path(name).is_dir():
        return str(Path(name).resolve())
    return snapshot_download(name, revision=revision, cache_dir=cache,
                             local_files_only=offline, allow_patterns=patterns)


@lru_cache(maxsize=1)
def load_classifier(model, revision, cache, offline):
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification
    ast_path = snapshot(model, revision, cache, offline,
                        ["config.json", "preprocessor_config.json", "model.safetensors", "pytorch_model.bin"])
    torch.set_num_threads(8)
    extractor = ASTFeatureExtractor.from_pretrained(ast_path, local_files_only=True)
    classifier = ASTForAudioClassification.from_pretrained(ast_path, local_files_only=True).eval()
    return ast_path, extractor, classifier


def run(args):
    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly
    import torch
    from transformers import ASTFeatureExtractor, ASTForAudioClassification

    if args.output.exists():
        raise FileExistsError("Audit outputs are immutable; choose another path")
    x, sr = sf.read(args.audio, dtype="float32", always_2d=True)
    if not len(x) or not np.isfinite(x).all():
        raise ValueError("Audio must contain finite samples")
    mono = resample_poly(x.mean(axis=1), 16000, sr).astype(np.float32)
    seconds = len(x) / sr
    energy = [float(np.sqrt(np.mean(x[start:start+sr] ** 2))) for start in range(0, len(x), sr)]
    technical = {"duration_seconds": seconds, "sample_rate": sr, "channels": x.shape[1],
                 "peak": float(np.abs(x).max()), "rms": float(np.sqrt(np.mean(x*x))),
                 "clipped_fraction": float(np.mean(np.abs(x) >= .99999)),
                 "one_second_rms": energy}
    issues = []
    if seconds < args.min_seconds or (args.max_seconds is not None and seconds > args.max_seconds):
        issues.append("duration_outside_requested_range")
    if technical["rms"] < 1e-4:
        issues.append("nearly_silent")
    if technical["clipped_fraction"] > .0001:
        issues.append("clipping")
    ast_path, extractor, classifier = load_classifier(
        args.ast_model, args.ast_revision, args.cache_dir, args.offline)
    ids = {label: i for i, label in classifier.config.id2label.items() if label in VOCAL_LIMITS}
    if set(ids) != set(VOCAL_LIMITS):
        raise ValueError("Classifier labels changed; review the screening implementation")
    windows = []
    for start in window_starts(len(mono), 160000, 80000):
        features = extractor(mono[start:start+160000], sampling_rate=16000, return_tensors="pt")
        with torch.inference_mode():
            values = classifier(**features).logits.sigmoid()[0]
        top = torch.topk(values, 10)
        windows.append({"start": start/16000, "end": min(start+160000, len(mono))/16000,
                        "vocal_scores": {k: float(values[i]) for k, i in ids.items()},
                        "top_labels": {classifier.config.id2label[i]: float(v)
                                       for i, v in zip(top.indices.tolist(), top.values.tolist())}})
    maxima = {k: max(w["vocal_scores"][k] for w in windows) for k in ids}
    issues += ["possible_" + k.lower().replace(" ", "_") for k, v in maxima.items() if v >= VOCAL_LIMITS[k]]
    result = {"schema": 2, "audio_sha256": digest(args.audio), "audio": str(args.audio.resolve()),
              "status": "needs_review" if issues else "screen_clear", "issues": issues,
              "technical": technical,
              "audioset": {"model": ast_path, "windows": windows, "maxima": maxima,
                           "review_thresholds": VOCAL_LIMITS, "feature_backend": "torchaudio" if
                           importlib.util.find_spec("torchaudio") else "numpy"},
              "versions": {p: importlib.metadata.version(p) for p in
                           ("transformers", "torch", "numpy", "soundfile")},
              "limits": "Automated AudioSet screening, not personal listening. Scores are uncalibrated; no flags do not guarantee absence of vocals."}
    result["duration_bounds"] = {"min_seconds": args.min_seconds, "max_seconds": args.max_seconds}
    write(args.output, result)
    print(f"{args.audio}: {result['status']} ({', '.join(issues) or 'no automated vocal flags'})")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("audio", type=Path)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--ast-model", default="MIT/ast-finetuned-audioset-10-10-0.4593")
    p.add_argument("--ast-revision")
    p.add_argument("--cache-dir")
    p.add_argument("--offline", action="store_true")
    p.add_argument("--min-seconds", type=float, default=90)
    p.add_argument("--max-seconds", type=float, help="Optional upper limit; no maximum by default")
    a = p.parse_args()
    if a.min_seconds <= 0 or (a.max_seconds is not None and a.max_seconds < a.min_seconds):
        p.error("Invalid duration bounds")
    run(a)


if __name__ == "__main__":
    main()
