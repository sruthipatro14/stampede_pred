# Progress audit — Stampede Prediction & Prevention
Audit date: 28 October 2026. Scope: files supplied in this directory; the supplied project plan is the acceptance baseline. Existing files were only read. No external research was needed to establish repository progress.

## 1. Executive summary
**Overall completion: 34.2% (evidence-weighted estimate, not a measured engineering completion rate).** A local monitoring prototype, synthetic video generator, dashboard and staff-alert workflow exist. The main prediction deliverable is still a damped trend heuristic, with no trained forecasting model or independent crowd-ground-truth validation. This is demonstrable software, but there is no evidence of operational prevention effectiveness or readiness for field deployment.

Scoring: Not started=0, Scaffold only=0.1, Partial=0.4, Working=0.7, Validated=1; equal weighting of listed items within each group. Scores reflect the **whole requested item**, not individual passing helper tests.

| Weighted group | Included items | Group completion | Weighted points |
|---|---|---:|---:|
| Prediction, 30% | 3a–3c | 40% | 12.00 |
| Simulation, 20% | 1b | 40% | 8.00 |
| CV/pipeline, 15% | 1a, 2a–2d, including storage | 24% | 3.60 |
| Alert/SOP, 10% | 4a | 40% | 4.00 |
| Dashboard, 5% | 4c | 40% | 2.00 |
| Latency, 5% | 4d | 40% | 2.00 |
| Documentation, 15% | D1–D7 below | 17.14% | 2.57 |

The prescribed weights omit A/B comparison, coverage and Semester 6 explicitly; their absence is recorded below and receives no additional points.

## 2. Status table
Each row has exactly one status. “No evidence found” means absent from the inspected project tree, not proof that work does not exist elsewhere.

