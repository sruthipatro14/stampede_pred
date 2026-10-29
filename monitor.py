#!/usr/bin/env python3
"""Camera -> people density -> threshold levels -> forecast -> bottlenecks -> staff alerts.
Alerts go to STAFF channels only (console, JSONL, optional webhook such as an n8n Webhook node).
Nothing here produces any public announcement."""
import argparse, json, math, sys, threading, time, urllib.request
from collections import deque
from datetime import datetime, timezone
import cv2, numpy as np
from source_tools import StreamCapture, open_capture, read_capture, resolve_source, redact

def load_cfg(path):
    with open(path) as f: cfg = json.load(f)
    for n, c in cfg["categories"].items():
        t = c["thresholds"]
        if not (t[0] < t[1] < t[2]):
            sys.exit(f"Invalid thresholds for '{n}': must be strictly increasing, got {t}")
    return cfg

def poly_area(pts):
    x, y = np.array(pts, float).T
    return float(0.5 * abs(np.dot(x, np.roll(y, 1)) - np.dot(y, np.roll(x, 1))))

class Zone:
    def __init__(s, z, cats, shape):
        s.name, s.catname = z["name"], z["category"]; s.cat = cats[s.catname]
        s.poly = np.array(z["image_polygon"], np.int32)
        s.area = poly_area(z["world_polygon_m"]); s.width = z["width_m"]
        s.axis = math.radians(z.get("flow_axis_deg", 0)); s.ppp = z.get("fg_px_per_person", 200)
        s.mask = np.zeros(shape[:2], np.uint8); cv2.fillPoly(s.mask, [s.poly], 255)
        s.m_per_px = math.sqrt(s.area / max(1, cv2.countNonZero(s.mask)))
        s.raw = deque(maxlen=300); s.hist = deque(maxlen=150); s.hist_times = deque(maxlen=150); s.last_tick = None; s.rise_since = None; s.stall_since = None
        s.level = 1; s.cnt = 0; s.stall = 0; s.eff = 1; s.why = "current"
        s.speed = None; s.counter = 0.0; s.d = 0.0; s.eta = None; s.fc60 = 0.0
    th = property(lambda s: s.cat["thresholds"])
    def lv(s, d): return sum(d >= x for x in s.th) + 1 if d is not None and math.isfinite(d) else None
    def sensed(s, t_ref):
        v = [d for (t, d) in s.raw if t <= t_ref]
        return v[-1] if v else (s.raw[0][1] if s.raw else 0.0)   # reuse previous valid reading
    def fcast(s, h):
        H = list(s.hist); T = list(s.hist_times); cur = H[-1]
        j = next((i for i, t in enumerate(T) if t >= T[-1] - 15), len(T) - 1)
        dt = T[-1] - T[j]
        sl = (cur - H[j]) / dt if dt > 0 else 0.0
        return max(0.0, cur + sl * 40 * (1 - math.exp(-h / 40)))
    def eta_l4(s):
        if s.hist[-1] >= s.th[2]: return 0
        return next((h for h in range(5, 121, 5) if s.fcast(h) >= s.th[2]), None)
    def tick(s, t, cfg):
        o = cfg["overrides"]; d = s.sensed(t - cfg["sensor_delay_s"]); s.hist.append(d); s.hist_times.append(t); s.d = d; s.last_tick = t
        c = s.lv(d)
        if c > s.level:
            if s.rise_since is None: s.rise_since = t
            if t - s.rise_since >= cfg["persistence_s"]: s.level, s.rise_since = c, None
        else:
            s.rise_since = None
            if s.level > 1 and d < s.th[s.level - 2] - cfg["hysteresis"]: s.level -= 1
        stalled = d >= s.cat["stall_density"] and s.speed is not None and s.speed <= o["stall_speed"]
        if stalled:
            if s.stall_since is None: s.stall_since = t
        else: s.stall_since = None
        s.stall = t - s.stall_since if s.stall_since is not None else 0
        e, why = s.level, "current"
        s.fc60 = s.fcast(60)
        if s.lv(s.fc60) >= 4 and e < 3: e, why = 3, "forecast +60s"
        if s.lv(s.fcast(120)) >= 3 and e < 2: e, why = 2, "forecast +120s"
        if s.stall >= o["stall_secs"]: e, why = 4, "override: stalled crowd"
        if d > o["packed_density"]: e, why = 4, "override: packed crowd"
        s.eff, s.why, s.eta = e, why, s.eta_l4()

