#!/usr/bin/env python3
"""Run three instrumental prompt groups; screen batches of four and export passing WAVs."""
import argparse
from contextlib import ExitStack
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace

from common import component, contained, digest, identifier, read, write

GROUPS = 3
BATCH_SIZE = 4
GROUP_LIMIT = 8
MIN_SECONDS = 75
SCHEMA = 3


def minimum_seconds(value):
    if type(value) not in (int, float) or not 0 < value < float("inf"):
        raise ValueError("Minimum duration must be a positive finite number")
    return value


def candidate_minimum(dest):
    return minimum_seconds(read(dest.parent.parent / "batch.json")["min_seconds"])


def instrumental_lyrics(value):
    """Allow an empty lyric field or empty structure tags, never sung words."""
    if not isinstance(value, str) or any(
        not re.fullmatch(r"\[(?:Intro|Verse|Pre-Chorus|Chorus|Bridge|Interlude|Instrumental|Outro)\]",
                         line.strip(), re.IGNORECASE)
        for line in value.splitlines() if line.strip()
    ):
        raise ValueError("Instrumental lyrics must be empty or contain only empty section tags")
    return value


def score_check(repo, abc):
    helper = repo / "skills/yue2-music/scripts/abc_tools.py"
    spec = importlib.util.spec_from_file_location("theme_bgm_abc", helper)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    score = module.parse_abc(abc)
    if score.voices["Vocal"].notes:
        raise ValueError("Vocal notes are present: move the melody into Ins and keep Vocal as rests")
    if not score.voices["Ins"].notes:
        raise ValueError("Instrumental melody is empty")
    return json.loads(json.dumps(module.report(score), default=module.json_value))



def batch(path):
    path = Path(path).resolve()
    manifest = read(path / "batch.json")
    if manifest.get("schema") != SCHEMA:
        raise ValueError("Legacy batch: preserve its artifacts and prepare a new batch with --prompts")
    repo = Path(manifest["repo"]).resolve()
    contained(repo, path)
    contained(repo / "music_previous", repo / "music_previous" / component(manifest["theme"]))
    if len(manifest["groups"]) != GROUPS:
        raise ValueError("Expected three prompt groups")
    minimum_seconds(manifest["min_seconds"])
    return path, manifest, repo


def candidate(run, name):
    return contained(run, run / "candidates" / identifier(name))


def prepare(a):
    import soundfile as sf
    minimum = minimum_seconds(getattr(a, "min_seconds", MIN_SECONDS))
    repo = a.repo.resolve()
    theme = component(a.theme)
    source = contained(repo / "music_previous", repo / "music_previous" / theme)
    if not source.is_dir():
        raise ValueError(f"No theme folder: {source}")
    prompts = read(a.prompts)
    if not isinstance(prompts, list) or len(prompts) != GROUPS:
        raise ValueError("Prompts must be a JSON array of exactly three objects")
    groups = []
    for index, prompt in enumerate(prompts, 1):
        if not isinstance(prompt, dict) or not isinstance(prompt.get("style"), str) or not prompt["style"].strip():
            raise ValueError("Each prompt needs a nonempty style")
        for key in ("summary", "difference"):
            if not isinstance(prompt.get(key), str) or not prompt[key].strip():
                raise ValueError(f"Each prompt needs a short {key} for the final report")
        seed = prompt.get("seed", index * 1000)
        if type(seed) is not int or not 0 <= seed <= 2**63 - GROUP_LIMIT:
            raise ValueError("Seed must leave room for eight consecutive seeds")
        group = {"id": f"g{index}", "title": prompt.get("title", f"Prompt {index}"),
                 "style": prompt["style"], "seed": seed,
                 "summary": prompt["summary"], "difference": prompt["difference"],
                 "demo_case_ids": prompt.get("demo_case_ids", [])}
        if "lyrics" in prompt:
            group["lyrics"] = instrumental_lyrics(prompt["lyrics"])
        if "retry_style" in prompt:
            if not isinstance(prompt["retry_style"], str) or not prompt["retry_style"].strip():
                raise ValueError("retry_style must be nonempty when supplied")
            group["retry_style"] = prompt["retry_style"]
        for key in ("abc_file", "retry_abc_file"):
            if prompt.get(key):
                abc = (a.prompts.resolve().parent / prompt[key]).read_text(encoding="utf-8")
                score_check(repo, abc)
                group[key.replace("_file", "")] = abc
        groups.append(group)
    if len({g["style"].strip() for g in groups}) != GROUPS:
        raise ValueError("Write three distinct musical prompts")
    tracks = []
    for path in sorted(source.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".wav", ".flac", ".mp3", ".ogg", ".m4a"):
            continue
        contained(source, path)
        item = {"path": str(path.relative_to(repo)), "sha256": digest(path)}
        try:
            info = sf.info(path)
            item.update(seconds=info.duration, sample_rate=info.samplerate, channels=info.channels)
        except Exception as exc:
            item["metadata_error"] = str(exc)
        tracks.append(item)
    if not tracks:
        raise ValueError("Theme has no reference audio")
    output = contained(repo, a.output)
    identifier(output.name)
    output.mkdir(parents=True, exist_ok=False)
    write(output / "batch.json", {"schema": SCHEMA, "repo": str(repo), "theme": theme,
          "groups": groups, "batch_size": BATCH_SIZE, "group_limit": GROUP_LIMIT,
          "min_seconds": minimum, "references": tracks,
          "created_at": datetime.now(timezone.utc).isoformat(),
          "demo_site": "https://map-yue2.github.io/"})
    print(output)


