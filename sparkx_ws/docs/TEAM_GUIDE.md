# SparkX Disaster Response Challenge — Team Guide

Everything a team needs: what you may edit, what the starter files already do, what each of your
files has to do, how to practise, how to hand in, and what gets a run disqualified. Rules and
scoring are in `RULES.md`, every topic and service in `INTERFACES.md`.

## 1. Your four files

```
sparkx_ws/src/sparkx_team/
├── sparkx_team/perception.py   1  sensors -> detections            (your trained model runs here)
├── sparkx_team/memory.py       2  semantic memory + clue resolution
├── sparkx_team/mission.py      3  decisions: explore, approach, follow clues, go home
├── config/team.yaml            4  every tunable number (your nodes, EKF, SLAM, Nav2)
└── models/                        trained weights - data only
```

These, and only these, are yours (`TEAM_FILES.txt` is the authoritative list).

**What you receive are starters.** They run, and they show every call you need, but they contain
no detection and no strategy:

| File | What the starter already does | What is left to you |
|---|---|---|
| `perception.py` | reads the thermal, colour and depth images and the camera intrinsics, converts the thermal image to kelvin, places a pixel on the map (`pixel_to_map`), publishes detections in the agreed format and an evidence snapshot | `detect()` returns nothing: find survivors, fires, numbered markers and landmarks; load and use your trained model |
| `memory.py` | receives detections, publishes `/team/semantic_map` | every detection becomes a new object: fuse them; `resolve()` (clue → search area) returns nothing |
| `mission.py` | listens to the referee (status, events, clues); `ask_info()`, `report_survivor()`, `submit_record()`, `end_mission()`; `go_to()` through Nav2, `drive()` on `/cmd_vel`, `pose()`; publishes the judged topics | `decide()` holds only a demo: 3 m forward, back to base, submit, end. Exploration, approaching people, following clues and timing are yours |
| `team.yaml` | working settings for localisation, mapping and navigation | parameters of your own nodes; tune the rest if you wish |

Launch the starter once before you change anything (section 4): the rover drives 3 m, returns and
ends the mission, and the log shows each exchange with the referee.

Everything else is locked: the robot and its sensors, the worlds, the referee, the launch files,
the message definitions, the package's own `setup.py`. You cannot add files, and a fifth Python
file next to yours will not be part of your submission. Keep helper code inside your three files.

Check at any time that you have not changed a locked file by accident:

```bash
cd sparkx_ws
python3 tools/sparkx_lock.py status      # the allow-list and the state of your checkout
python3 tools/sparkx_lock.py verify      # lists every modified / added / removed locked file
```

## 2. What each node must do

The locked launch file (`sparkx_baseline/launch/baseline.launch.py`) starts the localisation,
mapping and navigation nodes and then exactly three executables from your package, each calling
`main()` in the matching file:

| Executable | File | Node name in `team.yaml` |
|---|---|---|
| `perception` | `perception.py` | `sparkx_perception` |
| `memory` | `memory.py` | `sparkx_semantic_memory` |
| `mission` | `mission.py` | `sparkx_mission` |

**perception.py** — reads `/thermal/image_raw`, `/camera/color/image_raw`,
`/camera/depth/image_raw` (and `/lidar/points` if you want) and publishes
`/perception/detections` (`vision_msgs/Detection3DArray`, frame `map`, `class_id` =
`survivor` | `fire` | `marker:<number>` | `<landmark_class>:<color>` | `sign:<LABEL>`) plus a
snapshot image used as evidence. Your trained model belongs here; its weights are found through
the `model_dir` parameter, which points at the installed `models/` folder.

**memory.py** — fuses repeated detections into persistent objects, publishes
`/team/semantic_map` (judged) and offers `resolve()`, which turns a clue such as *"about 15 m west
of marker 12"* into a search area on your own map. It may also publish keep-out points on
`/team/keepout` so navigation stays clear of people and fires.

**mission.py** — the decision maker. Talks to the referee (`report_survivor`, `submit_record`,
`end`), publishes `/team/behavior_state` and `/team/clues` (both judged) and drives the rover
through Nav2's `navigate_to_pose` action, or directly on `/cmd_vel` if you prefer.

