# Stampede-risk monitor (OpenCV + Python)

Camera -> person counting per zone -> density (persons/m2) -> level L1-L4 from per-category thresholds
-> damped forecast -> stalled/packed overrides -> bottleneck analysis -> STAFF alerts.
No public announcement is produced by this code.

## Run
    pip install -r requirements.txt
    python make_demo.py                 # makes demo.mp4 (synthetic blobs, NOT real footage)
    python monitor.py                   # window; press q to quit
    python monitor.py --headless        # no window, alerts to console + alerts.jsonl
    python monitor.py --source 0        # webcam;  or --source rtsp://user:pass@ip/stream
    python monitor.py --pick --source 0 # click polygon corners on a frame, press p to print them

## Set up for a real camera (required, otherwise the numbers mean nothing)
1. Fixed camera. Use --pick to get each zone's `image_polygon` (pixels).
2. Measure the same floor area on site and enter `world_polygon_m` (metres) and `width_m`. Density = people / that area.
3. Set `"estimator": "yolo"` (needs ultralytics; counts people by foot point). `"fg"` is experimental background subtraction.
4. Edit thresholds ONLY in config.json `categories` (single source of truth). They are provisional project values,
   not Indian standards. Invalid (non-increasing) thresholds stop the program.
5. For n8n: add a Webhook node, paste its URL in `alert.webhook_url`. Each alert is POSTed as JSON.

## What it computes
- Levels: rise after 10 s above a threshold; fall only 0.5/m2 below the active level's threshold.
- Forecast: damped trend over the last 15 s, 30/60/120 s horizons. +60 s reaching L4 -> at least L3; +120 s reaching L3 -> at least L2.
- Overrides: stalled (density >= category stall_density and speed <= 0.05 m/s for 10 s) -> L4; density > 8 -> L4. Overrides are separate from the forecast.
- Speed and counterflow: Farneback optical flow over occupied pixels.
- Bottleneck: link flagged when 2+ of: width ratio > 1.5, flow J = density x speed x width > 85% of capacity,
  queue growing with flat outflow, speed < 0.5 m/s, counterflow ratio > 0.25.
- Alert: stage times (video, backend, dispatch) against a 3 s budget; 20 s cooldown per zone/level.

## Limits (read before trusting it)
- Tested only on the synthetic demo video. Not tested on real footage, RTSP streams, YOLO, or n8n webhooks.
- Person detectors undercount in dense, occluded crowds (roughly above 3-4 persons/m2). For dense scenes use a
  density-map model (e.g. CSRNet/DM-Count style); this project does not include one.
- `fg` estimator needs a static camera and an empty-scene warm-up; a stationary crowd can fade into the background if learning is on (here it is frozen after warm-up).
- Speed is a rough estimate from flow and an average metres-per-pixel; perspective is not modelled (no homography).
- In the demo, the bottleneck flags fire often (width ratio is always true there, and wrap-around blobs create fake counterflow). Tune on real footage.
- The 5.0 / 2.5 stall densities, capacities and free speeds are assumptions.
- Research prototype, not a certified safety system. Needs review by qualified crowd-safety professionals.


## Connecting a camera

All alerts are for staff only. Use `/opt/anaconda3/bin/python` in this environment.
First test an existing clip:

```bash
/opt/anaconda3/bin/python test_source.py scene.mp4
/opt/anaconda3/bin/python save_frame.py scene.mp4 --frame 100
/opt/anaconda3/bin/python monitor.py --pick --source scene.mp4 --frame 100
```

Frame indices are zero-based. Picking reads through to the requested frame (for a live
source this waits for that many frames). Click one zone in boundary order, press `p`
to print coordinates, and `q` to quit. Reopen the picker for each zone. A warning is
printed if zone masks overlap; a person in the overlap can count in both zones.

RTSP format (ALL uppercase fields below are placeholders, not real credentials):
`rtsp://USERNAME:PASSWORD@CAMERA_HOST:554/STREAM_PATH`. Obtain the actual URL from
camera settings. Prefer the camera's lower-resolution sub-stream to reduce decode
and inference latency. Keep the camera fixed; calibrate each camera and each resolution
separately with measured world polygons and usable passage widths. Never reuse demo
calibration for operational footage. URL-encode reserved characters in credentials.

