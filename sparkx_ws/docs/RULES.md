# SparkX Disaster Response Challenge — Rules & Scoring (v1.4)

Robotics & AI challenge · **IIIT Allahabad** · **STEMLearn.AI** · **Airoot** · presented at **IIT Bombay Techfest**.

## 1. Mission

A rescue rover (Husky-class, Airoot livery) is placed on the rescue-base pad of a city block hit by
a blast. After the referee starts the mission the rover must work **without any human input**:

1. explore and build a map with its own sensors (no map is supplied),
2. detect survivors (and ignore mannequin decoys),
3. drive up to each survivor and get the rescue confirmed by the referee,
4. use the clue each confirmed rescue may release to find people who are hard to see,
5. cope with fires, rubble, blocked streets and aftershocks that block more streets mid-run,
6. return to the base pad, submit its map and mission record and end the mission.

Every evaluation world is generated from a secret seed, so no two are alike.

| World size | Arena | Time limit | Survivors |
|---|---|---|---|
| small | ~78 × 78 m (2 × 2 blocks) | 15 min | 5 |
| medium | ~117 × 82 m (3 × 2 blocks) | 20 min | 7 |
| large | ~117 × 117 m (3 × 3 blocks) | 25 min | 9 |

| Difficulty | Survivors | Decoys | Extra fires | Streets blocked at start | Aftershocks | Time |
|---|---|---|---|---|---|---|
| easy | −1 | 1 | 1 | 0 | 0 | — |
| normal | ±0 | 2 | 3 | up to 1 | 1 | — |
| hard | +1 | 3 | 5 | up to 2 | 2 | +5 min |

The generator drops a survivor it cannot place reachably, so a world holds 4–10 survivors; the
exact number is in `MissionStatus.survivors_total` (0 if the organisers hide it). Lighting is one
of day, afternoon, smoky or dusk. About half of the survivors are the target of a clue, and at
least one clue points back to an area near the base that the rover has already passed. Survivors
who cannot be seen from any street are clue targets first. A survivor inside a building is never
more than 12 m of driving from an outside entrance of that building.

**What the world guarantees.** Every survivor can be reached from the base on a route on which the
rover's centre stays at least 3.4 m from the centre of every fire (hazard radii are 2.0–2.5 m), and
that still holds after any aftershock. No fire stands on the only way to a person. Rubble that
counts as a collision is at least 0.35 m tall, so the rover's LiDAR sees it from about 1 m to 5 m
away; loose debris lower than 9 cm is scenery and can be driven over.

**Heat sources (smoky worlds).** Where the fires are thick, some things have been heated to body
temperature: a drum that stood by a fire, a smouldering beam, a steel locker. A world with `smoky`
lighting holds 6 (small), 10 (medium) or 14 (large) of them, standing on open street ground at least
6 m from any person and outside every fire's hazard zone. Each is at 304–313 K and has the size of a
person sitting, lying or standing, so in the thermal image alone it cannot be told from a survivor.
Reporting one is a rejected report. Together with the mannequin decoys (the shape of a person, but
cold) they are the reason one sensor is not enough: decide with several.

**Numbered location markers.** Every street junction, and every landmark a clue can name, has a
marker beside it: a post carrying a four-sided board with a machine-readable tag (ArUco
`DICT_4X4_100`) and its number in print. Each clue gives the person's direction and distance from
one marker, for example *"about 15 m west of marker 12"*. Marker positions are not handed out; the
rover has to find a marker with its camera before it can use it.

## 2. Rescue confirmation

Call `/sparkx/mission/report_survivor` with your estimate of the survivor's position. The rescue
is **confirmed** only if, at that moment, all of these hold:

| Condition | Value |
|---|---|
| mission is RUNNING | |
| rover stationary | ≥ 2.0 s below 0.05 m/s and 0.1 rad/s |
| an un-rescued survivor within | 2.0 m of the rover (horizontal) |
| clear line of sight | from the rover's camera height (0.55 m) to the person, no wall or object between |
| reported position error | ≤ 1.0 m, measured relative to the rover's own `map → base_link` so SLAM drift is not punished |
| report rate | at most one report every 3 s |

