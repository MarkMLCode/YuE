"""Behavioral BGM workflow checks with synthetic audio, without model inference."""
import contextlib
import importlib.util
import io
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import soundfile as sf
from yue2 import SemanticResult, SymbolicPlan, YuE2Pipeline  # Load torch before temporary module patches.

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/theme-bgm/scripts"


def load(name):
    spec = importlib.util.spec_from_file_location("test_bgm_" + name, SCRIPTS / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


common = load("common")
with patch.dict("sys.modules", {"common": common}):
    bgm = load("bgm")
    audit = load("audit")
    demos = load("demo_prompts")


class BgmWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(patch.stopall)
        patch.dict("sys.modules", {"audit": audit, "common": common}).start()
        self.output = io.StringIO()
        self.quiet = contextlib.redirect_stdout(self.output)
        self.quiet.__enter__()
        self.addCleanup(self.quiet.__exit__, None, None, None)
        self.repo = Path(self.temp.name)
        self.theme = self.repo / "music_previous/adventure begins"
        self.theme.mkdir(parents=True)
        sf.write(self.theme / "reference.wav", np.zeros(800), 8000)
        self.run = self.repo / "outputs/test-batch"
        self.groups = [{"id": f"g{i}", "title": f"Direction {i}", "style": f"Instrumental style {i}",
                        "summary": f"Intended style {i}.", "difference": f"Distinctive feature {i}.",
                        "seed": i * 1000, "demo_case_ids": []} for i in range(1, 4)]
        common.write(self.run / "batch.json", {"schema": 3, "repo": str(self.repo),
                     "theme": "adventure begins", "min_seconds": 90, "groups": self.groups})
        self.args = SimpleNamespace(run=self.run, model="fake", vae="fake", revision=None,
                                    vae_revision=None, device="cpu", offline=True,
                                    ast_model="fake", ast_revision=None, cache_dir=None, audit_python=None)

    def native(self, dest, seconds=90, truncated=False):
        from yue2.protocol import SongRequest
        from yue2.storage import collect_hashes
        n = dest / "native"
        n.mkdir(parents=True, exist_ok=True)
        request = SongRequest(**common.read(dest / "request.json")).to_dict()
        common.write(n / "request.json", request)
        common.write(n / "config.json", {})
        for filename in ("prefix.npy", "semantic.npy", "latent.npy"):
            np.save(n / filename, np.zeros(1))
        # Distinct PCM fixtures exercise actual duration measurement and lossless conversion.
        sr = 8000
        frequency = 200 + request["seed"] % 100
        samples = .1 * np.sin(2 * np.pi * frequency * np.arange(round(seconds * sr)) / sr)
        sf.write(n / "audio.flac", samples, sr, subtype="PCM_24")
        common.write(n / "result.json", {"status": "complete", "identity": dest.name,
                     "truncated": {"abc": False, "semantic": truncated}, "audio_seconds": seconds,
                     "sample_rate": sr, "weights": {}, "artifacts": collect_hashes(n)})
        common.write(dest / "state.json", {"status": "ready_for_audit"})

    def report(self, dest, issues=(), choir=0):
        maxima = dict.fromkeys(audit.VOCAL_LIMITS, .001)
        maxima["Choir"] = choir
        report = {"schema": 2, "status": "needs_review" if issues else "screen_clear",
                  "issues": list(issues), "audio_sha256": common.digest(dest / "native/audio.flac"),
                  "technical": {"duration_seconds": sf.info(dest / "native/audio.flac").duration},
                  "audioset": {"windows": [{"start": 0, "end": 90}], "maxima": maxima}}
        common.write(dest / "audit.json", report)
        return report

    def candidate(self, group=None, attempt=1, seconds=90, issues=(), choir=0, truncated=False):
        group = group or self.groups[0]
        request = bgm.request_for(group, attempt)
        dest = bgm.candidate(self.run, request["id"])
        common.write(dest / "request.json", request)
        self.native(dest, seconds, truncated)
        if seconds >= common.read(self.run / "batch.json")["min_seconds"]:
            self.report(dest, issues, choir)
        verdict = bgm.decision(dest)
        common.write(dest / "decision.json", verdict)
        common.write(dest / "state.json", {"status": "passed" if verdict["accepted"] else "rejected"})
        return dest

    def scenario(self, passes):
        calls = []

        def attempt(group, number):
            calls.append((group["id"], number))
            if number in passes.get(group["id"], set()):
                self.candidate(group, number)
            else:
                request = bgm.request_for(group, number)
                dest = bgm.candidate(self.run, request["id"])
                common.write(dest / "request.json", request)
                common.write(dest / "state.json", {"status": "rejected", "issues": ["fixture_failure"]})
        groups = bgm.execute_groups(self.run, self.groups, attempt)
        return calls, groups

    def test_example_exports_all_seven_as_lossless_wav_with_style_report(self):
        calls, groups = self.scenario({"g1": {5, 7}, "g2": {1, 2, 3, 4}, "g3": {3}})
        self.assertEqual([g["attempts"] for g in groups], [8, 4, 4])
        self.assertEqual([g["passes"] for g in groups], [2, 4, 1])
        self.assertEqual(len(calls), 16)
        bgm.export(self.args)
        directory = self.repo / "music/adventure begins"
        wavs = sorted(directory.glob("*.wav"))
        self.assertEqual(len(wavs), 7)
        self.assertFalse(list(directory.glob("*.flac")))
        receipt = common.read(directory / "selection-test-batch.json")
        for entry in receipt["selected"]:
            group_number = entry["id"].split("-")[0][1:]
            take = entry["id"].rsplit("-", 1)[-1]
            self.assertEqual(entry["file"], f"direction-{group_number}-{take}.wav")
            wav = directory / entry["file"]
            original = self.run / "candidates" / entry["id"] / "native/audio.flac"
            info = sf.info(wav)
            self.assertEqual((info.format, info.subtype, info.duration), ("WAV", "PCM_24", 90))
            np.testing.assert_array_equal(sf.read(wav, dtype="int32")[0], sf.read(original, dtype="int32")[0])
        report = (self.run / "final-results.md").read_text()
        for g in self.groups:
            self.assertIn(g["summary"], report)
            self.assertIn(g["difference"], report)
        self.assertIn("7 WAVs", report)
        # Re-running export verifies existing files and creates no duplicates.
        bgm.export(self.args)
        self.assertEqual(len(list(directory.glob("*.wav"))), 7)

    def test_all_fail_stops_at_24_and_exports_zero_without_review_gate(self):
        calls, groups = self.scenario({})
        self.assertEqual(len(calls), 24)
        self.assertTrue(all(g["complete"] and not g["passes"] for g in groups))
        bgm.export(self.args)
        self.assertIn("0 WAVs", (self.run / "final-results.md").read_text())

    def test_archive_keeps_rejected_audio_and_preserves_samples(self):
        self.candidate(attempt=1)
        self.candidate(attempt=2, seconds=45)
        self.candidate(attempt=3, issues=["possible_choir"], choir=.02)
        self.candidate(attempt=4, truncated=True)
        bgm.archive(self.args)
        index = common.read(self.run / "all/index.json")
        self.assertEqual(len(index["tracks"]), 4)
        self.assertEqual([e["status"] for e in index["tracks"]],
                         ["passed", "rejected", "rejected", "rejected"])
        for entry in index["tracks"]:
            wav = self.run / "all" / entry["file"]
            source = self.run / entry["artifacts"] / "native/audio.flac"
            self.assertEqual(sf.info(wav).subtype, "PCM_24")
            np.testing.assert_array_equal(sf.read(wav, dtype="int32")[0],
                                          sf.read(source, dtype="int32")[0])
        bgm.archive(self.args)
        self.assertEqual(len(list((self.run / "all").glob("*.wav"))), 4)
        self.assertFalse((self.repo / "music").exists())
        damaged = self.run / "all" / index["tracks"][0]["file"]
        damaged.write_bytes(b"keep this changed file")
        with self.assertRaises(FileExistsError):
            bgm.archive(self.args)
        self.assertEqual(damaged.read_bytes(), b"keep this changed file")

    def test_first_pass_still_finishes_quartet_and_single_pass_can_export(self):
        calls, groups = self.scenario({"g1": {1}})
        self.assertEqual(calls[:4], [("g1", n) for n in range(1, 5)])
        self.assertNotIn(("g1", 5), calls)
        self.assertEqual([g["attempts"] for g in groups], [4, 8, 8])
        bgm.export(self.args)
        self.assertEqual(len(list((self.repo / "music/adventure begins").glob("*.wav"))), 1)

    def test_resume_inside_quartet_does_not_stop_at_early_pass(self):
        self.candidate(attempt=1)
        calls, groups = self.scenario({})
        self.assertEqual(calls[:3], [("g1", 2), ("g1", 3), ("g1", 4)])
        self.assertEqual(groups[0]["attempts"], 4)

    def test_parallel_resume_preserves_finished_later_take(self):
        later = self.candidate(attempt=2)
        before = common.digest(later / "state.json")
        dest, action = bgm.prepare_attempt(self.run, self.groups[0], 2)
        self.assertEqual((dest, action), (later, "done"))
        self.assertEqual(common.digest(later / "state.json"), before)
        request = bgm.request_for(self.groups[0], 1)
        early = bgm.candidate(self.run, request["id"])
        common.write(early / "request.json", request)
        common.write(early / "state.json", {"status": "generating"})
        self.assertEqual(bgm.prepare_attempt(self.run, self.groups[0], 1)[1], "done")
        self.assertEqual(bgm.group_status(self.run, self.groups[0])["attempts"], 2)

    def test_quartet_callback_obeys_retry_budget_with_reverse_completions(self):
        calls = []

        def quartet(group, numbers):
            numbers = list(numbers)
            calls.append((group["id"], numbers))
            for number in reversed(numbers):
                self.candidate(group, number, seconds=45 if group["id"] == "g1" and number <= 4 else 90)

        groups = bgm.execute_groups(self.run, self.groups, batch_fn=quartet)
        self.assertEqual(calls, [("g1", [1, 2, 3, 4]), ("g1", [5, 6, 7, 8]),
                                 ("g2", [1, 2, 3, 4]), ("g3", [1, 2, 3, 4])])
        self.assertEqual([g["passes"] for g in groups], [4, 4, 4])

    def test_auto_gpu_selection_skips_busy_device_and_rejects_duplicates(self):
        args = SimpleNamespace(device=None, devices=None, min_free_gib=24)
        with patch("torch.cuda.device_count", return_value=2), \
             patch("torch.cuda.mem_get_info", side_effect=lambda i: ((8 if i == 0 else 90)*1024**3, 96*1024**3)):
            self.assertEqual(bgm.generation_devices(args), ["cuda:1"])
            args.devices = ["cuda:0", "cuda:1"]
            with self.assertRaisesRegex(RuntimeError, "less than"):
                bgm.generation_devices(args)
            args.devices = ["cuda:1", "cuda:01"]
            with self.assertRaisesRegex(ValueError, "more than once"):
                bgm.generation_devices(args)

    def test_second_runner_cannot_control_the_same_batch(self):
        import fcntl
        with (self.run / ".run.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, "active runner"):
                bgm.run(self.args)

    def test_parallel_runner_integrates_retry_screening_export_and_resume(self):
        batches = []
        test = self

        class Queue:
            def __init__(self, devices, loader):
                test.assertEqual(devices, ["cuda:0", "cuda:1"])

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                pass

            def process(self, jobs, saved, audit_fn):
                batches.append([Path(job[1]).name for job in jobs])
                for job in reversed(jobs):
                    dest = Path(job[1])
                    seconds = 45 if dest.name in {f"g1-{i:02d}" for i in range(1, 5)} else 90
                    test.native(dest, seconds=seconds)
                    audit_fn(job)
                for job in saved:
                    audit_fn(job)

        with patch.dict("sys.modules", {"parallel": SimpleNamespace(GenerationQueue=Queue)}), \
             patch.object(bgm, "generation_devices", return_value=["cuda:0", "cuda:1"]) as devices, \
             patch.object(audit, "run", side_effect=lambda a: self.report(a.output.parent)):
            bgm.run(self.args)
            bgm.run(self.args)
            self.assertEqual(devices.call_count, 1)
        self.assertEqual([len(b) for b in batches], [4, 4, 4, 4])
        self.assertEqual([b[0] for b in batches], ["g1-01", "g1-05", "g2-01", "g3-01"])
        self.assertEqual(len(list((self.repo / "music/adventure begins").glob("*.wav"))), 12)
        self.assertEqual(len(list((self.run / "all").glob("*.wav"))), 16)

    def test_duration_boundary_no_upper_limit_and_short_audio_skips_classifier(self):
        short = self.candidate(seconds=89.999)
        with patch.object(audit, "run") as classifier:
            self.assertFalse(bgm.screen(short, self.args)["accepted"])
            classifier.assert_not_called()
        self.assertTrue(bgm.decision(self.candidate(attempt=2, seconds=90))["accepted"])
        self.assertTrue(bgm.decision(self.candidate(attempt=3, seconds=241))["accepted"])

    def test_batch_specific_duration_preserves_legacy_and_accepts_75_seconds(self):
        manifest = common.read(self.run / "batch.json")
        self.assertEqual(bgm.batch(self.run)[1]["min_seconds"], 90)
        self.assertFalse(bgm.decision(self.candidate(seconds=80))["accepted"])
        manifest["min_seconds"] = 75
        common.write(self.run / "batch.json", manifest)
        self.assertEqual(bgm.batch(self.run)[1]["min_seconds"], 75)
        self.assertTrue(bgm.decision(self.candidate(attempt=2, seconds=75))["accepted"])
        short = self.candidate(attempt=3, seconds=74.999)
        with patch.object(audit, "run") as classifier:
            self.assertEqual(bgm.screen(short, self.args)["issues"], ["shorter_than_75_seconds"])
            classifier.assert_not_called()
        dest = bgm.candidate(self.run, "g1-04")
        common.write(dest / "request.json", bgm.request_for(self.groups[0], 4))
        self.native(dest, seconds=80)
        def classify(args):
            self.assertEqual(args.min_seconds, 75)
            self.report(dest)
        with patch.object(audit, "run", side_effect=classify):
            self.assertTrue(bgm.screen(dest, self.args)["accepted"])

    def test_choir_rejected_even_if_status_or_issues_omit_flag(self):
        c = self.candidate(choir=.02)
        self.assertFalse(bgm.decision(c)["accepted"])
        self.assertIn("possible_choir", bgm.decision(c)["issues"])

    def test_clipping_is_reported_not_ranked_and_silence_truncation_rejected(self):
        c = self.candidate(issues=["clipping"])
        self.assertTrue(bgm.decision(c)["accepted"])
        self.assertEqual(bgm.decision(c)["warnings"], ["clipping"])
        self.assertFalse(bgm.decision(self.candidate(attempt=2, issues=["nearly_silent"]))["accepted"])
        self.assertFalse(bgm.decision(self.candidate(attempt=3, truncated=True))["accepted"])

    def test_stale_audit_and_changed_audio_cannot_export(self):
        c = self.candidate()
        report = common.read(c / "audit.json")
        report["audio_sha256"] = "stale"
        common.write(c / "audit.json", report)
        with self.assertRaisesRegex(ValueError, "stale"):
            bgm.group_status(self.run, self.groups[0])
        (c / "native/audio.flac").write_bytes(b"corrupt")
        with self.assertRaisesRegex(ValueError, "corrupt"):
            bgm.decision(c)

    def test_incomplete_batch_and_existing_music_are_preserved(self):
        with self.assertRaisesRegex(ValueError, "Finish all"):
            bgm.export(self.args)
        self.scenario({"g1": {1}})
        music = self.repo / "music/adventure begins"
        music.mkdir(parents=True)
        occupied = music / "direction-1-01.wav"
        occupied.write_bytes(b"existing user's music")
        with self.assertRaises(FileExistsError):
            bgm.export(self.args)
        self.assertEqual(occupied.read_bytes(), b"existing user's music")
        self.assertEqual(len(list(music.iterdir())), 1)

    def test_export_failure_rolls_back_only_its_own_files(self):
        self.scenario({"g1": {1, 2}})
        with patch.object(bgm.shutil, "copyfileobj", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                bgm.export(self.args)
        self.assertEqual(list((self.repo / "music/adventure begins").iterdir()), [])

    def test_retry_uses_supplied_prompt_and_new_seeds_without_changing_group(self):
        group = {**self.groups[0], "retry_style": "Plucked instrumental", "abc": "original", "retry_abc": "retry"}
        first, retry = bgm.request_for(group, 1), bgm.request_for(group, 5)
        self.assertEqual(first["style"], group["style"])
        self.assertEqual(retry["style"], group["retry_style"])
        self.assertEqual(retry["abc"], "retry")
        self.assertEqual(retry["seed"], first["seed"] + 4)
        self.assertEqual(retry["lyrics"], "")

    def test_prepare_retains_summaries_and_rejects_wrong_prompt_count(self):
        prompts = self.repo / "prompts.json"
        common.write(prompts, self.groups)
        args = SimpleNamespace(repo=self.repo, theme="adventure begins", prompts=prompts,
                               output=self.repo / "outputs/new-batch")
        bgm.prepare(args)
        data = common.read(args.output / "batch.json")
        self.assertEqual(data["groups"][0]["difference"], self.groups[0]["difference"])
        self.assertEqual(data["min_seconds"], 75)
        common.write(prompts, self.groups[:2])
        with self.assertRaisesRegex(ValueError, "exactly three"):
            bgm.prepare(args)

    def test_empty_structure_tags_survive_prepare_and_retry(self):
        lyrics = "[Verse]\n\n[Pre-Chorus]\n\n[Chorus]\n\n[Outro]"
        groups = [{**g, "lyrics": lyrics} for g in self.groups]
        prompts = self.repo / "tagged-prompts.json"
        common.write(prompts, groups)
        args = SimpleNamespace(repo=self.repo, theme="adventure begins", prompts=prompts,
                               output=self.repo / "outputs/tagged")
        bgm.prepare(args)
        group = common.read(args.output / "batch.json")["groups"][0]
        for attempt in (1, 5):
            self.assertEqual(bgm.request_for(group, attempt)["lyrics"], lyrics)
        for bad in ("[Verse]\nSing these words", "[A singer sings]", None):
            with self.assertRaisesRegex(ValueError, "empty section tags"):
                bgm.request_for({**group, "lyrics": bad}, 1)

    def test_run_reuses_pipeline_exports_and_resumes_without_regeneration(self):
        pipe = MagicMock()
        pipe.__enter__.return_value = pipe

        def generate(pipe_arg, repo, dest):
            self.native(dest)

        def classify(args):
            return self.report(args.output.parent)

        with patch("yue2.YuE2Pipeline.from_pretrained", return_value=pipe) as loader, \
             patch.object(bgm, "generate_one", side_effect=generate) as generate_mock, \
             patch.object(audit, "run", side_effect=classify) as classifier:
            bgm.run(self.args)
            self.assertEqual(loader.call_count, 1)
            self.assertEqual(generate_mock.call_count, 12)
            self.assertEqual(classifier.call_count, 12)
            bgm.run(self.args)
            self.assertEqual(loader.call_count, 1)
            self.assertEqual(generate_mock.call_count, 12)
            self.assertEqual(classifier.call_count, 12)
        self.assertEqual(len(list((self.repo / "music/adventure begins").glob("*.wav"))), 12)
        self.assertEqual(len(list((self.run / "all").glob("*.wav"))), 12)

    def test_audit_error_pauses_then_resumes_saved_audio(self):
        pipe = MagicMock()
        pipe.__enter__.return_value = pipe
        with patch("yue2.YuE2Pipeline.from_pretrained", return_value=pipe), \
             patch.object(bgm, "generate_one", side_effect=lambda p, r, d: self.native(d)) as generation, \
             patch.object(audit, "run", side_effect=RuntimeError("classifier unavailable")):
            with self.assertRaisesRegex(RuntimeError, "classifier unavailable"):
                bgm.run(self.args)
            self.assertEqual(generation.call_count, 1)
            self.assertFalse((self.repo / "music").exists())
        with patch("yue2.YuE2Pipeline.from_pretrained", return_value=pipe), \
             patch.object(bgm, "generate_one", side_effect=lambda p, r, d: self.native(d)) as generation, \
             patch.object(audit, "run", side_effect=lambda a: self.report(a.output.parent)):
            bgm.run(self.args)
            self.assertEqual(generation.call_count, 11)

    def test_generation_stops_before_audio_when_score_has_vocal_notes(self):
        from yue2 import SymbolicPlan
        from yue2.protocol import SongRequest
        request = bgm.request_for(self.groups[0], 1)
        dest = bgm.candidate(self.run, request["id"])
        common.write(dest / "request.json", request)
        plan = SymbolicPlan(SongRequest(**request), (ROOT / "examples/score.abc").read_text(), [], [])
        pipe = MagicMock()
        pipe.plan.return_value = plan
        with self.assertRaisesRegex(bgm.CandidateRejected, "Vocal notes"):
            bgm.generate_one(pipe, ROOT, dest)
        pipe.generate_semantic.assert_not_called()

    def test_generation_saves_complete_native_artifacts(self):
        from yue2 import SymbolicPlan, SemanticResult
        from yue2.protocol import SongRequest
        from yue2.storage import verify_result
        request = bgm.request_for(self.groups[0], 1)
        dest = bgm.candidate(self.run, request["id"])
        common.write(dest / "request.json", request)
        score = ('X:1\nT:\nM:4/4\nL:1/32\nQ:1/4=100\n'
                 'V: Vocal clef=treble name="Vocal Melody" snm="Vocal"\n'
                 'V: Ins clef=treble name="Ins Melody" snm="Inst."\nK:C\n'
                 '% intro\nV: Vocal\n"C"z32|\nV: Ins\nC8E8G8c8|\n')
        plan = SymbolicPlan(SongRequest(**request), score, [1], [2])
        pipe = MagicMock()
        pipe.plan.return_value = plan
        pipe.generate_semantic.return_value = SemanticResult(plan, [1, 2], {}, False)
        pipe.synthesize.return_value = np.zeros((2, 64), dtype=np.float32)
        pipe.decode.return_value = np.zeros((4800, 2), dtype=np.float32)
        pipe.effective_config.return_value = {}
        pipe.weights = {}
        bgm.generate_one(pipe, ROOT, dest)
        self.assertFalse(any(verify_result(dest / "native")["truncated"].values()))
        self.assertEqual(common.read(dest / "state.json")["status"], "ready_for_audit")

    def test_window_coverage_includes_exact_end(self):
        for samples in (500, 160000, 160001, 958699, 1119339):
            starts = audit.window_starts(samples, 160000, 80000)
            self.assertEqual(starts[0], 0)
            self.assertGreaterEqual(starts[-1] + 160000, samples)
            self.assertTrue(all(b <= a + 160000 for a, b in zip(starts, starts[1:])))

    def test_demo_data_never_executes_trailing_javascript(self):
        self.assertEqual(demos.parse('window.YUE2_DATA = {"cases":[{"id":"x"}]};'), [{"id": "x"}])
        with self.assertRaises(ValueError):
            demos.parse('window.YUE2_DATA = {"cases":[]}; dangerous();')

    def test_path_traversal_and_symlink_escape_rejected(self):
        for value in ("../other", "a/b", "a\\b", "..", ""):
            with self.assertRaises(ValueError):
                common.component(value)
        (self.repo / "escape").symlink_to("/tmp")
        with self.assertRaises(ValueError):
            common.contained(self.repo, self.repo / "escape/out")


if __name__ == "__main__":
    unittest.main()
