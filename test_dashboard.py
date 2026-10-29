"""Local dashboard file and HTTP checks, without a browser or camera."""
import json
import io
from types import SimpleNamespace
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
import cv2
import numpy as np
from dashboard_output import DashboardOutput
from dashboard import alert_tail, make_handler


class DashboardTests(unittest.TestCase):
    def test_ring_atomic_and_nonblocking_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            output = DashboardOutput(directory, 'Demo camera', lambda frame, status: None)
            state = {'zones': [{'name': 'Zone', 'density': 2.0, 'level': 2}], 'video_s': 0}
            for i in range(650):
                state['video_s'] = i
                output.publish(state, sample=True, force=i == 649)
            output.close()
            history = json.loads((output.path / 'history.json').read_text())
            self.assertEqual(len(history), 600)
            self.assertEqual(history[-1]['video_s'], 649)
            self.assertFalse(list(output.path.glob('.*')))
            blocked = Path(directory) / 'file'
            blocked.write_text('not a directory')
            failed = DashboardOutput(blocked, 'default', lambda *_: None)
            failed.publish(state, force=True)
            failed.close()
            self.assertTrue(failed.failed)

    def test_alert_tail_malformed(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'alerts.jsonl'
            p.write_text('{"kind":"first"}\ninvalid JSON\n[]\n{"kind":"last"}\n')
            self.assertEqual([r['kind'] for r in alert_tail(p, 50)], ['last', 'first'])

    def test_routes_without_network(self):
        class Connection:
            def __init__(self, route):
                self.request = io.BytesIO(('GET ' + route + ' HTTP/1.0\r\nHost: localhost\r\n\r\n').encode())
                self.response = bytearray()
            def makefile(self, *_): return self.request
            def sendall(self, data): self.response.extend(data)
        handler = make_handler('dashboard_data', 'alerts.jsonl')
        def request(route):
            connection = Connection(route)
            handler(connection, ('127.0.0.1', 0), SimpleNamespace())
            headers, body = bytes(connection.response).split(b'\r\n\r\n', 1)
            return int(headers.split()[1]), headers, body
        for route in ['/', '/api/cameras', '/api/status/default', '/api/history/default', '/api/alerts?limit=50', '/frame/default.jpg']:
            code, headers, body = request(route)
            self.assertEqual(code, 200, route)
            self.assertIn(b'no-store', headers)
            if route.startswith('/api/'): json.loads(body)
            if route.endswith('.jpg'):
                self.assertIsNotNone(cv2.imdecode(np.frombuffer(body, np.uint8), cv2.IMREAD_COLOR))
            print('PASS direct handler:', route, code)
        for route in ['/frame/../config.json', '/config.json', '/api/status/%2e%2e', '/frame/%2e%2e%2fconfig.json', '/source_tools.py']:
            self.assertIn(request(route)[0], (400, 404), route)
        self.assertEqual(request('/api/alerts?limit=bad')[0], 400)



def integration():
    # Observe the running 20-second real-time demo before testing HTTP routes.
    path = Path('dashboard_data/default/history.json')
    start = time.monotonic()
    initial = None
    while time.monotonic() - start < 8:
        if path.exists():
            count = len(json.loads(path.read_text()))
            if initial is None: initial = count
            if count > initial:
                print('PASS history grows:', initial, '->', count, flush=True)
                break
        time.sleep(.1)
    else: print('History growth not observed during this interval', flush=True)
    with open('dashboard-http-test.log', 'w') as log:
        server = subprocess.Popen(['/opt/anaconda3/bin/python', '-u', 'dashboard.py'], stdout=log, stderr=subprocess.STDOUT)
        try:
            base = 'http://127.0.0.1:8000'
            for _ in range(50):
                if server.poll() is not None:
                    raise RuntimeError(Path('dashboard-http-test.log').read_text())
                try:
                    with urlopen(base + '/api/cameras', timeout=1) as r: cameras = json.load(r)
                    break
                except URLError: time.sleep(.1)
            else: raise RuntimeError('dashboard server did not become ready')
            assert any(c['id'] == 'default' for c in cameras)
            for route in ['/', '/api/cameras', '/api/status/default', '/api/history/default', '/api/alerts?limit=50', '/frame/default.jpg']:
                with urlopen(base + route, timeout=2) as response:
                    data = response.read()
                    assert 'no-store' in response.headers['Cache-Control']
                    if route.startswith('/api/'): json.loads(data)
                    if route.endswith('.jpg'):
                        assert data.startswith(b'\xff\xd8')
                        assert cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR) is not None
                    print('PASS HTTP', route, response.status, len(data), 'bytes', flush=True)
            with urlopen(base + '/api/alerts?limit=50') as r:
                alerts = json.load(r)
                assert alerts and alerts[0]['time'] == json.loads(Path('alerts.jsonl').read_text().splitlines()[-1])['time']
            for route in ['/frame/../config.json', '/config.json', '/source_tools.py', '/api/status/%2e%2e', '/frame/%2e%2e%2fconfig.json']:
                try: urlopen(base + route, timeout=2)
                except HTTPError as e:
                    assert e.code in (400,404)
                    print('PASS blocked', route, e.code, flush=True)
                else: raise AssertionError('Unexpected accessible path: ' + route)
        finally:
            if server.poll() is None: server.terminate()
            server.wait(timeout=5)


if __name__ == '__main__':
    import sys
    if '--integration' in sys.argv: integration()
    else: unittest.main()