A confirmed rescue releases the clue attached to that survivor (if any). A rejected report costs
points unless the reason was `MISSION_NOT_RUNNING`, `RATE_LIMITED` or `INVALID_REQUEST`.

### Clue-led rescues (v1.4)

The +50 for a clue-led rescue is paid only if your rover really used the clue. The referee reads
your `/team/clues` and checks, for the clue that names the person you rescued:

1. its entry had `status` `SEARCHING`, with a `search_center` (in your `map` frame) and a
   `search_radius_m` of at most 8 m;
2. the person was inside that circle (1 m of slack);
3. that area was published **before the rover could see the person**, i.e. before it first came
   within 15 m of them with a clear line of sight after the clue was released. Areas published after
   that moment are ignored, so the area that counts is the last one you published before it.

A search area may be refined freely, but its centre may jump (more than 3 m from where it last
settled) at most 3 times per clue; a fourth jump forfeits that clue's +50. Only the first entry per
`hint_id` in a message is read. A person you find without your search area
pointing at them is still a full rescue (+100 and the accuracy bonus), just without the +50. The
referee never tells you whether an area was right.

### Timing rules

All times are mission time: simulation seconds while the mission is RUNNING. If the simulator runs
slower than a wall clock, these clocks slow down with it.

| Rule | What the referee measures | Penalty |
|---|---|---|
| **Report window: 10 s** | The clock for a survivor starts when the rover is within 2.0 m of them with a clear line of sight (the two conditions of the table above that do not depend on your report). The rescue has to be confirmed within 10 s. Being out of the zone (farther than 2.0 m, or no line of sight) for at least 5 s resets the clock; a shorter absence does not. | −20 once per survivor (`LATE_REPORT`). The survivor can still be rescued afterwards for full points. |
| **Idle limit: 60 s** | The rover has to move at least 0.5 m in every 60 s. Turning on the spot is not moving. | −10 for every full 60 s without it (`IDLE`). |
| **Time limit** | The run ends when the world's time limit is reached. | No return bonus and no time bonus; everything scored until then counts. |
| **Report rate** | At most one report every 3 s. | A faster report is answered `RATE_LIMITED` and is not judged. |

In practice the report window means: do not drive into the 2 m zone until you are ready to stop,
stand still for 2 s and report. A rover that enters, stops at once and reports needs about 4 s.
The limits are also in `GetMissionInfo` (`report_window_s`, `idle_limit_s`, `idle_move_m`).

## 3. Automatic score (referee)

| Event | Points |
|---|---|
| Confirmed rescue | +100 |
| Position accuracy bonus | +20 at 0 m error, falling linearly to 0 at 1 m |
| Clue-led rescue: your rover found the person **through the clue** (section 2) | +50 |
| `EndMission` called inside the base zone (3 m radius) with ≥ 1 rescue | +100 |
| All survivors rescued **and** ended in the base zone | +5 per full minute left |
| Map quality: coverage of reachable space × wall quality (precision and recall, 0.3 m tolerance) × free-space precision (free cells must be drivable ground) | 0 … 100 |
| Semantic record: (½ landmark recall + ½ survivor recall) × precision. Landmarks within 2 m with the right colour; other real objects (markers, landmarks no clue uses) are neutral; every false object lowers the precision | 0 … 50 |
| Rejected rescue report | −25 |
| Report window exceeded at a survivor (`LATE_REPORT`, once per survivor) | −20 |
| Every full 60 s without moving 0.5 m (`IDLE`) | −10 |
| Collision with an obstacle element (a new contact; 1 s without contact, or every 10 s of continuous contact, starts a new one) | −10 |
| Touching a survivor (at most once per 10 s per survivor) | −50 |
| Inside a fire's hazard radius | −2 per second (charged once where fires overlap) |
| Rover rolled or pitched over (> 57°) | −100, rover disabled, run ends |
| Manual intervention by an organiser | −75 |

Fire also drains rover health: 4 % per second in the hazard radius, 15 % per second in the inner
danger radius, for each fire the rover is in. At 0 % the rover is disabled and the run ends. The run also ends at the time limit;
whatever was scored until then counts, but there is no return bonus.

