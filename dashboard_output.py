"""Optional bounded, asynchronous dashboard output. No source URLs are exported."""
from collections import deque
from datetime import datetime, timezone
from pathlib import Path
import base64
import math
import hashlib
import json
import os
import queue
import re
import tempfile
import threading
import time
import cv2


def camera_directory(name):
    if re.fullmatch(r'[A-Za-z0-9_-]+', name): return name
    return 'camera-' + hashlib.sha256(name.encode()).hexdigest()[:16]


def finite_json(value):
    if isinstance(value, float) and not math.isfinite(value): return None
    if isinstance(value, dict): return {k: finite_json(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)): return [finite_json(v) for v in value]
    return value


class DashboardOutput:
    def __init__(self, root, camera, render):
        self.path = Path(root) / camera_directory(camera)
        self.camera, self.render = camera, render
        self.pending = queue.Queue(maxsize=1)
        self.history = deque(maxlen=600)
        self.last_image = 0
        self.failed = False
        self.closed = False
        self.worker = threading.Thread(target=self._run, daemon=True)
        self.worker.start()

    def publish(self, status, frame=None, sample=False, force=False):
        try:
            if self.closed: return
            status = finite_json(dict(status, timestamp=datetime.now(timezone.utc).isoformat(), camera=self.camera))
            if sample:
                self.history.append({'timestamp': status['timestamp'], 'video_s': status.get('video_s'),
                                     'zones': [{'name': z['name'], 'density': z['density'], 'level': z['level']}
                                               for z in status['zones']]})
            now = time.monotonic()
            image = None
            if frame is not None and now - self.last_image >= .2:
                image = frame.copy()
                self.last_image = now
            item = (status, image, list(self.history), force)
            try: self.pending.put_nowait(item)
            except queue.Full:
                try: old = self.pending.get_nowait()
                except queue.Empty: old = None
                if image is None and old is not None: item = (status, None, item[2], force or old[3])
                try: self.pending.put_nowait(item)
                except queue.Full: pass
        except Exception as exc:
            self._warn(exc)

    def _warn(self, error=None):
        if not self.failed:
            print('[dashboard] output failed; continuing monitor (further warnings suppressed): ' + (type(error).__name__ + ': ' + str(error) if error else 'snapshot error'), flush=True)
            self.failed = True

    def _atomic(self, name, data):
        self.path.mkdir(parents=True, exist_ok=True)
        temp = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.path, prefix='.', delete=False) as f:
                temp = f.name
                f.write(data)
            os.replace(temp, self.path / name)
        finally:
            if temp is not None:
                try: os.unlink(temp)
                except FileNotFoundError: pass

    def _run(self):
        last_history = last_jpeg = 0
        last_visual = None
        while not self.closed or not self.pending.empty():
            try: status, frame, history, force = self.pending.get(timeout=.1)
            except queue.Empty: continue
            try:
                # Publish the image and its analysis in one atomic JSON document.
                now = time.monotonic()
                if frame is not None and now - last_jpeg >= .2:
                    self.render(frame, status)
                    ok, jpg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
                    if not ok: raise OSError('JPEG encoding failed')
                    self._atomic('frame.jpg', jpg.tobytes())
                    status['frame_data'] = 'data:image/jpeg;base64,' + base64.b64encode(jpg.tobytes()).decode()
                    last_jpeg = now
                    last_visual = (status['frame_data'], status['zones'])
                if last_visual is not None and status.get('source_status') == 'live':
                    status['frame_data'], status['zones'] = last_visual
                self._atomic('status.json', json.dumps(status, allow_nan=False).encode())
                if force or now - last_history >= 1:
                    self._atomic('history.json', json.dumps(history, allow_nan=False).encode())
                    last_history = now
            except Exception as exc:
                self._warn(exc)

    def close(self):
        self.closed = True
        self.worker.join(timeout=.75)
