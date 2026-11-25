from __future__ import annotations

import os
import threading
import time
from typing import Callable, Optional


class LogWatcher:
    """Simple polling file watcher/tailer.

    Reads existing content and then appends new lines as the file grows.
    Designed for demo reliability, not high-throughput ingestion.

    With ``follow=False`` the watcher performs the initial read only and stops
    by itself once the file has been drained, so callers can wait on
    :attr:`initial_read_done` instead of sleeping for a guessed duration.
    """

    def __init__(
        self,
        path: str,
        on_line: Callable[[str, int], None],
        poll_interval: float = 0.5,
        read_from_start: bool = True,
        follow: bool = True,
    ) -> None:
        self.path = path
        self.on_line = on_line
        self.poll_interval = poll_interval
        self.read_from_start = read_from_start
        self.follow = follow
        self.initial_read_done = threading.Event()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._line_no = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self.initial_read_done.clear()
        self._thread = threading.Thread(target=self._run, name="log-watcher", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)

    def _run(self) -> None:
        # Wait for file to exist.
        while not self._stop.is_set() and not os.path.exists(self.path):
            time.sleep(self.poll_interval)

        if self._stop.is_set():
            return

        offset = 0
        inode = None
        try:
            st = os.stat(self.path)
            inode = st.st_ino
            if not self.read_from_start:
                offset = st.st_size
        except OSError:
            offset = 0

        while not self._stop.is_set():
            try:
                st = os.stat(self.path)
                current_inode = st.st_ino
                # File rotated/recreated.
                if inode is not None and current_inode != inode:
                    offset = 0
                    inode = current_inode
                    self._line_no = 0
                if st.st_size < offset:
                    offset = 0
                    self._line_no = 0

                if st.st_size > offset:
                    with open(self.path, "r", encoding="utf-8", errors="replace") as f:
                        f.seek(offset)
                        chunk = f.read()
                        offset = f.tell()
                    for line in chunk.splitlines():
                        self._line_no += 1
                        self.on_line(line, self._line_no)

                if not self.initial_read_done.is_set() and st.st_size <= offset:
                    self.initial_read_done.set()
                    if not self.follow:
                        return
            except FileNotFoundError:
                # File may be rotated; wait for it to reappear.
                pass
            except OSError:
                pass

            time.sleep(self.poll_interval)