The final score is the exact sum of all points, rounded once to a whole number. Each event shows
how far it moved that rounded total, so the events always add up to the final score.

Scores of several worlds are added up (best run per world). The leaderboard is produced with
`ros2 run sparkx_referee leaderboard`.

## 4. What a team may change — the lock-down

Teams work on **four files** and nothing else:

| File | Role |
|---|---|
| `src/sparkx_team/sparkx_team/perception.py` | sensors → detections (this is where your trained model runs) |
| `src/sparkx_team/sparkx_team/memory.py` | semantic memory and clue resolution |
| `src/sparkx_team/sparkx_team/mission.py` | decision making: explore, approach, follow clues, return |
| `src/sparkx_team/config/team.yaml` | every tunable number, including SLAM and navigation settings |

plus trained weights (data only) in `src/sparkx_team/models/`. The list is `TEAM_FILES.txt`.

The four files you receive are **starters**: they show how to read every sensor, how to drive and
how to talk to the referee, and they contain no detection and no strategy. The robot, its sensors,
the worlds, the referee, the launch files and all other code are locked.

What you hand in is one zip with those four files (and your weights in a `models/` folder),
uploaded to the folder the organisers name. `python3 tools/sparkx_lock.py pack <team>` builds it
for you. The organisers place your files in an untouched copy of the stack, build it and run it on
their own machine, so edits to locked files on your machine never take part in the competition.
A zip that holds anything else is rejected before it runs (see `docs/TEAM_GUIDE.md`).

## 5. Disqualification

A run is **disqualified (0 points for that world, or its score if that was negative)** when team code

- subscribes to or publishes on any `/sparkx/referee_private/*` topic (ground-truth pose, bumper
  contacts, the gated motor command) — the referee watches the ROS graph and ends the run;
- talks to the simulator directly (Gazebo transport, `gz` tools, the `ros_gz_bridge`), reads files
  outside its own package, or otherwise obtains ground truth (survivor positions, the true map);
- tries to start, pause or otherwise control the mission, or to interfere with the referee;
- is driven by a person once the mission runs (teleoperation, parameter changes, restarts).

The referee also watches the rover's true motion. Motion the platform cannot produce (a jump, more
than its top speed, leaving the ground or the arena, moving without a matching command, a frozen
simulation) is recorded as `PHYSICS_ANOMALY` and the run is reviewed by the organisers; deliberate
manipulation is disqualification.

A submission that contains anything outside the four files is rejected before it runs.

## 6. Other rules

- Your software runs on the organisers' machine with a memory limit (8 GB unless announced
  otherwise) and no network access to rely on; a GPU only if the event announces one.
