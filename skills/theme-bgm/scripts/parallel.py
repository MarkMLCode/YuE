"""Persistent, isolated YuE2 workers and a completion-driven track queue."""
from collections import deque
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, ThreadPoolExecutor, wait
import multiprocessing
import os
from pathlib import Path
import time

_PIPE = None
_LOADER = None


def initialize_worker(loader):
    global _LOADER
    import torch
    torch.cuda.set_device(loader['device'])
    torch.set_num_threads(8)
    _LOADER = loader


def generate_job(job):
    """Only small paths cross processes; model weights and audio stay in the worker."""
    global _PIPE
    from yue2 import YuE2Pipeline
    from bgm import CandidateRejected, generate_one
    from common import write
    repo, dest = map(Path, job)
    if _PIPE is None:
        _PIPE = YuE2Pipeline.from_pretrained(**_LOADER)
    invocation = {'loader': _LOADER, 'worker_pid': os.getpid(), 'started_at': time.time()}
    write(dest / 'invocation.json', invocation)
    try:
        generate_one(_PIPE, repo, dest)
    except CandidateRejected as exc:
        write(dest / 'state.json', {'status': 'rejected', 'issues': [str(exc)]})
        return False
    finally:
        invocation['finished_at'] = time.time()
        write(dest / 'invocation.json', invocation)
    return True


class GenerationQueue:
    """At most one generation per GPU, plus one CPU audit at a time."""

    def __init__(self, devices, loader):
        self.workers = []
        self.auditor = None
        try:
            for device in devices:
                self.workers.append(ProcessPoolExecutor(
                    max_workers=1, mp_context=multiprocessing.get_context('spawn'),
                    initializer=initialize_worker, initargs=({**loader, 'device': device},)))
            self.auditor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='bgm-audit')
        except BaseException:
            self.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        # On error, cancel queued work and allow already-running jobs to save artifacts.
        if self.auditor is not None:
            self.auditor.shutdown(wait=True, cancel_futures=True)
        for worker in self.workers:
            worker.shutdown(wait=True, cancel_futures=True)

    def process(self, jobs, audit_jobs, audit_fn):
        pending = deque(jobs)
        generations = {}
        audits = {}
        free = list(self.workers)
        try:
            for job in audit_jobs:
                audits[self.auditor.submit(audit_fn, job)] = job
            while pending or generations or audits:
                while free and pending:
                    worker = free.pop(0)
                    job = pending.popleft()
                    generations[worker.submit(generate_job, job)] = (worker, job)
                done, _ = wait(set(generations) | set(audits), return_when=FIRST_COMPLETED)
                # Surface any failure before scheduling further work.
                results = {future: future.result() for future in done}
                for future, generated in results.items():
                    if future in generations:
                        worker, job = generations.pop(future)
                        free.append(worker)
                        if generated:
                            audits[self.auditor.submit(audit_fn, job)] = job
                    else:
                        audits.pop(future)
        except BaseException:
            for future in (*generations, *audits):
                future.cancel()
            raise