class FgEstimator:   # EXPERIMENTAL: foreground area / calibrated pixels-per-person. Needs a static camera.
    def __init__(s, cfg):
        s.bg = cv2.createBackgroundSubtractorMOG2(300, 25, False); s.n = 0; s.w = cfg["bg_warmup_frames"]; s.started = None
        s.k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    def process(s, frame, zones, t=None, fps=25):
        if s.started is None: s.started = t
        warming = s.n < s.w if t is None else t - s.started < s.w / fps
        fg = s.bg.apply(frame, learningRate=-1 if warming else 0.0); s.n += 1
        if warming: return None, None
        fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, s.k)
        return [cv2.countNonZero(cv2.bitwise_and(fg, z.mask)) / z.ppp for z in zones], fg

class YoloEstimator:  # person detector; counts foot points inside each zone. Degrades when heavily occluded.
    def __init__(s, cfg):
        from ultralytics import YOLO
        s.m, s.conf = YOLO(cfg["yolo_model"]), cfg["yolo_conf"]
    def process(s, frame, zones, t=None, fps=25):
        r = s.m(frame, classes=[0], conf=s.conf, verbose=False)[0]
        occ = np.zeros(frame.shape[:2], np.uint8); pts = []
        for x1, y1, x2, y2 in r.boxes.xyxy.cpu().numpy().astype(int):
            cv2.rectangle(occ, (x1, y1), (x2, y2), 255, -1); pts.append(((x1 + x2) / 2.0, float(y2)))
        return [sum(cv2.pointPolygonTest(z.poly, p, False) >= 0 for p in pts) for z in zones], occ

def flow_stats(prev, cur, occ, zones, dt, scale):
    fl = cv2.calcOpticalFlowFarneback(prev, cur, None, 0.5, 3, 21, 3, 5, 1.1, 0)
    occs = cv2.resize(occ, (cur.shape[1], cur.shape[0]), interpolation=cv2.INTER_NEAREST)
    for z in zones:
        zm = cv2.resize(z.mask, (cur.shape[1], cur.shape[0]), interpolation=cv2.INTER_NEAREST)
        sel = (zm > 0) & (occs > 0)
        if sel.sum() < 30: z.speed, z.counter = None, 0.0; continue
        fx, fy = fl[..., 0][sel] * scale, fl[..., 1][sel] * scale
        z.speed = float(np.hypot(fx, fy).mean() * z.m_per_px / dt)
        proj = fx * math.cos(z.axis) + fy * math.sin(z.axis); thr = 0.5
        pos, neg = int((proj > thr).sum()), int((proj < -thr).sum())
        z.counter = min(pos, neg) / (pos + neg) if pos + neg >= 50 else 0.0

def bottlenecks(zmap, cfg, include_all=False):
    out = []
    for up, dn in cfg["links"]:
        a, b = zmap[up], zmap[dn]; w = min(a.width, b.width)
        cap = b.cat["capacity_per_m_min"] / 60 * w
        v = b.speed if b.speed is not None else b.cat["free_speed"]
        flow = b.d * v * b.width                                  # fundamental relation J = density x speed x width
        H = list(a.hist); T = list(a.hist_times)
        j = next((i for i, t in enumerate(T) if t >= T[-1] - 10), 0) if T else 0
        sl = (H[-1] - H[j]) / (T[-1] - T[j]) if len(T) > 1 and T[-1] > T[j] else 0.0
        c = {"width_ratio>1.5": max(a.width, b.width) / w > 1.5, "flow>85%cap": flow > 0.85 * cap,
             "queue_growing_flow_flat": sl > 0.03 and flow <= cap,
             "speed<0.5": b.speed is not None and b.speed < 0.5 and b.d > 1.0,
             "counterflow": max(a.counter, b.counter) > cfg["counterflow_ratio"]}
        hit = [k for k, v_ in c.items() if v_]
        if include_all or len(hit) >= 2: out.append({"link": f"{up}->{dn}", "conditions": hit, "flagged": len(hit) >= 2})
    return out