def request_for(group, attempt):
    retry = attempt > BATCH_SIZE
    request = {"id": f"{group['id']}-{attempt:02d}",
               "style": group.get("retry_style", group["style"]) if retry else group["style"],
               "lyrics": instrumental_lyrics(group.get("lyrics", "")),
               "cot": "full", "seed": group["seed"] + attempt - 1}
    abc = group.get("retry_abc", group.get("abc")) if retry else group.get("abc")
    if abc:
        request["abc"] = abc
    return request


class CandidateRejected(ValueError):
    """Musical failure that consumes one attempt, unlike an infrastructure error."""


def generate_one(pipe, repo, dest):
    from yue2 import SongResult
    from yue2.storage import identity, verify_result
    import numpy as np
    request = read(dest / "request.json")
    write(dest / "state.json", {"status": "generating"})
    start = time.perf_counter()
    plan = pipe.plan(**request)
    plan.save(dest / "plan")
    if plan.truncated:
        raise CandidateRejected("Planner hit its token limit; supply a bounded instrumental score")
    try:
        report = score_check(repo, plan.abc)
    except ValueError as exc:
        raise CandidateRejected(str(exc)) from exc
    write(dest / "score_check.json", report)
    semantic = pipe.generate_semantic(plan)
    np.save(dest / "semantic.npy", np.asarray(semantic.tokens, dtype=np.int32))
    if semantic.truncated:
        raise CandidateRejected("Audio token generation hit its limit; revise the structure")
    nar_start = time.perf_counter()
    latent = pipe.synthesize(semantic)
    nar_seconds = time.perf_counter() - nar_start
    np.save(dest / "latent.npy", latent)
    vae_start = time.perf_counter()
    audio = pipe.decode(latent)
    config = pipe.effective_config(plan.request)
    timing = {"abc": plan.timing, "semantic": semantic.timing,
              "nar_seconds": nar_seconds, "vae_seconds": time.perf_counter()-vae_start,
              "e2e_seconds": time.perf_counter()-start}
    key = identity({"request": plan.request.to_dict(), "config": config, "weights": pipe.weights})
    song = SongResult(audio, 48000, semantic, latent, config, pipe.weights, timing, key)
    song.save_artifacts(dest / "native")
    verify_result(dest / "native")
    write(dest / "state.json", {"status": "ready_for_audit"})


def native_result(dest):
    from yue2.storage import verify_result
    from yue2.protocol import SongRequest
    result = verify_result(dest / "native")
    expected = SongRequest(**read(dest / "request.json")).to_dict()
    if expected != read(dest / "native/request.json"):
        raise ValueError("Candidate request differs from generated audio provenance")
    return result