| Item | Status | Evidence | What is missing |
|---|---|---|---|
| 1a RTSP ingestion / edge setup | Partial | `source_tools.py` (172 lines): `LatestCapture`, `StreamCapture`, retries/latest-frame buffering; mocked recovery tests passed | Actual RTSP session, edge hardware setup and measurements |
| 1b Baseline simulation | Partial | `make_demo.py` (17 lines), `demo.mp4`: 80 s of moving rectangular blobs, filling/stalling stairs | Arena exports: no evidence found; no arrival/service/egress model, calibrated pedestrian interactions or simulation validation |
| 2a YOLO person detection | Working | `monitor.YoloEstimator`; `yolov8n.pt`; `yolo-scene-verification.log`: ten sampled frames detect 0–4 people; `yolo-monitor-verification.log`: 126 processed frames | Independent labels and crowded-scene count accuracy; existing logs establish execution only |
| 2b CSRNet/MCN density estimation | Scaffold only | `density_estimator.py` (46 lines) loads user-supplied TorchScript; `train_density.py` explicitly calls itself a skeleton | Architecture, compatible density weights and completed training: no evidence found |
| 2c ByteTrack/DeepSORT movement tracking | Not started | No evidence found; `monitor.flow_stats` uses Farneback optical flow | Persistent identities, tracks and tracking evaluation |
| 2d TimescaleDB spatial schemas | Not started | No evidence found; persistence is JSON/JSONL/CSV | SQL schema, spatial zones, hypertables, migrations and DB integration |
| 3a Simulation zone time series | Partial | `RecordingWriter.sample`; three demo segment sidecars, 156 zone samples | Data uses estimated blob density, not simulator ground-truth counts; multiple seeded runs/scenarios/splits |
| 3b Baselines + LSTM/GBM + evaluation | Partial | `Zone.fcast`, `backtest_forecast.backtest`; reproduced 30/60 s MAE below | Persistence baseline comparison, trained LSTM/GBM, forecast RMSE and independent test set; reliable 4.0 crossing/false-alarm evaluation |
| 3c Time to threshold | Partial | `Zone.eta_l4`: searches 5–120 s in 5 s steps using `fcast` | Targets category L4, not universally 4.0; no ETA error/coverage validation |
| 4a Three-tier current/predicted SOP engine | Partial | `Zone.tick`, `Alerts.send`, `alert_workflow.py` (88 lines): forecast escalation, overrides, staff metadata/acknowledgements | Required three tiers, approved actionable SOPs and verified recipient delivery |
| 4b Run A vs prediction-triggered Run B | Not started | No evidence found | Intervention changes to simulation and paired outcome comparison |
| 4c Dashboard | Partial | `dashboard.py`, `dashboard_output.py`, `dashboard/index.html`; saved frames/history, zone colour overlays, forecast charts, bottlenecks, sound/ack UI | Mobile delivery and executed SOP trigger; browser usability/sound and full end-to-end validation |
| 4d Latency budget | Partial | `Alerts.send` stage fields; 146 stored alerts have maximum recorded total 0.059 s | Capture/network and completed delivery timing; per-stage 1.2/0.8/1.0 s checks and strict total <3.0 s load validation |
| 5a Railway station | Not started | No evidence found; demo names “Concourse”/“Stairs” only | Site geometry, source data and calibrated scenario |
| 5a Metro station | Not started | No evidence found | Implemented location |
| 5a Temple | Not started | No evidence found | Implemented location |
| 5a Stadium/event venue | Not started | No evidence found | Implemented location |
| 5a Market street/bus terminal | Not started | No evidence found | Implemented location |
| 5b Peak-hour rush | Not started | No evidence found | Explicit demand profile and evaluated run |
| 5b Platform overhang | Not started | No evidence found | Explicit scenario and results |
| 5b Emergency egress | Not started | No evidence found | Exit behaviour and evacuation results |
| 5b Other: filling/stalled stairs | Partial | `make_demo.py`: stair arrivals at 45–60 s; motion stops at 55 s | Physically calibrated scenario and outcome validation |
| Phase 3 integration | Partial | Monitor integrates counting, forecasting, local storage, dashboard and alerts | Planned DB, tracking and trained models are absent; prototype wiring is not full integration |
| Phase 3 field testing | Not started | No evidence found | Site trials and results |
| Phase 4 final SOP | Not started | No evidence found | Approved prevention procedures |
| Phase 4 deployment manual | Not started | No evidence found; README is local prototype usage | Final deployment/rollback/maintenance manual |
| D1 Introduction and Literature Review | Not started | No evidence found | Formal report section |
| D2 Architecture | Partial | `README.md` pipeline description; estimator contract and module docs | Formal architecture section and DB/deployment design |
| D3 Execution Roadmap | Not started | No evidence found | Dated milestones and ownership |
| D4 Simulation Methodology | Partial | README describes synthetic blobs and limitations; `make_demo.py` specifies generator | Formal methodology, assumptions, calibration and replication design |
| D5 Results | Partial | README verification notes; logs and `evaluation_code_test/` | Formal results section with independent outcomes |
| D6 Literature summary, 15+ papers | Not started | No evidence found | Paper summaries, citations and comparative synthesis |
| D7 SDG 3/9/11 mapping | Not started | No evidence found | Explicit mapping and measurable contribution |

## 3. Metrics and verification
Physical line counts include blanks/comments: **1,937 Python lines** across 23 files; not all are implementation. Modules: monitor 380; source_tools 172; alert_workflow 88; dashboard 173 + dashboard_output 97 + HTML 48; make_demo 17; estimators 20 + density_estimator 46; recording/collection 65+22; labeling/training utilities 49+32+33+70; evaluation/backtest 58+92; camera helpers check_yolo/record_clip/save_frame/test_source 44+40+31+63. Test suites: test_camera_tools 127, test_dashboard 124, test_v2 94. README: 399 lines; requirements: 3 entries (OpenCV, NumPy, Ultralytics); Torch needed by density training is not declared.

Implemented coverage: **0 verified real locations; 0 of 3 named scenarios; 1 synthetic composite scenario**, 2 zones, 1 link. Demo collection: **1 recording ID**, 3 MP4/JSON pairs, 2,000 frames, video timestamps 0–79.96 s, 78 sample times/156 zone observations, **10,671,784 bytes** total. Label manifest: 20 rows referencing 10 extracted images; no point-label JSON files found. Synthetic count CSV: 5 pairs. Models trained here: **0 evidenced**; one supplied YOLOv8n weight file, no density or forecasting checkpoints.

