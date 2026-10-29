#!/bin/bash
# One independent monitor process per configured camera; Ctrl+C stops the group.
set -u
cd "$(dirname "$0")" || exit 1
exec /opt/anaconda3/bin/python - "$@" <<'PY'
import argparse
import signal
import subprocess
import sys
import time
from monitor import load_cfg
p = argparse.ArgumentParser()
p.add_argument('--config', default='config.json')
a, extra = p.parse_known_args()
if any(x.split('=')[0] in ('--camera', '--config') for x in extra):
    p.error('camera selection is managed by run_all.sh')
cfg = load_cfg(a.config)
cameras = cfg.get('cameras')
names = [c['name'] for c in cameras] if cameras else [None]
if len(set(names)) != len(names): p.error('camera names must be unique')
children = []
def stop(*_):
    raise KeyboardInterrupt
signal.signal(signal.SIGTERM, stop)
try:
    for name in names:
        cmd = [sys.executable, '-u', 'monitor.py', '--config', a.config]
        if not any(x.split('=')[0] == '--dashboard-dir' for x in extra):
            cmd += ['--dashboard-dir', 'dashboard_data']
        if name is not None: cmd += ['--camera', name]
        children.append(subprocess.Popen(cmd + extra))
    while any(c.poll() is None for c in children):
        if any(c.poll() not in (None, 0) for c in children):
            break
        time.sleep(0.1)
    status = int(any(c.poll() not in (None, 0) for c in children))
except KeyboardInterrupt:
    status = 130
finally:
    for c in children:
        if c.poll() is None: c.terminate()
    for c in children:
        try: c.wait(timeout=12)
        except subprocess.TimeoutExpired: c.kill(); c.wait()
raise SystemExit(status)
PY