Set `CAM_URL` privately in your Terminal environment, then run:

```bash
/opt/anaconda3/bin/python test_source.py --source-env CAM_URL
/opt/anaconda3/bin/python monitor.py --headless --source-env CAM_URL --frame-skip 3
/opt/anaconda3/bin/python monitor.py --source-env CAM_URL
```

Alternatively `--source '${CAM_URL}'` expands the environment variable inside Python.
Missing variables are errors. Passwords in URL userinfo are masked in diagnostics;
native network backend output is suppressed because it can expose credentials.
`test_source.py` imposes a 10-second watchdog over opening and reading 30 frames;
reported measured FPS is decode/read throughput, not the stream's declared FPS.
When OpenCV only returns False there is no backend exception to quote.

RTSP uses FFmpeg over TCP, a requested one-frame buffer, and a background reader
that keeps only the newest decoded frame. Network open/read timeouts are 10s/1s.
After 5s of failed reads, the monitor emits `source_lost`, releases the capture and
reopens after 2, 4, 8, 16, then at most 30 seconds between attempts. Recovery emits
`source_restored` and clears time histories so outages do not count as crowd persistence.
Native operations may extend the wall-clock limit by their timeout. File EOF finishes
normally; webcams do not reconnect automatically. Changed stream resolution requires
recalibration and restart.

`--frame-skip N` reads every frame but performs inference on every Nth received frame.
Live timing uses monotonic wall time; files use source frame index / FPS (video time).
Persistence, stall duration, forecasts and queue trends use timestamps; optical-flow
speed uses measured sample intervals. Foreground warm-up uses configured warm-up frames
converted to seconds using source FPS. Alert cooldown remains wall-clock based.
Lower sample rates can still change estimates, especially foreground subtraction.

The original single-camera config works unchanged. For multiple cameras, add a
`cameras` list to the existing config. Each entry must have `name`, `source`, `zones`,
and `links`; global categories, overrides, estimator and alert settings are inherited.
Sources can contain `${CAM_URL}`-style references, using a distinct variable per camera.
Names must be unique; zone names and links belong to that camera only. With multiple
entries select one with `--camera` using its exact configured name. Run all cameras:

```bash
./run_all.sh --headless --frame-skip 3
```

The launcher starts one Python process per camera (or one for the legacy config),
forwards other CLI options, stops all on Ctrl+C or failure, and every JSONL/console
alert includes its camera name (`default` for legacy config). Calibrate and validate
person counts per camera before enabling YOLO for operational monitoring. The launcher
uses the existing config and does not invent camera entries or calibration.


## Dashboard

Start the offline staff dashboard and repeating, real-time synthetic demo:

```bash
./run_dashboard_demo.sh
```

Open **http://127.0.0.1:8000/** in your browser. Click **Presentation mode** or press
**P** for larger text and fewer debug details. The permanent banner identifies this
as a research prototype for staff, not a certified safety system. Check readability,
charts, status badges and image refresh on your laptop/projector before presenting.
Ctrl+C stops both processes. This script clears `dashboard_data/` before starting.

For an existing clip, use two Terminal tabs:

```bash
/opt/anaconda3/bin/python monitor.py --headless --source scene.mp4 --realtime --dashboard-dir dashboard_data
/opt/anaconda3/bin/python dashboard.py
```

`--dashboard-dir` alone uses `dashboard_data/`; without the flag, direct monitor runs
write no dashboard files. `--loop` repeats files only and resets zone/foreground
history at each loop while retaining dashboard history. `--realtime` paces files to
source FPS. Existing calibration/estimator settings still apply. `run_all.sh` enables
dashboard output by default so configured cameras appear as separate tiles; a custom
`--dashboard-dir` is forwarded. Start `dashboard.py` with the same directory and
`--alerts` pointing to your actual JSONL alert file when it differs from `alerts.jsonl`.

Output consists only of allowlisted state, annotated JPEGs (up to 5 Hz), and the last
600 analysis samples per camera. File encoding/writes run asynchronously with a
one-item queue; slow writes drop dashboard updates rather than queueing monitor work.
Atomic file replacement keeps reads consistent. Final shutdown flushes history;
normal history writes are limited to once per second. A write failure warns once and
monitoring continues. Camera directory IDs are safe names or stable hashes.

