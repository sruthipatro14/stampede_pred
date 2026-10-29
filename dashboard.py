"""Offline, staff-only dashboard. Serve only explicit routes, never project files."""
import argparse
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import hmac
import threading
from datetime import datetime, timezone
from alert_workflow import acknowledgements, read_jsonl, RepeatNotifications
from urllib.parse import parse_qs, unquote, urlsplit


def clean(value):
    if isinstance(value, str):
        return re.sub(r'(?i)\b(?:rtsp|https?)://[^\s]+', '[URL omitted]', value)
    if isinstance(value, list): return [clean(v) for v in value]
    if isinstance(value, dict): return {k: clean(v) for k, v in value.items() if k not in ('source', 'url', 'webhook_url')}
    return value


def alert_tail(path, limit):
    # Scan backwards without loading an unbounded staff alert log into memory.
    records, remainder = [], b''
    try:
        with path.open('rb') as f:
            f.seek(0, 2); position = f.tell()
            while position > 0 and len(records) < limit:
                count = min(position, 8192); position -= count; f.seek(position)
                lines = (f.read(count) + remainder).split(b'\n')
                remainder = lines.pop(0)
                if position == 0: lines.insert(0, remainder); remainder = b''
                for line in reversed(lines):
                    try:
                        row = json.loads(line)
                        if not isinstance(row, dict): continue
                        allowed = ('time', 'camera', 'kind', 'zone', 'level', 'trigger', 'eta_to_L4_s',
                                   'stages', 'within_3s_budget', 'density', 'category', 'thresholds',
                                   'id', 'drill', 'channels', 'repeat_s', 'staff_message', 'density_level',
                                   'persistent_level', 'forecast_levels', 'forecast_30', 'forecast_60', 'forecast_120', 'sample_video_s', 'eta_state')
                        records.append(clean({k: row[k] for k in allowed if k in row}))
                        if len(records) >= limit: break
                    except (ValueError, UnicodeError): continue
    except FileNotFoundError: pass
    return records