class Alerts:   # STAFF channels only
    def __init__(s, cfg): s.c = cfg["alert"]; s.last = {}; s.camera = cfg.get("camera_name", "default"); s.settings = cfg.get("alerts", {})
    def send(s, kind, zone, level, why, eta, ts, extra=None):
        key = (kind, zone, level, why); now = time.monotonic()
        if kind not in ("source_lost", "source_restored") and now - s.last.get(key, 0) < s.c["cooldown_s"]: return
        s.last[key] = now; t_out = time.time()
        st = {"video_s": round(ts[1] - ts[0], 3), "backend_s": round(ts[2] - ts[1], 3), "dispatch_s": round(t_out - ts[2], 3)}
        a = {"time": datetime.now(timezone.utc).isoformat(), "camera": s.camera, "kind": kind, "zone": zone, "level": level, "trigger": why,
             "eta_to_L4_s": eta, "stages": st, "within_3s_budget": sum(st.values()) <= 3.0, **(extra or {})}
        from alert_workflow import decorate, initial_delivery
        a = decorate(a, {'alert': s.c, 'alerts': s.settings})
        label = 'DRILL ' if a['drill'] else ''
        print(f"[ALERT] {label}[{s.camera}] {kind} L{level} {zone}: {why} eta={eta} stages={st}", flush=True)
        with open(s.c["log_file"], "a") as f: f.write(json.dumps(a, default=lambda o: o.item() if hasattr(o, "item") else str(o)) + "\n")
        initial_delivery(a, {'alert': s.c, 'alerts': s.settings})