This server has **no authentication**: keep it on **127.0.0.1**, do not expose its port
publicly, and do not put it behind a public proxy. Binding a different host prints a
warning. Camera imagery and alerts are staff data. Config files and source URLs are
never served. No data older than 5 seconds is shown as current; `NO DATA` replaces
numbers and imagery. Lost, reconnecting and finished sources also hide live readings.
The displayed stage budget measures existing backend stages, not end-to-end camera,
network or browser latency. Foreground counts are estimates, not validated detections.


To verify HTTP endpoints on a machine which permits local listening sockets:

```bash
/opt/anaconda3/bin/python test_dashboard.py --integration
```

Run this while the dashboard demo data is being updated, with port 8000 available;
the test starts and stops its own server. Do not run a separate dashboard server on
that port during the test. Direct handler/unit checks (no listening socket) use:

```bash
/opt/anaconda3/bin/python test_dashboard.py
```

## Live view

The dashboard places footage beside per-zone predictions: current level and density,
30/60/120-second densities and their mapped levels, estimated time to L4, trigger,
trend and category thresholds. It identifies `fg`, `yolo` or `density`. The permanent
staff-only banner remains visible. `NO DATA` replaces live readings after 5 seconds
or when the source is not live. Browser layout and sound must be checked on your Mac.

```bash
./run_dashboard_demo.sh
```

Open http://127.0.0.1:8000/. For calibrated CCTV, set the real URL privately in
`CAM_URL`, start the dashboard separately, and run:

```bash
/opt/anaconda3/bin/python monitor.py --headless --source-env CAM_URL --dashboard-dir dashboard_data
/opt/anaconda3/bin/python dashboard.py
```

Use separate Terminal tabs for these two long-running commands. The existing
estimator is unchanged (`fg`). Change to `yolo`/`density` only after weights,
calibration and count validation. The dashboard does not make uncalibrated estimates
valid. `run_all.sh` uses the configured per-camera zones and separate tiles.

## Alert workflow

New `alerts` config keys control escalation separately from the existing `alert`
transport/log settings. Defaults: L2 highlights the dashboard; L3 adds sound, webhook
and a generic staff-message payload; L4 repeats webhook delivery every 30 seconds
until acknowledged. Empty `alert.webhook_url` means no webhook is sent. Global channel
switches can disable a channel; browser sound is always off until **Enable sound**
is clicked. The first alert feed after a page load is always silent, including after
a browser reload; later polling sounds only newly arriving, unacknowledged recent
alerts once. Enable sound before starting a drill if you want to hear its tones.
Staff-message payloads include camera, zone, level, trigger, density,
ETA and dashboard link. There is no public display, PA or public messaging integration.

Every new alert has a stable ID. Type your staff name and click **Acknowledge**.
The event stays visible, with who acknowledged it and when. `acks.jsonl` stores the
acknowledgements; repeated deliveries retain the original alert ID rather than
creating duplicate alert events. The dashboard server must be running for repeats.
A delivery already in flight when acknowledged may still finish. Acknowledgement is
operational tracking, not proof the crowd condition is resolved.

POST `/api/ack` is restricted to client 127.0.0.1 unless `dashboard.py --token` is set;
when set, every acknowledgement requires that token in `Authorization: Bearer ...`.
Enter that same token in the dashboard token box. Names and alert IDs are validated,
unknown IDs are rejected, repeated acknowledgement is idempotent, and cross-origin
browser requests are rejected. Names are self-reported, not authenticated identities.
Tokens protect writes only; GET images/state are not authenticated. Keep the server
on loopback and never expose the port publicly. No credentials belong in source
control, alert text, recordings or sidecars.

## Drills

```bash
/opt/anaconda3/bin/python monitor.py --headless --source demo.mp4 --realtime --loop --drill --dashboard-dir dashboard_data
```

