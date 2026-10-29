"""Staff-only escalation metadata, acknowledgements and webhook delivery."""
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
import time
import urllib.request
import uuid


def read_jsonl(path):
    try:
        with Path(path).open() as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if isinstance(row, dict): yield row
                except ValueError: continue
    except FileNotFoundError: return


def acknowledgements(path):
    result = {}
    for row in read_jsonl(path):
        if isinstance(row.get('alert_id'), str): result.setdefault(row['alert_id'], row)
    return result


def decorate(alert, cfg):
    settings = cfg.get('alerts', {})
    rule = settings.get('escalation', {}).get(str(alert['level']), {})
    alert.update(id=uuid.uuid4().hex, drill=bool(alert.get('drill', False)))
    channels = [c for c in rule.get('channels', ['dashboard', 'webhook', 'staff_message'])
                if settings.get('channels', {}).get(c, c == 'dashboard')]
    alert['channels'] = channels
    alert['repeat_s'] = max(1, float(rule.get('repeat_s', 30))) if rule.get('repeat_until_ack') else None
    alert['staff_message'] = {
        'audience': 'staff', 'drill': alert['drill'], 'label': 'DRILL' if alert['drill'] else 'STAFF ALERT',
        **{k: alert.get(k) for k in ('id', 'camera', 'zone', 'level', 'trigger', 'density', 'eta_to_L4_s')},
        'dashboard': settings.get('dashboard_url', 'http://127.0.0.1:8000/')}
    return alert


def deliver(alert, url, repeat=False):
    if not url or 'webhook' not in alert.get('channels', []): return False
    body = dict(alert, repeated_notification=repeat)
    request = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=3): pass
    return True


def initial_delivery(alert, cfg):
    url = cfg.get('alert', {}).get('webhook_url', '')
    if not url or 'webhook' not in alert.get('channels', []): return
    def work():
        try: deliver(alert, url)
        except Exception as exc: print('[staff webhook failed]', type(exc).__name__, '(URL omitted)', flush=True)
    threading.Thread(target=work, daemon=True).start()


class RepeatNotifications:
    """Owned by dashboard server; repeat existing IDs, never create fake real events."""
    def __init__(self, cfg, log, acks):
        self.cfg, self.log, self.acks = cfg, log, acks
        self.last = {}
        self.stop = threading.Event()

    def tick(self, now=None):
        now = time.time() if now is None else now
        acked = acknowledgements(self.acks)
        for alert in read_jsonl(self.log):
            interval = alert.get('repeat_s')
            aid = alert.get('id')
            if not aid or not interval or aid in acked: continue
            try: created = datetime.fromisoformat(alert['time']).timestamp()
            except (KeyError, ValueError): continue
            if now - self.last.get(aid, created) < interval: continue
            # Check again immediately before dispatch to narrow the ack race.
            if aid in acknowledgements(self.acks): continue
            self.last[aid] = now
            camera = next((c for c in self.cfg.get('cameras', []) if c.get('name')==alert.get('camera')), {})
            settings = {**self.cfg, **camera}
            if not settings.get('alerts', {}).get('channels', {}).get('webhook', True): continue
            try: deliver(alert, settings.get('alert', {}).get('webhook_url', ''), repeat=True)
            except Exception as exc: print('[staff repeat failed]', type(exc).__name__, '(URL omitted)', flush=True)

    def run(self):
        while not self.stop.wait(1): self.tick()
