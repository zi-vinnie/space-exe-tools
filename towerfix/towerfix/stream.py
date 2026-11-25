"""Read raw samples in chunks, from a .cu8 file or a live RTL-SDR.

Each chunk holds `frames` whole DAB frames plus two spare frames, because
`timing.process_frames` needs a frame of slack to find the first null and
another at the end. Chunks are analysed on their own, so a gap between two
chunks (for example while the computer is busy) does no harm.
"""

import os
import subprocess
import tempfile
import threading
from pathlib import Path

import numpy as np

from .timing import FS, T_FRAME

FREQ_12B = 225_648_000


def frames_for(seconds):
    return max(4, round(seconds * FS / T_FRAME))


class FileChunks:
    """Chunks of a recording, read with seek so big files never load whole."""

    def __init__(self, path, seconds=5.0):
        self.path = Path(path)
        self.frames = frames_for(seconds)
        self.step_bytes = self.frames * T_FRAME * 2
        self.read_bytes = (self.frames + 2) * T_FRAME * 2
        size = os.path.getsize(self.path)
        self.count = max(0, (size - 2 * T_FRAME * 2) // self.step_bytes)

    def seconds_at(self, i):
        return i * self.frames * T_FRAME / FS

    def read(self, i):
        with open(self.path, "rb") as f:
            f.seek(i * self.step_bytes)
            b = f.read(self.read_bytes)
        return np.frombuffer(b, dtype=np.uint8)


class LiveChunks:
    """Runs rtl_sdr and keeps only the newest whole chunk.

    A reader thread drains rtl_sdr's output all the time, so the dongle
    never drops samples inside a chunk. If analysis falls behind, older
    chunks are thrown away.
    """

    def __init__(self, seconds=5.0, gain_db=20.0, freq=FREQ_12B, device=0):
        self.frames = frames_for(seconds)
        self.read_bytes = (self.frames + 2) * T_FRAME * 2
        cmd = ["rtl_sdr", "-d", str(device), "-f", str(freq), "-s", str(FS),
               "-g", str(gain_db), "-"]
        # stderr goes to a file so a chatty rtl_sdr can't fill a pipe and stall.
        self._err = tempfile.TemporaryFile()
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=self._err)
        self._latest = None
        self._count = 0
        self._taken = 0
        self._cond = threading.Condition()
        self._stop = False
        self.error = None
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        out = self.proc.stdout
        while not self._stop:
            buf = bytearray()
            while len(buf) < self.read_bytes:
                part = out.read(self.read_bytes - len(buf))
                if not part:
                    if self._stop:
                        return
                    self.proc.wait()
                    self._err.seek(0)
                    err = self._err.read().decode(errors="replace")[-400:]
                    with self._cond:
                        self.error = "rtl_sdr stopped: " + err.strip()
                        self._cond.notify_all()
                    return
                buf += part
            with self._cond:
                self._latest = np.frombuffer(bytes(buf), dtype=np.uint8)
                self._count += 1
                self._cond.notify_all()

    def next(self, timeout=30.0):
        """Wait for a chunk newer than the last one taken. None on error."""
        with self._cond:
            self._cond.wait_for(lambda: self._count > self._taken or self.error or self._stop,
                                timeout=timeout)
            if self._count > self._taken:
                self._taken = self._count
                return self._latest
            return None

    def close(self):
        self._stop = True
        if self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        with self._cond:
            self._cond.notify_all()
        # rtl_sdr has exited, so the reader sees the end of the pipe and
        # stops. Wait for it before closing the files it reads.
        self._thread.join(timeout=2)
        if not self._thread.is_alive():
            self.proc.stdout.close()
            self._err.close()
