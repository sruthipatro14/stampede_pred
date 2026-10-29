#!/bin/bash
# Staff-only presentation: fixed local data directory; Ctrl+C stops both children.
set -eu
cd "$(dirname "$0")"
exec /opt/anaconda3/bin/python - "$@" <<'PY'
import argparse
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
p = argparse.ArgumentParser()
p.add_argument('--port', type=int, default=8000)
a = p.parse_args()
data = Path('dashboard_data')
if data.is_symlink(): p.error('Refusing to clear a symlink named dashboard_data')
if data.exists(): shutil.rmtree(data)
children = []
def stop(*_): raise KeyboardInterrupt
signal.signal(signal.SIGTERM, stop)
try:
    children.append(subprocess.Popen([sys.executable, '-u', 'monitor.py', '--source', 'demo.mp4',
        '--headless', '--dashboard-dir', 'dashboard_data', '--loop', '--realtime'], start_new_session=True))
    children.append(subprocess.Popen([sys.executable, '-u', 'dashboard.py', '--port', str(a.port)], start_new_session=True))
    while all(c.poll() is None for c in children): time.sleep(.1)
    status = int(any(c.poll() not in (None, 0) for c in children))
except KeyboardInterrupt:
    status = 0
finally:
    for c in children:
        if c.poll() is None: c.send_signal(signal.SIGINT)
    for c in children:
        try: c.wait(timeout=5)
        except subprocess.TimeoutExpired: c.terminate(); c.wait()
raise SystemExit(status)
PY
