"""Shared source parsing and bounded network capture, with credential-safe diagnostics."""
import contextlib
import os
import re
import time
import threading
import cv2


def network_source(src):
    return isinstance(src, str) and src.lower().startswith(('rtsp://', 'http://', 'https://'))


def redact(value):
    return re.sub(r'(?i)([a-z]+://)([^\s/]+)@',
                  lambda m: m[1] + m[2].split(':', 1)[0] + ':****@', str(value))


def resolve_source(value, env=None):
    if env:
        if env not in os.environ:
            raise ValueError(f'Environment variable {env} is not set')
        value = os.environ[env]
    def replace(match):
        name = match[1]
        if name not in os.environ:
            raise ValueError(f'Environment variable {name} is not set')
        return os.environ[name]
    value = re.sub(r'\$\{([A-Za-z_][A-Za-z0-9_]*)\}', replace, str(value))
    return int(value) if value.isdigit() else value


@contextlib.contextmanager
def quiet_backend(enabled):
    # FFmpeg may print raw credential-bearing URLs directly to fd 2.
    # Suppress native output for network operations; report safe errors ourselves.
    if not enabled:
        yield
        return
    saved = os.dup(2)
    try:
        with open(os.devnull, 'w') as sink:
            os.dup2(sink.fileno(), 2)
            yield
    finally:
        os.dup2(saved, 2)
        os.close(saved)


def open_capture(src):
    net = network_source(src)
    if isinstance(src, str) and src.lower().startswith('rtsp://'):
        os.environ['OPENCV_FFMPEG_CAPTURE_OPTIONS'] = 'rtsp_transport;tcp'
    with quiet_backend(net):
        if net:
            cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 10000,
                                    cv2.CAP_PROP_READ_TIMEOUT_MSEC, 1000])
        else:
            cap = cv2.VideoCapture(src)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    return cap


def read_capture(cap, src):
    with quiet_backend(network_source(src)):
        return cap.read()


class LatestCapture:
    """Drain network frames continuously; retain only the newest decoded frame."""
    def __init__(self, src):
        self.src = src
        self.cap = open_capture(src)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS)
        self.condition = threading.Condition()
        self.stopped = False
        self.frame = None
        self.sequence = 0
        self.delivered = 0
        self.worker = threading.Thread(target=self._drain, daemon=True)
        self.worker.start()

    def _drain(self):
        try:
            while not self.stopped:
                try:
                    ok, frame = read_capture(self.cap, self.src)
                except cv2.error:
                    ok, frame = False, None
                with self.condition:
                    if ok:
                        self.frame = frame
                        self.sequence += 1
                    self.condition.notify_all()
                if not ok:
                    time.sleep(0.05)
        finally:
            self.cap.release()

    def read(self):
        with self.condition:
            self.condition.wait_for(lambda: self.sequence > self.delivered or self.stopped, timeout=1)
            if self.sequence <= self.delivered:
                return False, None
            self.delivered = self.sequence
            return True, self.frame

    def get(self, prop):
        return self.fps if prop == cv2.CAP_PROP_FPS else 0

    def release(self):
        self.stopped = True
        self.worker.join(timeout=2)
        # The worker releases its own capture, never concurrently with read().



class StreamCapture:
    """Retry network failures only; files retain normal EOF semantics."""
    def __init__(self, src, notify, deadline=None, force_network=False, state_changed=None):
        self.src, self.notify, self.deadline = src, notify, deadline
        self.state_changed = state_changed or (lambda state: None)
        self.network = network_source(src) or force_network
        self.cap = LatestCapture(src) if network_source(src) else open_capture(src)
        self.generation = 0
        self.lost = False

    def expired(self):
        return self.deadline is not None and time.monotonic() >= self.deadline

    def pause(self, seconds):
        if self.deadline is not None:
            seconds = min(seconds, max(0, self.deadline - time.monotonic()))
        time.sleep(seconds)

    def read(self):
        failed_since = None
        delay = 2
        while not self.expired():
            ok, frame = self.cap.read() if isinstance(self.cap, LatestCapture) else read_capture(self.cap, self.src)
            if ok:
                if self.lost:
                    self.notify('source_restored', 'frames available again')
                    self.state_changed('live')
                    self.generation += 1
                    self.lost = False
                return ok, frame
            if not self.network:
                return False, None
            if failed_since is None:
                failed_since = time.monotonic()
            if time.monotonic() - failed_since < 5:
                self.pause(0.1)
                continue
            if not self.lost:
                self.notify('source_lost', 'no readable frames for 5 seconds')
                self.state_changed('lost')
                self.lost = True
            self.cap.release()
            self.state_changed('reconnecting')
            print(f'[source] reconnect {redact(self.src)} in {delay}s', flush=True)
            self.pause(delay)
            if self.expired():
                break
            print(f'[source] reopening {redact(self.src)}', flush=True)
            self.cap = LatestCapture(self.src) if network_source(self.src) else open_capture(self.src)
            delay = min(delay * 2, 30)
        return False, None

    def release(self):
        self.cap.release()