**team.yaml** — parameters of your three nodes and of `ekf_filter_node`,
`pointcloud_to_laserscan`, `slam_toolbox` and the Nav2 servers. The launch file always forces
`use_sim_time` and the topic names; the rest is yours.

The topics between your three nodes (`/perception/detections`, `/team/memory/update`, …) are your
own business: change them if you change both ends. The interface to the referee is fixed.

Two facts that decide how a search has to work: the LiDAR maps walls out to 30 m, but a person
shows up in the thermal camera only within about 11 m and inside its 57° field of view, so ground
that is on the map has not necessarily been looked at; and a clue can only be used once your rover
has seen the numbered marker it names.

## 3. The trained model

The rules ask for a model you trained yourself whose output changes what the rover does; running
an unchanged pre-trained detector is not enough. A practical route:

```bash
# record labelled images in a practice world (the ground-truth box camera exists only for this)
ros2 launch sparkx_sim sim.launch.py world:=practice_small_day gt_bbox_camera:=true
ros2 run sparkx_bringup teleop
ros2 run sparkx_bringup dataset_capture --ros-args -p out_dir:=~/sparkx_dataset -p every_n:=5
```

Train on your own machine, put the weights in `src/sparkx_team/models/` and load them in
`perception.py`. Only data files may live in `models/` (no `.py`, `.so`, `.sh` …), the folder is
flat (no sub-folders), a single file may be up to 500 MB and the folder up to 1.5 GB.

**Your model must run with the official ML kit** (RULES §6): numpy 1.26.4, OpenCV 4.6 (with `cv2.ml`)
and `onnxruntime` 1.32.0 on the CPU. Nothing else is installed: no PyTorch, no Ultralytics, no TensorFlow,
no scikit-learn. Train with whatever you like on your own machine, then hand in the model in one of three
levels:

| Level | File in `models/` | Your code loads it with | Good for |
|---|---|---|---|
| **1. Plain numbers** | `.json` `.csv` `.npy` `.npz` | `json.load`, `numpy.load(path, allow_pickle=False)` | logistic regression, small neural network, decision tree |
| **2. OpenCV model** | `.xml` / `.yml` saved by `cv2.ml` | `cv2.ml.RTrees_load(path)` (or `SVM_load`, `ANN_MLP_load`, ...) | random forest, SVM, boosting, k-nearest |
| **3. ONNX** | `.onnx` (opset 12 to 21, fixed input size) | `onnxruntime.InferenceSession(path)` | detectors that work on whole images |

**Start with a small classifier (level 1 or 2).** Let your code find candidates with the sensors (a warm
spot in the thermal image, a coloured blob, a LiDAR cluster), measure a handful of numbers about each one
(size in metres, shape, temperature, colour, ...), and let a trained classifier decide "person or not",
"landmark or not". It trains in seconds on a few hundred examples you record yourself, runs in
microseconds on the CPU, cannot fail to load, and counts fully as your trained model: the organisers'
own reference run uses exactly that kind of model. Move to level 3 only if you need a detector on whole
images, and budget the extra work: you write the resizing and the box filtering yourself, and a big
network slows your whole stack down.

A level-1 example: train a logistic regression anywhere, save its numbers, use them with numpy.

```python
# on your own machine (any library), after training:
json.dump({'mean': mean.tolist(), 'std': std.tolist(), 'w': w.tolist(), 'b': float(b)}, open('person.json', 'w'))

# in perception.py
m = json.load(open(os.path.join(self.model_dir, 'person.json')))
z = (np.asarray(features) - m['mean']) / m['std']
p_person = 1.0 / (1.0 + np.exp(-(z @ np.asarray(m['w']) + m['b'])))
```

A level-2 example, with OpenCV only:

```python
rf = cv2.ml.RTrees_create(); rf.train(X.astype(np.float32), cv2.ml.ROW_SAMPLE, y.astype(np.int32)); rf.save('person.yml')
# in perception.py
rf = cv2.ml.RTrees_load(os.path.join(self.model_dir, 'person.yml'))
_, label = rf.predict(np.float32([features]))
```

**Not allowed in `models/`:** pickles (`.pkl`, `.joblib`, `.pt`, `.pth`, `.ckpt`) and formats the kit
cannot read (`.h5`, `.tflite`, `.pb`, `.safetensors`, `.bin`, ...). Save numbers, not Python objects.

