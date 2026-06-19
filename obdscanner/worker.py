"""
Background worker: owns the Transport + ELM327 and runs jobs serially on its
own thread so the tkinter GUI never blocks on slow Bluetooth I/O.

The GUI submits jobs with .submit(fn, on_done). `fn` receives the live ELM327
instance and runs on the worker thread; `on_done(result, error)` is queued
back and must be drained by the GUI on the main thread via .poll_results().
"""

from __future__ import annotations

import queue
import threading


class Job:
    __slots__ = ("fn", "on_done")

    def __init__(self, fn, on_done):
        self.fn = fn
        self.on_done = on_done


class Worker:
    def __init__(self):
        self._jobs: "queue.Queue[Job | None]" = queue.Queue()
        self._results: "queue.Queue[tuple]" = queue.Queue()
        self._thread: threading.Thread | None = None
        self._elm = None
        self._running = False

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        self._jobs.put(None)

    def submit(self, fn, on_done=None):
        self._jobs.put(Job(fn, on_done))

    def set_elm(self, elm):
        self._elm = elm

    @property
    def elm(self):
        return self._elm

    def _run(self):
        while self._running:
            job = self._jobs.get()
            if job is None:
                break
            try:
                result = job.fn(self._elm)
                error = None
            except Exception as e:  # surface to GUI rather than crashing thread
                result = None
                error = e
            if job.on_done is not None:
                self._results.put((job.on_done, result, error))

    def poll_results(self):
        """Call from the GUI thread to dispatch completed callbacks."""
        while True:
            try:
                on_done, result, error = self._results.get_nowait()
            except queue.Empty:
                break
            try:
                on_done(result, error)
            except Exception:
                pass