def decision(dest):
    import soundfile as sf
    from audit import VOCAL_LIMITS
    result = native_result(dest)
    audio = dest / "native/audio.flac"
    seconds = sf.info(audio).duration
    if any(result["truncated"].values()):
        return {"accepted": False, "seconds": seconds, "issues": ["truncated"]}
    minimum = candidate_minimum(dest)
    if seconds < minimum:
        return {"accepted": False, "seconds": seconds, "issues": [f"shorter_than_{minimum:g}_seconds"]}
    report = read(dest / "audit.json")
    if report.get("status") not in ("screen_clear", "needs_review") or report.get("audio_sha256") != digest(audio):
        raise ValueError("Missing, failed or stale audio audit")
    if not isinstance(report.get("issues"), list) or not report.get("audioset", {}).get("windows"):
        raise ValueError("Incomplete AudioSet report")
    maxima = report["audioset"].get("maxima", {})
    if set(maxima) != set(VOCAL_LIMITS) or not all(0 <= v <= 1 for v in maxima.values()):
        raise ValueError("Incomplete or invalid vocal scores")
    flags = {"possible_" + k.lower().replace(" ", "_")
             for k, v in maxima.items() if v >= VOCAL_LIMITS[k]}
    # Clipping is reported for the user's later review, not a musical quality gate.
    blocking = set(report["issues"]) - {"clipping"}
    issues = sorted(blocking | flags)
    label = max(maxima, key=maxima.get)
    return {"accepted": not issues, "seconds": seconds, "issues": issues,
            "warnings": [v for v in report["issues"] if v == "clipping"],
            "highest_vocal_score": {"label": label, "score": maxima[label]},
            "audio_sha256": digest(audio),
            "audit_sha256": digest(dest / "audit.json"), "method": "automated_audioset"}


def screen(dest, a):
    import soundfile as sf
    native_result(dest)
    minimum = candidate_minimum(dest)
    # Reject short tracks before spending CPU time on vocal classification.
    if sf.info(dest / "native/audio.flac").duration < minimum:
        return decision(dest)
    if not (dest / "audit.json").exists():
        options = [str(Path(__file__).with_name("audit.py")), str(dest / "native/audio.flac"),
                   "--output", str(dest / "audit.json"), "--min-seconds", str(minimum),
                   "--ast-model", a.ast_model]
        if a.ast_revision:
            options += ["--ast-revision", a.ast_revision]
        if a.cache_dir:
            options += ["--cache-dir", a.cache_dir]
        if a.offline:
            options += ["--offline"]
        if a.audit_python:
            subprocess.run([str(a.audit_python), *options], check=True)
        else:
            import audit
            audit.run(SimpleNamespace(audio=dest / "native/audio.flac", output=dest / "audit.json",
                      min_seconds=minimum, max_seconds=None, ast_model=a.ast_model,
                      ast_revision=a.ast_revision, cache_dir=a.cache_dir, offline=a.offline))
    return decision(dest)


def group_status(run, group):
    rows = []
    for attempt in range(1, GROUP_LIMIT + 1):
        dest = candidate(run, f"{group['id']}-{attempt:02d}")
        if not (dest / "state.json").exists():
            break
        state = read(dest / "state.json")
        if state["status"] not in ("passed", "rejected"):
            break
        if read(dest / "request.json") != request_for(group, attempt):
            raise ValueError("Prompt changed after generation; prepare a new batch")
        if state["status"] == "passed":
            current = decision(dest)
            if not current["accepted"] or current != read(dest / "decision.json"):
                raise ValueError("A passing candidate or its audit changed")
        rows.append({"id": dest.name, **state})
    passes = sum(row["status"] == "passed" for row in rows)
    complete = len(rows) == GROUP_LIMIT or (len(rows) == BATCH_SIZE and passes > 0)
    return {"id": group["id"], "title": group["title"],
            "summary": group["summary"], "difference": group["difference"],
            "attempts": len(rows), "passes": passes,
            "complete": complete, "candidates": rows}


def execute_groups(run, groups, attempt_fn=None, batch_fn=None):
    """Finish each quartet before deciding whether this prompt needs one retry quartet."""
    for group in groups:
        state = group_status(run, group)
        while not state["complete"]:
            end = BATCH_SIZE if state["attempts"] < BATCH_SIZE else GROUP_LIMIT
            attempts = range(state["attempts"] + 1, end + 1)
            if batch_fn is not None:
                batch_fn(group, attempts)
            else:
                for attempt in attempts:
                    attempt_fn(group, attempt)
            state = group_status(run, group)
            print(f"{group['id']}: {state['passes']} passes / {state['attempts']} attempts", flush=True)
    return [group_status(run, g) for g in groups]


