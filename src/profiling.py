"""Opt-in process RSS sampling. Reports contain metadata, never source text."""
from contextlib import contextmanager
from contextvars import ContextVar
import json
import os
import sys
import threading
import time

_current = ContextVar('recall_profile', default=None)


def enabled():
    return _current.get() is not None


class MemorySample:
    def __enter__(self):
        import psutil
        self.process = psutil.Process()
        self.start = self.process.memory_info().rss
        self.peak = self.start
        self.stop = threading.Event()
        self.thread = threading.Thread(target=self.poll, daemon=True)
        self.thread.start()
        self.started = time.perf_counter()
        return self

    def poll(self):
        while not self.stop.wait(.05):
            self.peak = max(self.peak, self.process.memory_info().rss)

    def __exit__(self, *error):
        self.end = self.process.memory_info().rss
        self.peak = max(self.peak, self.end)
        self.elapsed = time.perf_counter() - self.started
        self.stop.set()
        self.thread.join()

    def record(self, stage, **metadata):
        return dict(stage=stage, pid=os.getpid(), seconds=round(self.elapsed, 4),
                    rss_start_mib=round(self.start / 2**20, 2),
                    rss_end_mib=round(self.end / 2**20, 2),
                    sampled_peak_rss_mib=round(self.peak / 2**20, 2), **metadata)


@contextmanager
def measure(stage, **metadata):
    records = _current.get()
    if records is None:
        yield
        return
    sample = MemorySample()
    try:
        with sample:
            yield
    finally:
        if hasattr(sample, 'elapsed'):
            records.append(sample.record(stage, **metadata))


def add_remote(records):
    current = _current.get()
    if current is not None:
        current.extend(dict(record, process='worker') for record in records)


@contextmanager
def capture(active=False, label='command', emit=True):
    if not active:
        yield []
        return
    records = []
    token = _current.set(records)
    try:
        sample = MemorySample()
        try:
            with sample:
                yield records
        finally:
            if hasattr(sample, 'elapsed'):
                records.append(sample.record(label))
    finally:
        _current.reset(token)
        if emit:
            for record in records:
                print('[profile] ' + json.dumps(record), file=sys.stderr, flush=True)
