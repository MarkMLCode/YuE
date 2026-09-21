"""Scheduling tests use controlled CPU workers; no model downloads or GPU required."""
from concurrent.futures import Future, ThreadPoolExecutor
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/theme-bgm/scripts'
spec = importlib.util.spec_from_file_location('test_parallel_worker', SCRIPTS / 'parallel.py')
parallel = importlib.util.module_from_spec(spec)
spec.loader.exec_module(parallel)


class SchedulingTests(unittest.TestCase):
    def test_free_gpu_takes_next_job_while_other_gpu_and_audit_are_busy(self):
        slow_started = threading.Event()
        release_slow = threading.Event()
        all_generated = threading.Event()
        lock = threading.Lock()
        assignments, audited, created = [], [], []
        active, peak = {}, {}
        finished = 0

        def generate(device, job):
            nonlocal finished
            with lock:
                assignments.append((job, device))
                active[device] = active.get(device, 0) + 1
                peak[device] = max(peak.get(device, 0), active[device])
            if job == 0:
                slow_started.set()
                if not release_slow.wait(5):
                    raise RuntimeError('Idle GPU did not consume queued tracks')
            elif job == 1:
                if not slow_started.wait(5):
                    raise RuntimeError('Second GPU did not start')
            elif job == 3:
                release_slow.set()
            with lock:
                active[device] -= 1
                finished += 1
                if finished >= 4:
                    all_generated.set()
            return True

        class Worker:
            def __init__(self, **kwargs):
                self.device = kwargs['initargs'][0]['device']
                created.append(self.device)
                self.executor = ThreadPoolExecutor(max_workers=1)

            def submit(self, fn, job):
                return self.executor.submit(generate, self.device, job)

            def shutdown(self, **kwargs):
                self.executor.shutdown(**kwargs)

        def audit(job):
            if not all_generated.wait(5):
                raise RuntimeError('Generation waited for the slow audit')
            audited.append(job)

        with patch.object(parallel, 'ProcessPoolExecutor', Worker):
            with parallel.GenerationQueue(['cuda:0', 'cuda:1'], {}) as queue:
                queue.process(range(4), [], audit)
                queue.process(range(4, 8), [], audit)
        self.assertEqual(dict(assignments)[0], 'cuda:0')
        self.assertEqual(dict(assignments)[2], 'cuda:1')
        self.assertEqual(dict(assignments)[3], 'cuda:1')
        self.assertEqual(peak, {'cuda:0': 1, 'cuda:1': 1})
        self.assertEqual(created, ['cuda:0', 'cuda:1'])  # Reused for second quartet.
        self.assertEqual(sorted(audited), list(range(8)))

    def test_worker_failure_stops_dispatch_and_skips_further_jobs(self):
        submitted = []

        class Worker:
            def __init__(self, **kwargs):
                pass

            def submit(self, fn, job):
                submitted.append(job)
                future = Future()
                if job == 0:
                    future.set_exception(RuntimeError('GPU unavailable'))
                else:
                    future.set_result(True)
                return future

            def shutdown(self, **kwargs):
                pass

        with patch.object(parallel, 'ProcessPoolExecutor', Worker):
            with parallel.GenerationQueue(['cuda:0', 'cuda:1'], {}) as queue:
                with self.assertRaisesRegex(RuntimeError, 'GPU unavailable'):
                    queue.process(range(4), [], lambda job: None)
        self.assertEqual(submitted, [0, 1])

    def test_saved_audio_is_audited_without_starting_generation(self):
        audited = []
        with patch.object(parallel, 'ProcessPoolExecutor') as pool:
            with parallel.GenerationQueue(['cuda:0', 'cuda:1'], {}) as queue:
                queue.process([], ['saved-take'], audited.append)
            pool.return_value.submit.assert_not_called()
        self.assertEqual(audited, ['saved-take'])


if __name__ == '__main__':
    unittest.main()