def generation_devices(a):
    """Auto-select GPUs with room for independent replicas; explicit CPU stays supported."""
    import torch
    requested = getattr(a, "devices", None)
    if getattr(a, "device", None):
        requested = [a.device]
    if requested and len(requested) == 1 and requested[0] in ("cpu", "mps"):
        return requested
    automatic = not requested or requested == ["auto"]
    count = torch.cuda.device_count()
    if not count:
        raise RuntimeError("No CUDA GPUs are visible; check GPU access, or explicitly use --device cpu")
    if automatic:
        requested = [f"cuda:{i}" for i in range(count)]
    devices = []
    minimum = getattr(a, "min_free_gib", 24)
    if not 0 < minimum < float("inf"):
        raise ValueError("--min-free-gib must be positive and finite")
    for name in requested:
        name = "cuda:0" if name == "cuda" else name
        if not re.fullmatch(r"cuda:[0-9]+", name) or int(name.split(":")[1]) >= count:
            raise ValueError(f"Invalid or unavailable GPU: {name}")
        name = f"cuda:{int(name.split(':')[1])}"
        if name in devices:
            raise ValueError(f"GPU listed more than once: {name}")
        free, _ = torch.cuda.mem_get_info(int(name.split(":")[1]))
        if free < minimum * 1024**3:
            if automatic:
                print(f"Skipping {name}: {free / 1024**3:.1f} GiB free", flush=True)
                continue
            raise RuntimeError(f"{name} has less than {minimum:g} GiB free")
        devices.append(name)
    if not devices:
        raise RuntimeError("No GPU has enough free memory; leave other services running and retry later")
    return devices


def prepare_attempt(run_path, group, number):
    request = request_for(group, number)
    dest = candidate(run_path, request["id"])
    dest.mkdir(parents=True, exist_ok=True)
    if (dest / "request.json").exists() and read(dest / "request.json") != request:
        raise ValueError("Prompt changed after generation; prepare a new batch")
    state = read(dest / "state.json") if (dest / "state.json").exists() else {}
    # Parallel completions can leave a finished later take behind an unfinished earlier one.
    if state.get("status") in ("passed", "rejected"):
        return dest, "done"
    write(dest / "request.json", request)
    write(dest / "brief.json", {"title": f"{group['title']} {number:02d}",
                               "demo_case_ids": group["demo_case_ids"]})
    if (dest / "native/result.json").is_file():
        native_result(dest)
        return dest, "audit"
    if state.get("status") == "generating":
        write(dest / "state.json", {"status": "rejected", "issues": ["interrupted_generation"]})
        return dest, "done"
    return dest, "generate"


def audit_attempt(dest, a):
    verdict = screen(dest, a)
    write(dest / "decision.json", verdict)
    write(dest / "state.json", {"status": "passed" if verdict["accepted"] else "rejected",
                               "seconds": verdict["seconds"], "issues": verdict["issues"]})