COL = {1: (80, 170, 80), 2: (60, 210, 240), 3: (40, 150, 240), 4: (50, 50, 230)}
def draw(frame, zones, bn):
    # Labels occupy separate rows on a dark rail; polygons retain source coordinates.
    h, w = frame.shape[:2]
    for i, z in enumerate(zones):
        color = COL.get(z.eff, (150, 150, 150))
        ov = frame.copy(); cv2.fillPoly(ov, [z.poly], color)
        cv2.addWeighted(ov, .12, frame, .88, 0, frame)
        cv2.polylines(frame, [z.poly], True, color, 2)
        valid = z.d is not None and math.isfinite(z.d) and getattr(z, 'data_available', True)
        text = f"{z.name} | Effective L{z.eff} | {z.d:.1f}/m2" if valid and z.eff else f"{z.name} | Unavailable"
        scale = min(.55, max(.2, (w - 16) / max(1, cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 1, 1)[0][0])))
        y = 22 + i * 26
        if y >= h - 4: break
        cv2.rectangle(frame, (0, y-19), (w, y+5), (18, 25, 32), -1)
        cv2.putText(frame, text, (8, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, 1, cv2.LINE_AA)

def pick_points(src, frame_index=0):
    cap = open_capture(src); ok, f = False, None; pts = []
    for _ in range(frame_index + 1):
        ok, f = read_capture(cap, src)
        if not ok: break
    cap.release()
    if not ok: sys.exit("cannot read source")
    def cb(e, x, y, *_):
        if e == cv2.EVENT_LBUTTONDOWN: pts.append([x, y]); cv2.circle(f, (x, y), 4, (0, 0, 255), -1)
    cv2.namedWindow("pick"); cv2.setMouseCallback("pick", cb)
    print("Click polygon corners. Press p to print, q to quit.")
    while True:
        cv2.imshow("pick", f); k = cv2.waitKey(30) & 255
        if k == ord("p"): print(json.dumps(pts))
        if k == ord("q"): break
    cv2.destroyAllWindows()

def select_camera(cfg, name=None):
    cameras = cfg.get("cameras")
    if not cameras:
        if name: sys.exit("--camera requires a cameras list")
        return {**cfg, "camera_name": "default"}
    for camera in cameras:
        if not all(key in camera for key in ("name", "source", "zones", "links")):
            sys.exit("Each camera requires name, source, zones and links")
        zone_names = [z["name"] for z in camera["zones"]]
        if not zone_names or len(set(zone_names)) != len(zone_names):
            sys.exit("Camera zones must have unique names and cannot be empty")
        if any(z["category"] not in cfg["categories"] for z in camera["zones"]):
            sys.exit("Unknown zone category in camera " + camera["name"])
        if any(up not in zone_names or dn not in zone_names for up, dn in camera["links"]):
            sys.exit("Camera links must reference its own zones")
    names = [c["name"] for c in cameras]
    if len(set(names)) != len(names): sys.exit("Camera names must be unique")
    if name is None and len(cameras) != 1: sys.exit("Choose --camera from: " + ", ".join(names))
    chosen = next((c for c in cameras if c["name"] == (name or names[0])), None)
    if chosen is None: sys.exit("Unknown camera: " + str(name))
    return {**cfg, **chosen, "camera_name": chosen["name"]}

def warn_overlaps(zones):
    for i, a in enumerate(zones):
        for b in zones[i + 1:]:
            if cv2.countNonZero(cv2.bitwise_and(a.mask, b.mask)):
                print(f"[WARNING] zones {a.name} and {b.name} overlap; people may be counted twice", file=sys.stderr)

def zone_snapshot(z, cfg):
    if hasattr(z, 'display_sample') and getattr(z, 'data_available', True): return dict(z.display_sample)
    valid = bool(z.hist) and math.isfinite(z.d) and getattr(z, 'data_available', True)
    ready = valid and len(z.hist_times) >= 2 and z.hist_times[-1] > z.hist_times[0] and all(math.isfinite(v) for v in z.hist)
    forecasts = {str(h): z.fcast(h) if ready else None for h in (30, 60, 120)}
    forecasts = {h: v if v is not None and math.isfinite(v) else None for h, v in forecasts.items()}
    overrides = []
    if valid and z.stall >= cfg['overrides']['stall_secs']: overrides.append('stalled crowd')
    if valid and z.d > cfg['overrides']['packed_density']: overrides.append('packed crowd')
    reason = z.why
    if valid and reason == 'current' and z.level != z.lv(z.d):
        reason = 'persistence pending' if z.rise_since is not None else 'hysteresis / step-down hold'
    eta = z.eta_l4() if ready else (0 if valid and z.d >= z.th[2] else None)
    eta_state = 'unavailable'
    if eta is not None: eta_state = 'at_threshold' if eta == 0 else 'crossing'
    elif ready:
        eta_state = 'not_rising' if forecasts['120'] <= z.d else 'beyond_horizon'
    return {'name': z.name, 'category': z.catname, 'people': z.d*z.area if valid else None,
            'density': z.d if valid else None, 'level': z.eff if valid else None,
            'density_level': z.lv(z.d) if valid else None, 'persistent_level': z.level if valid else None,
            **{'forecast_'+h: v for h,v in forecasts.items()},
            'forecast_levels': {h: z.lv(v) for h,v in forecasts.items()},
            'eta_to_L4': eta, 'eta_state': eta_state, 'speed': z.speed if z.speed is not None and math.isfinite(z.speed) else None,
            'active_overrides': overrides, 'polygon': z.poly.tolist(), 'thresholds': z.th,
            'trigger': reason if valid else 'Unavailable', 'sample_video_s': z.last_tick, 'sample_timestamp': datetime.now(timezone.utc).isoformat(),
            'trend': (1 if forecasts['120'] > z.d else -1 if forecasts['120'] < z.d else 0) if ready else None}


def dashboard_snapshot(cfg, zones, zmap, state, processed, skip, stages, video_s):
    return {'estimator': cfg['estimator'], 'source_type': cfg.get('_source_type', 'Unavailable'),
            'source_status': state, 'frames_processed': processed, 'frame_skip': skip,
            'video_s': video_s, 'zones': [zone_snapshot(z, cfg) for z in zones],
            'links': bottlenecks(zmap, cfg, include_all=True) if zones else [],
            'stages': stages, 'budget_s': 3, 'within_3s_budget': sum(stages.values()) <= 3}


def render_dashboard(frame, status):
    from types import SimpleNamespace
    zones = [SimpleNamespace(name=z['name'], poly=np.array(z['polygon'], np.int32),
                             eff=z['level'], d=z['density']) for z in status['zones']]
    draw(frame, zones, [])


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--config", default="config.json"); ap.add_argument("--source")
    ap.add_argument("--headless", action="store_true"); ap.add_argument("--pick", action="store_true"); ap.add_argument("--max-seconds", type=float)
    ap.add_argument("--source-env"); ap.add_argument("--camera")
    ap.add_argument("--dashboard-dir", nargs="?", const="dashboard_data", default=None)
    ap.add_argument("--loop", action="store_true", help="repeat file sources only")
    ap.add_argument("--realtime", action="store_true", help="pace file playback to source FPS")
    ap.add_argument("--frame-skip", type=int, default=1)
    ap.add_argument("--frame", type=int, default=0, help="zero-based picker frame")
    ap.add_argument("--force-network", action="store_true", help=argparse.SUPPRESS)
    ap.add_argument("--drill", action="store_true", help="inject labelled DRILL L2/L3/L4 staff alerts")
    ap.add_argument('--recordings-dir')
    ap.add_argument('--segment-seconds', type=float, default=60)
    ap.add_argument('--max-gb', type=float, default=5)
    a = ap.parse_args()
    if a.frame_skip < 1 or a.frame < 0: ap.error("frame-skip must be >=1 and frame must be >=0")
    cfg = select_camera(load_cfg(a.config), a.camera)
    try: src = resolve_source(a.source if a.source is not None else cfg["source"], a.source_env)
    except ValueError as e: sys.exit(str(e))
    if a.pick: return pick_points(src, a.frame)
    live = isinstance(src, int) or str(src).lower().startswith(("rtsp://", "http://", "https://")) or a.force_network
    cfg['_source_type'] = 'LIVE CAMERA' if live else ('SYNTHETIC DEMO' if __import__('pathlib').Path(str(src)).resolve() == __import__('pathlib').Path(__file__).with_name('demo.mp4').resolve() else 'VIDEO FILE')
    if live and (a.loop or a.realtime): ap.error("--loop and --realtime are for file sources only")
    dashboard = None
    if a.dashboard_dir is not None:
        from dashboard_output import DashboardOutput
        dashboard = DashboardOutput(a.dashboard_dir, cfg['camera_name'], render_dashboard)
    zones, zmap = [], {}
    processed = 0
    source_state = 'live'
    stages = {'video_s': 0.0, 'backend_s': 0.0, 'dispatch_s': 0.0}
    last_status = 0
    def emit_dashboard(frame=None, sample=False, force=False):
        nonlocal last_status
        if dashboard is None: return
        now = time.monotonic()
        if not (force or sample) and now - last_status < .2: return
        last_status = now
        try:
            dashboard.publish(dashboard_snapshot(cfg, zones, zmap, source_state, processed,
                                                a.frame_skip, stages, locals_video[0]), frame, sample, force)
        except Exception: dashboard._warn()
    locals_video = [0.0]
    def source_state_changed(state):
        nonlocal source_state
        source_state = state
        emit_dashboard(force=True)
    alerts = Alerts(cfg)
    def source_alert(kind, why):
        now = time.time()
        alerts.send(kind, "source", 0, why, None, (now, now, now))
    emit_dashboard(force=True)
    started = time.monotonic()
    cap = StreamCapture(src, source_alert, started + a.max_seconds if live and a.max_seconds else None, a.force_network, source_state_changed)
    ok, frame = cap.read()
    if not ok:
        cap.release()
        source_state_changed("finished")
        if dashboard: dashboard.close()
        if live and cap.expired():
            print("done 0 frames; no readable source frames within time limit")
            return
        sys.exit(f"cannot open source {redact(src)}")
    fps = cap.cap.get(cv2.CAP_PROP_FPS) or 25.0
    zones = [Zone(z, cfg["categories"], frame.shape) for z in cfg["zones"]]; zmap = {z.name: z for z in zones}
    warn_overlaps(zones)
    from estimators import create_estimator
    try: est = create_estimator(cfg)
    except ValueError as exc: cap.release(); sys.exit(str(exc))
    t0 = started; generation = cap.generation; idx = 0; processed = 0; nxt = 0.0; gbuf = deque(); last_occ = None; prev_level = {z.name: 1 for z in zones}
    SW = 320; scale = frame.shape[1] / SW
    recorder = None
    if a.recordings_dir:
        from data_recording import RecordingWriter
        recorder = RecordingWriter(a.recordings_dir, cfg['camera_name'], fps, a.segment_seconds, a.max_gb)
    drill_level = 2
    total_read = 0
    loop_offset = 0.0
    playback_start = time.monotonic()
    try:
      while True:
        if idx: ok, frame = cap.read()
        if not ok:
            if a.loop and not live:
                loop_offset += idx / fps
                if a.max_seconds and loop_offset >= a.max_seconds: break
                cap.release()
                cap = StreamCapture(src, source_alert)
                ok, frame = cap.read()
                if not ok: break
                idx = 0
                zones = [Zone(z, cfg['categories'], frame.shape) for z in cfg['zones']]
                zmap = {z.name: z for z in zones}
                if cfg["estimator"] == "fg": est = create_estimator(cfg)
                gbuf.clear(); prev_level = {z.name: 1 for z in zones}; nxt = loop_offset
            else: break
        t_cap = time.time(); t = (time.monotonic() - t0) if live else loop_offset + idx / fps; idx += 1; total_read += 1
        locals_video[0] = t
        if a.realtime:
            time.sleep(max(0, playback_start + t - time.monotonic()))
            t_cap = time.time()
        if cap.generation != generation:
            if frame.shape[:2] != zones[0].mask.shape:
                cap.release(); sys.exit("Source resolution changed; recalibrate zones before restarting")
            generation = cap.generation
            gbuf.clear()
            for z in zones:
                z.raw.clear(); z.hist.clear(); z.hist_times.clear()
                if hasattr(z, 'display_sample'): del z.display_sample
                z.rise_since = z.stall_since = None; z.speed = None
            nxt = t
        if a.max_seconds and t > a.max_seconds: break
        if recorder: recorder.write(frame, t)
        if (idx - 1) % a.frame_skip: continue
        processed += 1
        counts, occ = est.process(frame, zones, t, fps); t_det = time.time()
        if counts is not None and not all(c is not None and math.isfinite(float(c)) and c >= 0 for c in counts): counts = None
        for z in zones: z.data_available = counts is not None
        if counts is not None:                       # a failed frame simply reuses the previous valid reading
            for z, c in zip(zones, counts):
                z.raw.append((t, c / z.area)); z.people = float(c)
            last_occ = occ
            g = cv2.resize(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), (SW, int(frame.shape[0] / scale)))
            gbuf.append((t, g))
            while len(gbuf) > 1 and gbuf[1][0] <= t - cfg["flow_interval_s"]: gbuf.popleft()
            if t - gbuf[0][0] >= cfg["flow_interval_s"] * 0.9: flow_stats(gbuf[0][1], g, last_occ, zones, t - gbuf[0][0], scale)
        sampled = False
        if t >= nxt and counts is not None:
            sampled = True
            nxt = t + 1.0
            for z in zones:
                if hasattr(z, 'display_sample'): del z.display_sample
                z.tick(t, cfg)
                z.display_sample = zone_snapshot(z, cfg)
            bn = bottlenecks(zmap, cfg); t_ana = time.time()
            if a.drill and drill_level <= 4 and t >= (drill_level - 1) * 2:
                z = zones[0]
                alerts.send('level', z.name, drill_level, 'DRILL staff escalation exercise', None,
                            (t_cap, t_det, t_ana), {'drill': True, 'density': z.d})
                drill_level += 1
            for z in zones:
                if z.eff > prev_level[z.name] and z.eff >= 2:
                    alerts.send("level", z.name, z.eff, z.why, z.eta, (t_cap, t_det, t_ana), zone_snapshot(z, cfg))
                prev_level[z.name] = z.eff
            for b in bn: alerts.send("bottleneck", b["link"], 0, ",".join(b["conditions"]), None, (t_cap, t_det, t_ana))
            stages = {'video_s': round(t_det - t_cap, 3), 'backend_s': round(t_ana - t_det, 3),
                      'dispatch_s': round(time.time() - t_ana, 3)}
        if recorder and sampled:
            recorder.sample(dashboard_snapshot(cfg, zones, zmap, source_state, processed, a.frame_skip, stages, t))
        emit_dashboard(frame, sample=sampled)
        if not a.headless:
            draw(frame, zones, bottlenecks(zmap, cfg) if zones[0].hist else []); cv2.imshow("stampede monitor", frame)
            if cv2.waitKey(1) & 255 == ord("q"): break
    except KeyboardInterrupt:
        pass
    finally:
        if recorder: recorder.close()
        cap.release()
        source_state = 'finished'
        emit_dashboard(force=True)
        if dashboard: dashboard.close()
    if not a.headless: cv2.destroyAllWindows()
    print("processed", processed, "frames (frame-skip", a.frame_skip, ")")
    print("done", total_read, "frames;", {z.name: (z.eff, round(z.d, 2)) for z in zones})
if __name__ == "__main__": main()