Run the dashboard in a second Terminal. `--drill` injects a one-time L2/L3/L4 exercise
at about 2/4/6 video seconds through the same staff pipeline. Every fake event has
`drill: true`, a DRILL trigger/console label, and a DRILL staff-message label; real
events have `drill: false`. They share the audit log but are explicitly distinguishable.
The browser uses a visibly labelled, distinct double tone for drill sound. Drills use
configured staff webhook delivery, so use a staff test destination when practising.
Real monitor alerts can still occur during a drill and retain their real labels.

## Collecting data

After calibration, collect real fixed-camera sessions with the current estimator:

```bash
/opt/anaconda3/bin/python collect_data.py --source-env CAM_URL --segment-seconds 60 --max-gb 5
```

For files, `--source scene.mp4` works; for webcams use `--source 0`. `--camera` selects
an existing configured camera. `--max-seconds` bounds a run. Segments and atomic JSON
sidecars are written under `recordings/<safe-camera-id>/<UTC-date>/`. Sidecars include
frame index, video time, timestamp, counts, density, level, thresholds and forecasts.
They omit source URLs. One `recording_id` spans all segments of a collection session.
Record multiple independent sessions to support recording-level train/validation splits.

`--max-gb` counts storage under that recordings directory. The collector removes oldest
completed segment pairs to stay within budget; keep separate archival copies if needed.
Active-segment space is checked periodically; if a segment alone exceeds the budget,
collection stops and its completed oversized segment is removed. Shorten segments or
increase the budget. Recording write errors stop collection visibly. Live capture
can drop frames; sidecar timestamps/frame indices, not nominal MP4 duration, are the
alignment reference. Collection adds encoding load; test throughput on your camera.
Store raw footage securely and collect only footage you are authorized to retain.

## Labeling

```bash
/opt/anaconda3/bin/python extract_frames.py --max-frames 100
```

Output is `labeling/<safe-camera-id>/images/` and a manifest CSV with image, time, zone,
current estimate, polygon and recording ID. Selection favors high levels and rises;
this is useful for finding failures, but is not a representative accuracy sample.
Use separately selected representative sessions for unbiased evaluation.

**`label_counts.py` requires your screen.** Pass the actual extracted image paths (or
use a shell glob for existing JPGs). Click every visible head/person; `u` undoes, `s`
saves JSON points beside the image, and `q` quits. Label consistently, including zero-
person frames. For per-zone comparisons, verify membership near zone boundaries:
head clicks can disagree with YOLO's bottom-centre/foot assignment. Full-frame count
labels avoid that boundary convention issue. Never treat automatic estimates as labels.

## Training the counting model

`estimators.Estimator` defines `process(frame, zones, t=None, fps=25) -> (counts, mask)`:
BGR uint8 input, one count per zone in input order, and a full-resolution uint8
occupancy mask for optical flow. Foreground warm-up may return `(None, None)`.
`create_estimator()` is the only selector; unknown estimator names fail visibly.

For `estimator: density`, configure `density_model` with a **real, trained TorchScript
weights path**, `density_device` as `cpu` or `mps`, and optionally `density_input_size`
as `[width,height]`. Missing weights fail clearly; nothing is downloaded. No model
architecture, random substitute weights or pretrained model is supplied. The model
contract is RGB `[0,1]` BCHW input and finite, nonnegative Bx1xHxW density output whose
pixel sum equals count. Wrap/export the original architecture with its correct
preprocessing and count scaling; arbitrary state-dict checkpoints are not compatible.
Zone polygons are scaled into output-map coordinates and their density is integrated.
The derived occupancy mask is approximate and is not a person segmentation model.

`train_density.py` is a **fine-tuning skeleton**, not a trained counting solution.
It requires actual labeled data, compatible initial weights, and at least two independent
recording IDs. Supply `--manifest` with the actual manifest path and `--weights` with
your actual weights path; select `--device cpu` or `mps`. It builds count-preserving
Gaussian maps from points, trains on one recording subset, validates on held-out
recordings, logs count MAE/RMSE, and writes TorchScript checkpoints, optimizer state,
split metadata and suggested inference settings. Never split adjacent frames/segments
from one recording across training and validation. Its configured input dimensions
must also be used in inference; suggested settings are written but never applied to
config.json automatically. Model-specific training/loss/preprocessing still need review.

**Training has not been run. It cannot be meaningfully run until real labeled recordings
and compatible initial weights exist. No accuracy is claimed.**