def run(a):
    import fcntl
    run_path, _, _ = batch(a.run)
    with (run_path / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("This batch already has an active runner") from exc
        run_batch(a)


def run_batch(a):
    from yue2 import YuE2Pipeline
    run_path, b, repo = batch(a.run)
    if all(group_status(run_path, group)["complete"] for group in b["groups"]):
        export(a)
        return
    devices = generation_devices(a)
    print(f"Generation devices: {', '.join(devices)}", flush=True)
    loader = dict(model=a.model, vae=a.vae, revision=a.revision, vae_revision=a.vae_revision,
                  device=devices[0], local_files_only=a.offline)
    with ExitStack() as stack:
        pipe = None
        queue = None
        if len(devices) > 1:
            from parallel import GenerationQueue
            queue = stack.enter_context(GenerationQueue(devices, loader))

        def attempt(group, number):
            nonlocal pipe
            dest, action = prepare_attempt(run_path, group, number)
            if action == "done":
                return
            if action == "generate":
                if pipe is None:
                    pipe = stack.enter_context(YuE2Pipeline.from_pretrained(**loader))
                write(dest / "invocation.json", {"loader": loader})
                try:
                    generate_one(pipe, repo, dest)
                except CandidateRejected as exc:
                    write(dest / "state.json", {"status": "rejected", "issues": [str(exc)]})
                    return
                # Infrastructure errors stop the run instead of burning the budget.
            audit_attempt(dest, a)

        def parallel_batch(group, numbers):
            jobs, audit_jobs = [], []
            for number in numbers:
                dest, action = prepare_attempt(run_path, group, number)
                if action == "generate":
                    jobs.append((str(repo), str(dest)))
                elif action == "audit":
                    audit_jobs.append((str(repo), str(dest)))
            queue.process(jobs, audit_jobs, lambda job: audit_attempt(Path(job[1]), a))

        groups = execute_groups(run_path, b["groups"], attempt,
                                batch_fn=parallel_batch if queue is not None else None)
    write(run_path / "outcome.json", {"groups": groups, "passes": sum(g["passes"] for g in groups)})
    export(a)


def wav_name(title, candidate_id):
    """Use a readable prompt title and the original take number, without the theme."""
    stem = re.sub(r"[\W_]+", "-", title.strip().lower()).strip("-")[:100] or "track"
    take = identifier(candidate_id).rsplit("-", 1)[-1]
    return f"{stem}-{take}.wav"


def archive(a):
    """Save all available generated audio, regardless of screening outcome."""
    import soundfile as sf
    run_path, b, _ = batch(a.run)
    destination = contained(run_path, run_path / "all")
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    names = set()
    with tempfile.TemporaryDirectory(prefix=".wav-", dir=destination) as temp:
        for group in b["groups"]:
            for attempt in range(1, GROUP_LIMIT + 1):
                c = candidate(run_path, f"{group['id']}-{attempt:02d}")
                audio = c / "native/audio.flac"
                if not audio.is_file():
                    continue  # Planning failures can have no audio to convert.
                native_result(c)
                name = wav_name(group["title"], c.name)
                if name in names:
                    raise ValueError("Prompt titles produce duplicate archive names")
                names.add(name)
                staged = Path(temp) / name
                samples, sr = sf.read(audio, dtype="int32", always_2d=True)
                sf.write(staged, samples, sr, format="WAV", subtype="PCM_24")
                wav = destination / name
                sha = digest(staged)
                if wav.is_symlink():
                    raise FileExistsError(f"Archive destination is a symlink: {wav}")
                if wav.exists():
                    if digest(wav) != sha:
                        raise FileExistsError(f"Archive would overwrite different audio: {wav}")
                else:
                    wav.hardlink_to(staged)  # Atomic creation; never replace an existing file.
                state = read(c / "state.json") if (c / "state.json").exists() else {}
                entries.append({"id": c.name, "title": group["title"], "file": name,
                                "seconds": len(samples) / sr, "status": state.get("status", "not_screened"),
                                "issues": state.get("issues", []), "wav_sha256": sha,
                                "source_sha256": digest(audio),
                                "artifacts": str(c.relative_to(run_path))})
    write(destination / "index.json", {"run": str(run_path), "theme": b["theme"], "tracks": entries})
    print(f"Saved {len(entries)} generated WAVs to {destination}")


def export(a):
    import soundfile as sf
    run_path, b, repo = batch(a.run)
    groups = [group_status(run_path, g) for g in b["groups"]]
    if not all(g["complete"] for g in groups):
        raise ValueError("Finish all three prompt groups before exporting")
    archive(a)
    chosen = [candidate(run_path, row["id"]) for g in groups for row in g["candidates"]
              if row["status"] == "passed"]
    music = contained(repo, repo / "music")
    destination = contained(music, music / component(b["theme"]))
    receipt_name = "selection-" + identifier(run_path.name) + ".json"
    receipt = destination / receipt_name
    if receipt.is_file():
        prior = read(receipt)
        if prior.get("run") != str(run_path) or [e["id"] for e in prior["selected"]] != [c.name for c in chosen]:
            raise FileExistsError("Selection name already exists; use a different run folder")
        for entry, c in zip(prior["selected"], chosen):
            wav = contained(destination, destination / entry["file"])
            if digest(wav) != entry["wav_sha256"] or digest(c / "native/audio.flac") != entry["source_sha256"]:
                raise ValueError("Export changed since its receipt was written")
        final_report(run_path, prior)
        print(f"Already exported {len(chosen)} WAVs to {destination}")
        return
    titles = {row["id"]: group["title"] for group in groups for row in group["candidates"]}
    names = [wav_name(titles[c.name], c.name) for c in chosen] + [receipt_name]
    if len(set(names)) != len(names):
        raise ValueError("Prompt titles produce duplicate WAV names; use distinct titles")
    if any((destination / n).exists() or (destination / n).is_symlink() for n in names):
        raise FileExistsError("Export would overwrite existing music; use new prompt titles")
    destination.mkdir(parents=True, exist_ok=True)
    entries = []
    with tempfile.TemporaryDirectory(prefix=".bgm-export-", dir=destination) as temp:
        stage = Path(temp)
        for c, name in zip(chosen, names):
            audio = c / "native/audio.flac"
            samples, sr = sf.read(audio, dtype="int32", always_2d=True)
            sf.write(stage / name, samples, sr, format="WAV", subtype="PCM_24")
            entries.append({"id": c.name, "file": name, "wav_sha256": digest(stage / name),
                            "source_sha256": digest(audio), "artifacts": str(c.relative_to(repo)),
                            "request": read(c / "native/request.json"), "decision": read(c / "decision.json"),
                            "weights": read(c / "native/result.json")["weights"]})
        selection = {"theme": b["theme"], "run": str(run_path), "groups": groups,
                     "min_seconds": b["min_seconds"],
                     "selected": entries, "note": "AudioSet screening only; no personal listening or guarantee of vocal absence."}
        write(stage / receipt_name, selection)
        written = []
        try:
            for name in names:
                with (destination / name).open("xb") as dst, (stage / name).open("rb") as src:
                    written.append(destination / name)
                    shutil.copyfileobj(src, dst)
        except Exception:
            for path in written:
                path.unlink()
            raise
    write(run_path / "export.json", {"destination": str(destination), "files": names, "passes": len(chosen)})
    final_report(run_path, selection)
    print(f"Exported {len(chosen)} WAVs to {destination}")


def final_report(run_path, selection):
    """Format already saved measurements; no ranking or additional analysis."""
    lines = [f"{len(selection['selected'])} WAVs exported for {selection['theme']}.", "",
             "Intended styles (prompt descriptions, not listening assessments):", ""]
    for group in selection["groups"]:
        lines.append(f"- {group['id']} — {group['title']}: {group['summary']} {group['difference']}")
    lines += ["",
             "| File | Seconds | Vocal screen | Other flags |",
             "| --- | ---: | --- | --- |"]
    for entry in selection["selected"]:
        verdict = entry["decision"]
        flags = ", ".join(verdict.get("warnings", [])) or "None"
        lines.append(f"| {entry['file']} | {verdict['seconds']:.2f} | No flags | {flags} |")
    lines += ["", "Prompt groups: " + "; ".join(
        f"{g['id']}: {g['passes']}/{g['attempts']} passed" for g in selection["groups"]),
        "", "AudioSet screening only; no subjective quality score or guaranteed vocal absence."]
    if (run_path / "all/index.json").is_file():
        count = len(read(run_path / "all/index.json")["tracks"])
        lines += ["", f"All {count} generated tracks, including rejected takes: [all/](all/).",
                  "Screening outcomes and source references: [all/index.json](all/index.json)."]
    text = "\n".join(lines) + "\n"
    (run_path / "final-results.md").write_text(text, encoding="utf-8")
    print(text)


def status(a):
    path, b, _ = batch(a.run)
    print(json.dumps({"theme": b["theme"], "minimum_seconds": b["min_seconds"],
                      "groups": [group_status(path, g) for g in b["groups"]]}, indent=2))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    q = sub.add_parser("prepare", help="Snapshot the theme and three prompts")
    q.add_argument("--repo", type=Path, default=Path.cwd())
    q.add_argument("--theme", required=True)
    q.add_argument("--prompts", type=Path, required=True)
    q.add_argument("--output", type=Path, required=True)
    q.add_argument("--min-seconds", type=float, default=MIN_SECONDS,
                   help="Minimum accepted duration saved with this batch (default: 75)")
    for name in ("run", "export", "archive", "status"):
        q = sub.add_parser(name)
        q.add_argument("--run", type=Path, required=True)
        if name == "run":
            q.add_argument("--model", default="m-a-p/YuE2-3B")
            q.add_argument("--vae", default="m-a-p/YuE2-Vae")
            q.add_argument("--revision")
            q.add_argument("--vae-revision")
            device_args = q.add_mutually_exclusive_group()
            device_args.add_argument("--device", help="Use one device, e.g. cuda:0 or cpu")
            device_args.add_argument("--devices", nargs="+", help="GPU list, e.g. cuda:0 cuda:1; default: auto")
            q.add_argument("--min-free-gib", type=float, default=24,
                           help="Minimum initial free GPU memory (default: 24 GiB)")
            q.add_argument("--offline", action="store_true")
            q.add_argument("--audit-python", type=Path, help="Optional separate AudioSet environment")
            q.add_argument("--ast-model", default="MIT/ast-finetuned-audioset-10-10-0.4593")
            q.add_argument("--ast-revision")
            q.add_argument("--cache-dir", help="AudioSet model cache")
    a = p.parse_args()
    try:
        globals()[a.command](a)
    except (ValueError, OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        p.exit(1, f"{type(exc).__name__}: {exc}\n")


if __name__ == "__main__":
    main()