def make_handler(data_root, alerts_path, acks_path="acks.jsonl", token=None):
    ack_lock = threading.Lock()
    root = Path(data_root).resolve()
    index = Path(__file__).with_name('dashboard') / 'index.html'
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_): pass  # Never echo query strings or credentials.

        def respond(self, body, content='application/json', code=200):
            self.send_response(code)
            self.send_header('Content-Type', content)
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store, max-age=0')
            self.send_header('X-Content-Type-Options', 'nosniff')
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def json(self, value, code=200):
            self.respond(json.dumps(clean(value), allow_nan=False).encode(), code=code)

        def camera_dirs(self):
            if not root.is_dir(): return {}
            return {p.name: p for p in root.iterdir() if p.is_dir() and not p.is_symlink()
                    and re.fullmatch(r'[A-Za-z0-9_-]+', p.name)}

        def camera_file(self, camera, filename):
            directory = self.camera_dirs().get(camera)
            if directory is None: raise FileNotFoundError
            path = directory / filename
            if path.is_symlink() or path.resolve().parent != directory.resolve(): raise FileNotFoundError
            return path

        def do_POST(self):
            if self.path != '/api/ack': return self.json({'error': 'not found'}, 404)
            supplied = self.headers.get('Authorization', '')
            if token:
                if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
                    return self.json({'error': 'staff token required'}, 403)
            elif self.client_address[0] != '127.0.0.1':
                return self.json({'error': 'local staff access required'}, 403)
            if not token and urlsplit('http://' + self.headers.get('Host','')).hostname not in ('127.0.0.1','localhost'):
                return self.json({'error':'local Host required'},403)
            origin = self.headers.get('Origin')
            if self.headers.get('Sec-Fetch-Site') == 'cross-site' or (origin and urlsplit(origin).netloc != self.headers.get('Host')):
                return self.json({'error': 'cross-origin request denied'}, 403)
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if not 0 < length <= 4096 or self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    return self.json({'error': 'small JSON body required'}, 400)
                body = json.loads(self.rfile.read(length))
                if not isinstance(body, dict): raise ValueError
                aid, staff = body.get('alert_id'), body.get('staff')
                if not isinstance(aid, str) or not re.fullmatch(r'[a-f0-9]{32}', aid): raise ValueError
                if not isinstance(staff, str) or not re.fullmatch(r"[\w .'-]{1,80}", staff.strip()) or not staff.strip(): raise ValueError
                alert = next((a for a in read_jsonl(alerts_path) if a.get('id') == aid), None)
                if alert is None: return self.json({'error': 'unknown alert id'}, 404)
                with ack_lock:
                    existing = acknowledgements(acks_path).get(aid)
                    if existing: return self.json(existing)
                    ack = {'alert_id': aid, 'staff': staff.strip(), 'timestamp': datetime.now(timezone.utc).isoformat(),
                           'drill': bool(alert.get('drill', False))}
                    with Path(acks_path).open('a') as f: f.write(json.dumps(ack) + '\n')
                return self.json(ack)
            except (ValueError, TypeError, UnicodeError): return self.json({'error': 'invalid acknowledgement'}, 400)
            except OSError: return self.json({'error': 'acknowledgement could not be stored'}, 503)

        def do_GET(self):
            try:
                url = urlsplit(self.path); path = unquote(url.path)
                if any(part in ('.', '..') for part in path.split('/')) or '\\' in path:
                    return self.json({'error': 'invalid path'}, 400)
                if path == '/': return self.respond(index.read_bytes(), 'text/html; charset=utf-8')
                if path == '/api/cameras':
                    cameras = []
                    for name in sorted(self.camera_dirs()):
                        try:
                            status = json.loads(self.camera_file(name, 'status.json').read_text())
                            cameras.append({'id': name, 'name': status.get('camera', name)})
                        except (OSError, ValueError): continue
                    return self.json(cameras)
                if path == '/api/alerts':
                    limit = int(parse_qs(url.query).get('limit', ['50'])[0])
                    rows = alert_tail(Path(alerts_path), max(1, min(limit, 500)))
                    acked = acknowledgements(acks_path)
                    for row in rows: row['acknowledgement'] = acked.get(row.get('id'))
                    return self.json(rows)
                match = re.fullmatch(r'/api/(status|history)/([A-Za-z0-9_-]+)', path)
                if match:
                    return self.json(json.loads(self.camera_file(match[2], match[1] + '.json').read_text()))
                match = re.fullmatch(r'/frame/([A-Za-z0-9_-]+)\.jpg', path)
                if match: return self.respond(self.camera_file(match[1], 'frame.jpg').read_bytes(), 'image/jpeg')
                self.json({'error': 'not found'}, 404)
            except FileNotFoundError: self.json({'error': 'not found'}, 404)
            except (ValueError, UnicodeError): self.json({'error': 'invalid request or unavailable data'}, 400)
            except OSError: self.json({'error': 'data unavailable'}, 503)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--dashboard-dir', default='dashboard_data')
    parser.add_argument('--alerts', default='alerts.jsonl')
    parser.add_argument('--acks', default=None)
    parser.add_argument('--config', default='config.json')
    parser.add_argument('--token', default=None, help='require this bearer token for all acknowledgements')
    args = parser.parse_args()
    cfg = json.loads(Path(args.config).read_text())
    acks_path = args.acks or cfg.get('alerts', {}).get('acks_file', 'acks.jsonl')
    if args.host != '127.0.0.1':
        print('WARNING: Staff only. Binding beyond 127.0.0.1 can expose camera images. Do not expose this port publicly.', flush=True)
    try:
        server = ThreadingHTTPServer((args.host, args.port), make_handler(args.dashboard_dir, args.alerts, acks_path, args.token))
    except OSError as exc:
        parser.exit(1, f"Cannot start dashboard: {type(exc).__name__}: {exc}\n")
    repeats = RepeatNotifications(cfg, args.alerts, acks_path)
    worker = threading.Thread(target=repeats.run, daemon=True); worker.start()
    print(f'Staff dashboard: http://{args.host}:{server.server_port}', flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally:
        repeats.stop.set(); worker.join(timeout=4); server.server_close()


if __name__ == '__main__': main()