## Evaluating counts

`evaluate_counts.py --manifest` compares recorded `current_estimate` against your
point labels within each manifest polygon. It does not silently rerun inference on
shuffled still images, which would invalidate foreground background subtraction.
For new compatible weights, `--manifest` plus `--estimator density` (or `yolo`)
runs the configured model directly on those labeled images; no foreground inference
is attempted on shuffled stills. Alternatively pass `--csv` with `true_count,predicted_count` columns from a measured
estimator run. It reports MAE, RMSE, signed bias (prediction minus truth) and bands
[0,5), [5,15), [15,30), [30,infinity). Negative bias indicates undercounting.

A deliberately synthetic metric-code test is included:

```bash
/opt/anaconda3/bin/python evaluate_counts.py --csv evaluation_code_test/synthetic_counts.csv
```

Those numbers test arithmetic only and say nothing about camera/model accuracy.
For a newly trained estimator, collect/evaluate held-out recordings with that estimator
or export its predictions as CSV. Keep drill events out of operational outcome analysis.

## Backtesting the forecast

```bash
/opt/anaconda3/bin/python backtest_forecast.py --recordings-dir recordings_demo_test --damping-values 20,40,60 --smoothing-values 10,15
```

`recordings_demo_test` contains the synthetic demo collection made during verification.
For your own footage, use your actual recordings directory. Stored 30/60/120-second
forecasts are matched to observed density at the target time (default tolerance 2 s).
Reports include MAE, bias, threshold TP/FP/FN/TN, correct early-warning lead time,
and false warning episodes per evaluable zone-hour (excluding missing future horizons). Confusion compares the horizon endpoint,
not whether a threshold was crossed and cleared earlier. Missing future observations
are excluded and reported as n=0. Damping is the exponential time constant in seconds;
"smoothing" here is the recent-trend window in seconds, not a new learned model.
The optional sweep writes CSV and never changes config.json. False alarms are onset
episodes rather than every repeated forecast sample. Time coverage/forecast errors
are measured against the estimator's observed density, not independently verified
crowd truth. An 80-second demo cannot verify a 120-second horizon.

## Limitations

- `fg` and YOLO can undercount dense/occluded crowds, especially above about 3–4 people/m².
- Forecasts are damped extrapolations, not trained predictions or guarantees.
- Thresholds, capacities and overrides are provisional project settings; no validation or
  standards compliance is established by this code.
- Results apply only to the calibrated camera, view and resolution, and still require
  independent measurement and review. Camera movement invalidates calibration.
- Optical-flow speed is approximate; density-model occupancy masks need independent checking.
- Alert acknowledgement is self-reported; this is not an authenticated incident-management system.
- Browser appearance/sound, real CCTV/network behaviour, training and model accuracy are unverified here.
- This is a research prototype for staff, **not a certified safety system**. There are no
  public announcements, public screens or public alert channels.


### Latest workflow verification

`scene.mp4` successfully exercised local `yolov8n.pt` through the 10-frame sampling
script and a bounded five-second YOLO monitor run. This proves runtime execution,
not accuracy. Its later frames are bright, but show a close foreground person and
ceiling rather than a clear walking-floor area. Do not calibrate zones from this clip.
Copy a fixed-camera crowd video with visible floor and clear people into the project
and provide its exact name. Supply verified image polygons, real floor geometry in
metres, usable passage/link widths, category and flow direction before calibration.

`config.drill-verification.json` disables external webhooks and uses isolated test
alert/ack logs. To check sound and acknowledgements, start the server first:

```bash
/opt/anaconda3/bin/python dashboard.py --config config.drill-verification.json --dashboard-dir dashboard_workflow_test --alerts workflow-drill-alerts.jsonl
```

Open http://127.0.0.1:8000/, click **Enable sound**, then start in a second Terminal:

```bash
/opt/anaconda3/bin/python monitor.py --config config.drill-verification.json --headless --source demo.mp4 --realtime --loop --drill --dashboard-dir dashboard_workflow_test
```