Install the kit once on your own machine, exactly as the evaluators do (numpy and OpenCV come with the
`apt` line in `README.md`; `onnxruntime` is needed only for level 3, but install it anyway):

```bash
sudo python3 -m pip install --break-system-packages --no-deps onnxruntime==1.32.0
python3 -c "import numpy, cv2; print(numpy.__version__, cv2.__version__)"     # must print 1.26.4 4.6.0
```

Then test every file in `models/` the way the evaluator will (it runs this same file before your run):

```bash
python3 sparkx_ws/tools/model_selftest.py      # one line per file: OK with its level, or why it will not load
```

A model that does not load in the evaluation is **your** problem: the run is scored without it. The same
applies to a model that needs more than your memory limit to open, or more than 180 s; `.npz` arrays that
unpack to more than 1 GB in total fail the check. The
check only proves that the file opens: test your whole stack in a practice world too. Give your code a
fallback (for example a plain temperature-and-size rule) and log loudly when the model is missing, so
that you see it in `team.log`.

## 4. Practise

```bash
cd sparkx_ws && colcon build && source install/setup.bash

# simulator + referee + your stack, dashboard on http://127.0.0.1:8080
ros2 launch sparkx_bringup practice.launch.py world:=practice_small_day gui:=true

# other practice worlds
#   practice_small_day is the one practice world in this release; more are released later.
#   Generate your own medium and large worlds to test on (see README.md, Worlds).
```

After editing a team file run `colcon build --packages-select sparkx_team` and launch again. Each
run writes a folder under `~/sparkx_logs/` with `summary.json` (score breakdown, map and
localisation metrics), `events.jsonl`, `reports.jsonl` and your map as an image. The practice
worlds ship with their answer sheets (`worlds/<name>/private/`), which is fine for debugging;
competition worlds are generated from secret seeds and you never see their `private/` folder.

## 5. Hand in

```bash
cd sparkx_ws
python3 tools/sparkx_lock.py pack <team_name>        # -> <team_name>_submission.zip
```

`pack` refuses to build the archive if one of the four files is missing or does not compile, or if
`models/` contains code, links or oversized files. Upload the zip to the folder the organisers
gave you. Name it after your team: the file name is the team name on the leaderboard.

A zip you made by hand is accepted too, as long as it contains exactly `perception.py`,
`memory.py`, `mission.py`, `team.yaml` and, optionally, a `models/` folder with data files. The
folder layout inside the zip does not matter; anything else in it gets the zip rejected.

What the organisers do with it: the four files are placed in an untouched copy of the stack, the
`sparkx_team` package is rebuilt, and your software is run against the simulator and the referee
on a world you have not seen. A change you made to any locked file never reaches that run. Your
software runs without access to the organisers' files and with a memory limit.

## 6. What gets a run disqualified

- Any node of yours subscribing to or publishing on `/sparkx/referee_private/*`. The referee checks
  the ROS graph every second, raises a `RULE_VIOLATION` event and ends the run. `ros2 topic echo`
  on such a topic counts too.
- Talking to the simulator directly (Gazebo transport, `gz` commands, your own bridge), or reading
  files outside your package to get ground truth.
- Trying to start, pause, abort or otherwise steer the mission, or interfering with the referee.
- Human input once the mission is running.

A submission with anything outside the four files and `models/` is rejected before it runs.

## 7. Things that cost points in practice

- A rejected rescue report costs 25: stop fully for 2 s, be within 2 m with a clear view, and
  report a position that is right to 1 m. Reporting a mannequin is a rejected report.
- **Report window.** From the moment the rover is within 2 m of a person with a clear view, the
  rescue has to be confirmed within 10 s, or it costs 20 (once per person). Get ready outside the
  zone: face the person, then drive in, stop, wait 2 s, report.
- **Idle limit.** Every full 60 s in which the rover does not move 0.5 m costs 10. A rover that
  is stuck has to notice and get itself out.
- Touching a survivor costs 50, each collision 10, each second next to a fire 2 plus health.
- The return bonus (100) needs `EndMission` called inside the 3 m base zone before time runs out.
- Your `map` frame must start at the start pose, or the map score is computed against the wrong place.