Executed with `/opt/anaconda3/bin/python -B`: 8 camera tests excluding the file-writing camera-tag test, plus 4 V2 tests (config preservation, metric/Gaussian arithmetic, missing weights, known-future forecast): **“Ran 12 tests … OK”**. Ran `evaluate_counts.py --csv evaluation_code_test/synthetic_counts.csv` without output-file option: MAE **4.6**, RMSE **7.1414**, bias **−4.6**; arithmetic-only data, not detector accuracy. Re-ran `load_series`/`backtest` in memory: 30 s n=100 MAE **2.6788**; 60 s n=40 MAE **5.9592**; 120 s n=0. Stored `demo_forecast.json` agrees; at 30 s its L4 false alarms are **36/zone-hour**, mean lead **2 s** (one correct episode), versus mixed 6.0/3.3 thresholds, not a universal 4.0 crossing.

Full suites, monitor, video generation, training, collection, HTTP server and webhook delivery were **not run** because they can create files or have external effects. `-B` prevented bytecode writes; selected tests used no temporary files. Existing YOLO/dashboard/workflow logs are historical evidence, not fresh audit executions.

## 4. Contribution summary
`git status` and `git log` return **“fatal: not a git repository”**; no `.git` exists here. Commit count, authors, dates, per-author files/lines and hashes are unavailable, not zero. **All supplied files have no clear author from git evidence**; filesystem ownership/timestamps cannot establish contribution.

## 5. Gaps and risks
A mentor cannot currently obtain evidence for real crowd count accuracy, forecast generalisation, useful 4.0-threshold warning lead, prevention benefit, site calibration or genuine end-to-end latency. The sole recording cannot support independent train/validation splits; forecasts are evaluated against the same estimator's observations. Apparent low latency excludes capture/read time (`t_cap` is assigned after reading), sensor/persistence delay and webhook completion; `within_3s_budget` uses <=3 and checks only the summed recorded stages. Generic staff messages and acknowledgements do not demonstrate an intervention or resolution.

## 6. Plan/documentation mismatches
No slides, formal report, notebooks, Arena files or SQL schemas were found, so slide/report claims cannot be compared directly. Against the supplied plan: level thresholds are **[2,4,6]**, stair thresholds **[1.5,2.5,3.3]**, creating **four** levels; ETA targets 6.0/3.3 rather than 4.0. Forecasts are exponential damped extrapolation, not LSTM/GBM; optical flow is not ByteTrack/DeepSORT; coloured zone overlays are not a validated density-map model. README's early claim “not tested … YOLO” conflicts with its later successful YOLO verification and saved logs; neither establishes accuracy.

## 7. Next 7 days, in impact order
1. Days 1–2: build a seeded simulation with explicit arrivals, zone areas, queues/exits and ground-truth density; cover the three planned scenarios and save reproducible time series.
2. Days 2–4: define independent run splits; compare persistence/trend with GBM or LSTM; report MAE/RMSE, crossing-based lead and false-alarm rate at 4.0, including failures.
3. Days 4–5: implement prediction-triggered intervention and paired Run A/B experiments; measure peak density, unsafe duration and evacuation/throughput outcomes.
4. Day 5: align thresholds/ETA with the three-tier plan and write concrete staff SOP actions; test boundary values and escalation.
5. Days 5–6: obtain authorised fixed-camera footage, measured zone geometry and independent labels; validate YOLO counts before pursuing density fine-tuning/tracking.
6. Day 6: measure capture-to-recipient latency with completed delivery timestamps, stage limits and load percentiles; document missing hardware/RTSP evidence.
7. Day 7: add database schema and reproducible setup, establish version control/ownership, and assemble formal sections, 15-paper summary and SDG mapping with evidence links. Leave uncompleted work explicitly pending.
