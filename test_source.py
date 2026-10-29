"""Probe a file, webcam or network stream without exposing URL passwords."""
import argparse
import json
import subprocess
import sys
import time
from source_tools import open_capture, read_capture, resolve_source, redact


def probe(src):
    cap = None
    started = time.monotonic()
    frames = 0
    resolution = None
    error = None
    try:
        cap = open_capture(src)
        if not cap.isOpened():
            raise RuntimeError('OpenCV VideoCapture.isOpened() returned False (backend supplied no exception)')
        opened = time.monotonic()
        for _ in range(30):
            ok, frame = read_capture(cap, src)
            if not ok:
                raise RuntimeError(f'OpenCV VideoCapture.read() returned False after {frames} frames (backend supplied no exception)')
            frames += 1
            resolution = [frame.shape[1], frame.shape[0]]
        elapsed = time.monotonic() - opened
    except Exception as exc:
        error = redact(str(exc))
        elapsed = time.monotonic() - started
    finally:
        if cap is not None: cap.release()
    print(json.dumps(dict(success=error is None, frames=frames, resolution=resolution,
                          measured_fps=round(frames / max(elapsed, 1e-9), 2), error=error)))
    return int(error is not None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', nargs='?')
    parser.add_argument('--source-env')
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return probe(json.loads(sys.stdin.read()))
    if args.source is None and not args.source_env: parser.error('provide a source or --source-env')
    try: src = resolve_source(args.source, args.source_env)
    except ValueError as exc: parser.exit(1, str(exc) + '\n')
    print('Testing:', redact(src), flush=True)
    # Parent watchdog also bounds backends which ignore OpenCV timeout properties.
    try:
        result = subprocess.run([sys.executable, __file__, '--worker'], input=json.dumps(src),
                                text=True, capture_output=True, timeout=10)
        print(redact(result.stdout), end='')
        if result.stderr: print(redact(result.stderr), file=sys.stderr, end='')
        return result.returncode
    except subprocess.TimeoutExpired:
        print('FAILURE: 10-second probe timeout (open/read did not finish); resolution=unknown; measured FPS=unknown')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