Check DRILL L2/L3/L4 events, type your staff name and acknowledge L4. The event remains
visible with staff name/time. Reloading the page must not replay the existing feed;
sound must be enabled again for future events. Stop only the monitor with Ctrl+C and
leave the server open: readings/image should show NO DATA immediately on finished
status, or within 5 seconds if the monitor disappears without a final write. No real
external webhook is sent by this verification config. Repeated-webhook cancellation
was verified with mocks, not an external recipient.


## Phase 1 dashboard and level contract

Backups before this change are in `backups/phase1/`, including the original configuration bytes. No AGENTS.md was found in this project or its parent tree search. No threshold, capacity, override, persistence or hysteresis setting was changed.

For each category's three configured thresholds a < b < c, the existing mapping is L1: density < a; L2: a <= density < b; L3: b <= density < c; L4: density >= c. There is no configured L0 density band and no extra L1 lower boundary. L1 does not establish safety. Level thresholds are [2,4,6] and stair thresholds [1.5,2.5,3.3] persons/m².

The dashboard separates the instantaneous band of the delayed analysis density, the persistent level (10-second rise persistence, configured hysteresis and one-level step-down), each forecast's category band, and effective level. Effective level starts at persistent level: +60 s reaching L4 raises it to at least L3; +120 s reaching L3 raises it to at least L2. Stalled/packed overrides can force L4. Persistence pending and hysteresis/step-down hold are explained when no higher-priority forecast or override is active. Alert feed entries are historical dispatch events, not current zone levels; DRILL entries deliberately inject exercise levels independent of measured density.

ETA is estimated time to the category's configured L4 density, in 5-second steps through 120 seconds; it is not time to a stampede. Null ETA distinguishes insufficient history, valid non-rising forecasts, and rising forecasts without a crossing in the horizon. Forecasts need two distinct analysis times for display. Counts displayed beside density are delayed-sample estimates (density × measured zone area), not newer raw-frame counts. Zone snapshots and alert metadata are frozen at the same analysis tick; image and associated snapshot are published together as an atomic status document with embedded annotated JPEG. Frame JPEG endpoints remain available for compatibility. This adds JSON bandwidth; performance under multi-camera load remains unmeasured.

Missing/non-finite estimates are unavailable. Fresh capture updates do not make an old analysis sample fresh: zone samples and whole-source state are checked independently against five seconds. Finished/lost sources hide footage and all current readings, forecasts and ETA together. Historical charts are removed during masking. File input is labelled VIDEO FILE; only the project's demo.mp4 is labelled SYNTHETIC DEMO; camera/network input is labelled LIVE CAMERA, separately from receiving-data status. Counting, calibration and provisional thresholds still require independent real-world validation.

Verification commands: `/opt/anaconda3/bin/python -B -m unittest test_phase1 test_camera_tools test_dashboard test_v2` and `node test_dashboard_ui.js` (Node test is renderer-contract testing, not visual QA). Full synthetic regression uses `phase1_verification/config.json`, which keeps thresholds unchanged and external webhooks disabled, with logs/data under `phase1_verification/`. The expected final output remains `done 2000 frames; {'Concourse': (3, 4.92), 'Stairs': (4, 4.16)}`.

For screen testing, start the dashboard first using the existing isolated drill configuration:

```bash
cd /Users/DELL/Documents/sem_5/de_sim
/opt/anaconda3/bin/python -B dashboard.py --config config.drill-verification.json --dashboard-dir dashboard_workflow_test --alerts workflow-drill-alerts.jsonl
```

Open http://127.0.0.1:8000/, wait for the initial silent feed, enable sound, then in another Terminal:

```bash
cd /Users/DELL/Documents/sem_5/de_sim
/opt/anaconda3/bin/python -B monitor.py --config config.drill-verification.json --headless --source demo.mp4 --realtime --loop --drill --dashboard-dir dashboard_workflow_test
```

L2 is dashboard-only; L3/L4 enable sound. Acknowledge a new DRILL alert, then stop only the monitor and verify NO DATA. Restart the monitor to repeat the one-shot drill; looping does not reset it. Verify desktop and narrow layouts and audible playback on your Mac. Audit environment denied listening sockets and returned an unusable browser screenshot, so visual appearance and actual HTTP/browser sound/acknowledgement were not verified by this phase's code checks. `phase1_verification/TEST_preview.html` is a labelled static synthetic display fixture, not live monitoring.