- **The official ML kit is the only machine-learning software you can rely on.** Every evaluation
  machine has exactly this, and nothing more: Python 3.12, **numpy 1.26.4**, **OpenCV 4.6** (`cv2`,
  including `cv2.ml`), **`onnxruntime` 1.32.0** (CPU only, `providers=["CPUExecutionProvider"]`) and the
  ROS 2 Jazzy Python packages. **Not there:** PyTorch, Ultralytics, TensorFlow, scikit-learn, `onnx`,
  `opencv-python` from pip, and anything else. Train with any tool you like on your own machine; what
  you hand in must run with the kit, in one of three levels:

  | Level | What you put in `models/` | Runs with | Good for |
  |---|---|---|---|
  | **1. Plain numbers** (recommended) | `.json`, `.csv`, `.npy` or `.npz`: the learned weights, thresholds or tree splits | your own few lines of numpy | logistic regression, small neural networks, decision trees, nearest neighbours |
  | **2. OpenCV model** | `.xml` / `.yml` / `.yaml` saved by `cv2.ml` (`model.save(path)`) | `cv2.ml.<Type>_load(path)` | random forest, SVM, boosting, k-nearest, small neural network (`ANN_MLP`), logistic regression |
  | **3. ONNX model** | one self-contained `.onnx` file per model, opset 12 to 21, fixed input size, fp32 or int8 (static QDQ) | `onnxruntime.InferenceSession` | image detectors (YOLO-style, RT-DETR, ...) |

  **Prefer a small classifier (level 1 or 2).** A model that takes a handful of numbers your code
  measures about each candidate (its size in metres, shape, temperature, colour, ...) and answers a
  question such as "person or not?" is quick to train from your own recordings, runs in microseconds,
  cannot fail to load, and is enough to win: the organisers' own reference run uses exactly that. Use
  level 3 only if you need a detector that works on whole images, and budget the extra work and risk.

  - **Level 1:** save numbers, not objects: `numpy.save` / `json.dump` of plain lists. `.npy` and `.npz`
    files must load with `numpy.load(path, allow_pickle=False)`.
  - **Level 2:** train and save with OpenCV 4.x (`cv2.ml.RTrees_create()`, `.train(...)`, `.save('m.yml')`).
  - **Level 3:** export to ONNX, for example with Ultralytics:
    `yolo export model=best.pt format=onnx opset=18 imgsz=640 dynamic=False nms=False`. Write the
    pre-processing (resize and letterbox) and the box filtering (NMS) yourself with numpy and `cv2`,
    because Ultralytics is not on the machine. Do not use `cv2.dnn`: OpenCV 4.6 cannot load YOLOv8 or
    newer ONNX files. Use at most 4 threads (`intra_op_num_threads`): your stack shares the CPU with
    navigation and mapping.
  - **Not allowed in `models/`:** pickle-based files (`.pkl`, `.pickle`, `.joblib`, `.pt`, `.pth`,
    `.ckpt`, and `.npy`/`.npz` that need `allow_pickle=True`), because opening one can run code, and
    formats the kit cannot read (`.h5`, `.keras`, `.pb`, `.tflite`, `.safetensors`, `.engine`,
    `.bin`, ...; save raw numbers as `.npy` instead). Other data files your code reads (class names, a
    calibration table as `.txt` or plain YAML) are fine.
- **Before every run, the evaluator opens each of your model files with the official ML kit**, in the
  same sandbox your software runs in: `.json` and `.csv` are parsed, `.npy`/`.npz` are loaded without
  pickle, `cv2.ml` files are loaded and asked for one prediction, `.onnx` files are loaded and run once.
  The result is written next to your score:
  - **The machine lacks the kit or has other versions:** that is the organisers' fault. The run is not
    scored; the machine is fixed and your team runs again.
  - **Your model does not load** (a forbidden format, a pickle, a newer opset, a broken file): that is
    your responsibility. **The run goes ahead and is scored as it is**, with your perception working
    without that model. There is no second attempt for this reason. A detector that silently switches
    itself off can cost you every rescue: let your code fall back to a simpler rule when the model is
    missing, and log it loudly.
  - The check proves that a file opens, not that your code uses it correctly: test your whole stack
    in a practice world before you hand in.
  - Test before you hand in: `python3 sparkx_ws/tools/model_selftest.py` (on your own machine, with
    the kit installed as in `README.md`) prints `OK` for every model that will load in the evaluation.
- Submitted code must not contain positions copied from any world's answer files (`private/`).
  That counts as obtaining ground truth (§5).
- A trained machine-learning model of your own is required: it must go beyond running an unchanged
  pre-trained detector, and its output must change what the rover does. Judges check the dataset,
  training and evaluation described in your report.
- Motor commands are limited by the platform to 1.0 m/s and 1.5 rad/s and are only passed on while
  the mission is RUNNING; a command older than 0.5 s stops the rover.
- Mannequin decoys look like people but are cold. Reporting one is a rejected report.
- Survivors are never closer than 7 m to each other, so two detections a few metres apart are the
  same person. Landmarks, vehicles and the survivors beside them are always outdoors; only people
  placed "in a room" are inside buildings.

## 7. How the automatic score maps to the proposal's evaluation (100 %)

| Area | Weight | Evidence |
|---|---|---|
| Task completion | 30 % | automatic score over the evaluation worlds, normalised |
| Navigation & control | 20 % | map quality, localisation RMSE (logged), collisions, return to base |
| Core technical | 20 % | detection, the trained model and its influence, semantic memory, clue resolution (judges + logs) |
| ROS integration | 10 % | judges |
| Robustness | 10 % | spread of results across worlds, lighting and difficulty |
| Documentation & demonstration | 10 % | judges |
