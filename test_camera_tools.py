"""Deterministic checks for camera recovery, timing and configuration isolation."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
import numpy as np
import monitor
import source_tools as st


class CameraTests(unittest.TestCase):
    def setUp(self):
        self.cfg = monitor.load_cfg('config.json')

    def test_config_untouched(self):
        current = json.loads(Path('config.json').read_text())
        original = json.loads(Path('config.json.bak').read_text())
        self.assertEqual({k: current[k] for k in original}, original)

    def test_environment_and_redaction(self):
        # Deliberately synthetic credentials; no network request is made.
        with patch.dict('os.environ', {'CAM_TEST': 'rtsp://staff:secret@invalid.test/live'}):
            self.assertEqual(st.resolve_source('${CAM_TEST}'), st.resolve_source('', 'CAM_TEST'))
            self.assertNotIn('secret', st.redact(st.resolve_source('${CAM_TEST}')))
        self.assertEqual(st.resolve_source('0'), 0)
        with self.assertRaises(ValueError): st.resolve_source('${UNSET_CAMERA_TEST_VARIABLE}')

    def test_recovery_and_backoff(self):
        now = [0.0]
        class Cap:
            def __init__(self, good=False): self.good = good
            def read(self): return (True, np.zeros((2, 2, 3), np.uint8)) if self.good else (False, None)
            def release(self): pass
        events, sleeps = [], []
        def sleep(n): now[0] += n; sleeps.append(n)
        with patch.object(st, 'open_capture', side_effect=[Cap(), Cap(), Cap(True)]), \
             patch.object(st.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(st.time, 'sleep', side_effect=sleep):
            cap = st.StreamCapture('demo.mp4', lambda *e: events.append(e), force_network=True)
            self.assertTrue(cap.read()[0])
            self.assertEqual([e[0] for e in events], ['source_lost', 'source_restored'])
            self.assertIn(2, sleeps); self.assertIn(4, sleeps)
            self.assertEqual(cap.generation, 1)

    def test_backoff_cap(self):
        now, sleeps = [0.0], []
        class Cap:
            def read(self): return False, None
            def release(self): pass
        def sleep(n): now[0] += n; sleeps.append(n)
        with patch.object(st, 'open_capture', side_effect=lambda _: Cap()), \
             patch.object(st.time, 'monotonic', side_effect=lambda: now[0]), \
             patch.object(st.time, 'sleep', side_effect=sleep):
            cap = st.StreamCapture('demo.mp4', lambda *_: None, deadline=130, force_network=True)
            self.assertFalse(cap.read()[0])
            self.assertEqual([n for n in sleeps if n >= 2][:6], [2, 4, 8, 16, 30, 30])

    def test_latest_frame_only(self):
        class Cap:
            n = 0
            def get(self, _): return 25
            def read(self):
                if self.n >= 30: return False, None
                self.n += 1
                return True, np.full((2, 2, 3), self.n, np.uint8)
            def release(self): pass
        with patch.object(st, 'open_capture', return_value=Cap()), patch.object(st, 'read_capture', side_effect=lambda c, _: c.read()):
            cap = st.LatestCapture('demo.mp4')
            with cap.condition:
                self.assertTrue(cap.condition.wait_for(lambda: cap.sequence == 30, timeout=2))
            self.assertEqual(int(cap.read()[1][0, 0, 0]), 30)
            cap.release()

    def test_picker_selected_frame(self):
        # Exercise selection and quit handling without claiming a GUI test.
        frames = [np.full((2, 2, 3), n, np.uint8) for n in range(4)]
        with patch.object(monitor, 'open_capture') as opening, \
             patch.object(monitor, 'read_capture', side_effect=[(True, f) for f in frames]), \
             patch.object(monitor.cv2, 'namedWindow'), patch.object(monitor.cv2, 'setMouseCallback'), \
             patch.object(monitor.cv2, 'imshow') as show, \
             patch.object(monitor.cv2, 'waitKey', return_value=ord('q')), \
             patch.object(monitor.cv2, 'destroyAllWindows'):
            monitor.pick_points('scene.mp4', 3)
            self.assertEqual(int(show.call_args.args[1][0, 0, 0]), 3)
            opening.return_value.release.assert_called_once()

    def test_file_eof_no_retry(self):
        class Cap:
            def read(self): return False, None
            def release(self): pass
        with patch.object(st, 'open_capture', return_value=Cap()) as opening:
            cap = st.StreamCapture('demo.mp4', lambda *_: self.fail('file reconnect alert'))
            self.assertFalse(cap.read()[0]); self.assertEqual(opening.call_count, 1)

    def test_elapsed_persistence(self):
        z = monitor.Zone(self.cfg['zones'][0], self.cfg['categories'], (480, 640, 3))
        for t in [0, 3, 6, 9]:
            z.raw.append((t, 4.5)); z.tick(t, self.cfg)
        self.assertEqual(z.level, 1)
        z.raw.append((12, 4.5)); z.tick(12, self.cfg)
        self.assertEqual(z.level, 3)
        self.assertGreaterEqual(z.fcast(60), 0)

    def test_overlap_and_camera_tags(self):
        z = monitor.Zone(self.cfg['zones'][0], self.cfg['categories'], (480, 640, 3))
        out = io.StringIO()
        with contextlib.redirect_stderr(out): monitor.warn_overlaps([z, z])
        self.assertIn('overlap', out.getvalue())
        cfg = copy.deepcopy(self.cfg)
        cfg['cameras'] = [{'name': 'Demo A', 'source': 'demo.mp4', 'zones': cfg['zones'], 'links': cfg['links']}]
        chosen = monitor.select_camera(cfg, 'Demo A')
        with tempfile.TemporaryDirectory() as directory:
            chosen['alert']['log_file'] = str(Path(directory) / 'alerts.jsonl')
            a = monitor.Alerts(chosen)
            for kind in ['source_lost', 'source_restored']:
                now = time.time()
                a.send(kind, 'source', 0, 'test', None, (now, now, now))
            rows = [json.loads(s) for s in Path(chosen['alert']['log_file']).read_text().splitlines()]
            self.assertEqual([r['camera'] for r in rows], ['Demo A', 'Demo A'])


if __name__ == '__main__': unittest.main()
