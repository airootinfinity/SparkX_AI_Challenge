<p align="center"><img src="../sparkx_ws/src/sparkx_worlds/models/sparkx_media/brand/header_strip_dark.png" alt="IIIT Allahabad | STEMLearn.AI | Airoot | Presented at IIT Bombay Techfest" width="100%"></p>

# SparkX evaluator guide (`hosting/`)

This folder is the **checker**. For each team it:

1. checks that the submission zip was handed in properly;
2. builds the team's code into a clean copy of this stack;
3. runs it on a world in competition mode;
4. stores the referee's score and keeps the leaderboard.

It is the same tool the organisers use for the official runs.

Who uses it:

- **Evaluators**: run every team's zip and keep the leaderboard.
- **Teams**: may use `check` (section 4) to make sure their own zip will be accepted before they upload it.

Everything below runs from the root of your clone of this branch. In the examples that folder is
called `$SPARKX_EVAL` (the training material calls a participant's clone of `main` `$SPARKX`; keep
the two apart). Set it once per terminal, or add the line to `~/.bashrc`:

```bash
export SPARKX_EVAL=~/SparkXEval   # wherever you cloned the evaluator branch
cd $SPARKX_EVAL
```

## 1. What the machine needs

- **Everything the team quick start needs:** Ubuntu 24.04, ROS 2 Jazzy and the `apt install` line in the main [`README.md`](../README.md) §4, and a GPU that runs Gazebo.
  - **Install Nav2 and SLAM with `apt`, into `/opt/ros/jazzy`.** Teams may name files there in `team.yaml`, for example
    `/opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees/navigate_w_replanning_only_if_path_becomes_invalid.xml`.
    Nav2 copied into any other folder makes such a team fail on your machine and not on the official one.
- **The official ML kit** (RULES §6): numpy 1.26.4 and OpenCV 4.6 from `apt` (with `cv2.ml`), plus `onnxruntime` 1.32.0.
  Teams hand in models at three levels: plain numbers (`.json` `.csv` `.npy` `.npz`), an OpenCV `cv2.ml` model (`.xml` `.yml`), or `.onnx`.
  The official organiser image (`docker/Dockerfile`) contains the kit. On your own machine, install `onnxruntime` system-wide, pinned and without dependencies:
  ```bash
  sudo python3 -m pip install --break-system-packages --no-deps onnxruntime==1.32.0
  python3 -c "import numpy, cv2; print(numpy.__version__, cv2.__version__)"     # must still print 1.26.4 4.6.0 (ROS needs them)
  ```
  Do not use `pip install --user`: the sandbox hides your home folder, so team software would not see it.
  Do not install other ML packages (PyTorch, Ultralytics, `opencv-python`): they are not part of the kit,
  and some replace numpy or OpenCV for every ROS program.
  Before each run the tool checks the kit inside the sandbox. If it is missing or the wrong version, the run is refused.
  It then opens every file in the team's `models/` with `sparkx_ws/tools/model_selftest.py`, the same file teams test with.
- **bubblewrap**, the sandbox for team software: `sudo apt install bubblewrap`. With the default `"sandbox": "on"` the tool refuses to run a team without it.
- **Team software must not run as a user in the `docker` group**, or as any user that can start containers or use `sudo`.
  Run `secure_setup.sh` (section 3) and set `team_user`. Until you have, run only zips from people you trust.

Check the machine before the first scored run, and again after any system update. Section 9 explains what each line means.

```bash
ls /opt/ros/jazzy/share/nav2_bt_navigator/behavior_trees/ | head -3   # Nav2 from apt: files listed
python3 -s -c "import numpy, cv2, onnxruntime as o; print('ML kit', numpy.__version__, cv2.__version__, o.__version__)"   # ML kit 1.26.4 4.6.0 1.32.0
id -nG "$(python3 -c "import json;print(json.load(open('hosting/host_config.json')).get('team_user') or '$USER')")" | tr ' ' '\n' | grep -x -e docker -e sudo || echo "team user ok"
```
- **Memory:**
  - The simulator and referee need about 2.5–3 GB for a medium world.
  - A team's software is limited to 8 GB by default.
  - 16 GB of RAM is comfortable for the small world. Use more for large worlds.
- **One evaluation at a time.** The tool refuses to start a run while one of its own runs is on, or while
  anything else serves the referee dashboard port (8080), i.e. another SparkX simulation. Close any Gazebo you started yourself.

## 2. Get the evaluator branch

Use a folder of its own, separate from any team work:

```bash
git clone -b evaluator https://github.com/airootinfinity/SparkX_AI_Challenge.git ~/SparkXEval
export SPARKX_EVAL=~/SparkXEval && cd $SPARKX_EVAL
git branch                         # * evaluator
```

Already have a clone of `main`? `git fetch origin && git switch evaluator` gives you the same files.
`git switch main` goes back.

## 3. One-time setup

```bash
cp hosting/host_config.example.json hosting/host_config.json      # then edit it for this machine (table below)
python3 hosting/sparkx_host.py setup
```

`setup` builds `sparkx_ws/` from scratch, which takes under a minute on a fast machine. It then checks the stack against its seal. The end of
its output must be:

```
Summary: 8 packages finished [15.1s]
stack integrity: OK  (741 locked files, fingerprint 7be8cd944cd41441)
sandbox for team software: available (bubblewrap)
```

The fingerprint must be the one the organisers announced for the release.

If setup prints `REFUSED: this copy of the stack differs from its seal`:

1. something in `sparkx_ws/` was changed;
2. `git status` shows what changed;
3. `git checkout -- <file>` restores it;
4. run `setup` again.

Never evaluate on a stack that does not verify.

Check the referee's timing rules once (no simulator needed):

```bash
python3 hosting/test_timing_rules.py       # report window, idle limit, clue rule; last line: ALL PASSED
```

### Secure the machine (once, needs sudo)

Team software runs on this machine while the simulator and the referee hold the answers. Run once:

```bash
sudo bash hosting/secure_setup.sh
```

It creates a user `sparkxteam` for the team software, a firewall that gives that user no TCP, no
simulator discovery and no traffic off the machine (ROS 2 keeps working), and read access to the
built stack only. Then set `"team_user": "sparkxteam"` in `hosting/host_config.json`. Before every
run the tool tests that the firewall really blocks; if it does not, the run does not start.

**Without this step, `run` refuses scored runs.** It also refuses when `team_user` is you, root, or a user in a group
that gives root access (`docker`, `sudo`, `adm`, `lxd`, ...): such a user can leave the sandbox. For a test on an
unsecured machine, add `--unofficial`: the run goes ahead, `host.json` says `"official": false`, and the leaderboard
skips it. Runs on worlds that were not made with `new-world` (plain seed, e.g. the practice worlds) are unofficial
for the same reason: they are not private.
After `setup` rebuilds the stack, run the script again. `sudo bash hosting/secure_setup.sh --remove` undoes it.

`hosting/host_config.json` holds the settings of your machine. It is never committed. Delete it to
use the defaults.

| Key | Default | Meaning |
|---|---|---|
| `team_memory` | `8G` | memory limit of a team's software (the rules promise teams 8 GB) |
| `team_cpus` | `8` | CPU cores for a team's software (applied only if your system allows it) |
| `org_memory` | none | memory limit of simulator + referee (e.g. `3200M`); leave empty unless the machine is short of memory |
| `textures` | `full` | `lite` halves texture memory. Use `full` for scored runs |
| `sandbox` | `on` | `on` refuses to run without bubblewrap; `auto` runs unsandboxed when bubblewrap is missing; `off` never sandboxes (tests only) |
| `min_free_mb` | 0 | refuse to start a run with less free memory than this |
| `team_user` | none | run team software as this user (`sparkxteam` after `secure_setup.sh`); **required for scored runs** (without it `run` refuses, unless `--unofficial`) |
| `extra_setup`, `team_visible_paths` | none | only if Nav2 / SLAM come from your own workspace instead of `apt`: its `setup.bash`, and that folder |
| `dashboard_port`, `ui_port` | 8080, 8090 | the referee's dashboard and this tool's control panel |

## 4. Check a submission (did they hand in properly?)

Put the teams' zips into `hosting/submissions/`. The file name is the team name:
`roborescuers.zip` or `roborescuers_submission.zip` → team `roborescuers`.

```bash
python3 hosting/sparkx_host.py check hosting/submissions/roborescuers_submission.zip
```

`check` runs nothing. It accepts a zip only if it holds these files and nothing else:

- `perception.py`, `memory.py`, `mission.py` and `team.yaml`;
- optional data files in a `models/` folder.

The folder layout inside the zip does not matter. Real outputs:

```
demo_team_submission.zip (team "demo_team"): ACCEPTED

missing_team.zip (team "missing_team"): REJECTED
  team.yaml: missing

extra_file.zip (team "extra_file"): REJECTED
  notes.py: not one of the four team files and not inside models/

syntax_error.zip (team "syntax_error"): REJECTED
  src/sparkx_team/sparkx_team/mission.py: does not compile: line 295: invalid syntax
```

The exit code is 0 for accepted and 1 for rejected. Other reasons for a rejection:

- code inside `models/`;
- sub-folders in `models/`;
- a file over 500 MB, or more than 1.5 GB in total;
- a file name that appears twice.

**Teams:** make your zip with `python3 sparkx_ws/tools/sparkx_lock.py pack <team_name>` (on `main`),
then run `check` on it from this branch.

## 5. Run a submission (does the code work?)

```bash
python3 hosting/sparkx_host.py run hosting/submissions/demo_team_submission.zip --world practice_small_day
```

What one run does:

1. checks the zip;
2. copies the sealed stack into `hosting/work/<team>/`, puts the four files in and rebuilds only `sparkx_team`;
3. starts the simulator and the referee in competition mode;
4. starts the team's software in the sandbox, with its memory limit;
5. starts the mission when navigation reports ready.

The run ends when the team ends the mission, at the time limit, or when the team's software dies.
Real output of the starter files:

```
[12:44:18] demo_team: copying the sealed stack
[12:44:19] demo_team: files accepted, building sparkx_team
[12:44:52] simulator and referee are up after 32 s (world practice_small_day)
[12:44:52] team software started (sandboxed, memory limit 1000M)
[12:45:06] navigation active after 14 s
[12:45:11] MISSION STARTED
[12:45:41]       25s MISSION_FINISHED: END_MISSION:COMPLETED (in base) (+0)
[12:45:45] RESULT demo_team on practice_small_day: score 27, rescued 0/4, END_MISSION:COMPLETED (in base), mission time 25 s
```

That run had `team_memory` set to 1000M; with the defaults the line says 8G. The starter only drives 3 m and back,
so 27 points is what the unchanged starter scores. A real solution runs for most of the time limit
(15 min on a small world, 20 medium, 25 large).

Options:

- `--gui` shows the Gazebo window. Use it only to watch a run, never on a machine short of memory.
- `--time-limit <s>` overrides the world's time limit, for quick tests only, never for a scored run.

While a run is on:

- the referee's dashboard is at `http://127.0.0.1:8080/?token=<token>`. The panel in section 6 shows this link.
  - In a competition run the dashboard shows nothing without its token, because team software runs on the same machine.
  - It shows the live score, the arena map with the rover and every survivor, the clues released, every scored event, and the rover's **colour and thermal camera** (the "Rover cameras" box, about 3 pictures a second);
- `python3 hosting/sparkx_host.py stop` stops it.

Where the results are:

| Path | What |
|---|---|
| `hosting/results/runs/<date>_<team>_<world>/summary.json` | the score: `official_score`, `final_score`, `score_breakdown`, `rescued`, `finish_reason`, `disqualified`, `rule_violations`, `stack_integrity` |
| `…/events.jsonl`, `…/team_map.png`, `…/evidence/` | every scored event, the team's map, the snapshots sent with rescue reports |
| `…/host.json` | which zip ran (its SHA-256), whether it was sandboxed, the memory limit |
| `hosting/results/team_logs/<date>_<team>_<world>/` | `team.log` (the team's own output: look here when their code crashed), `organiser.log`, `roslog/` |
| `hosting/results/leaderboard.csv` | rebuilt after every run |

## 6. The control panel (the button)

```bash
python3 hosting/sparkx_host.py ui           # opens the panel in your browser; Ctrl-C quits (and stops a run)
```

The panel's address ends with a key, `http://127.0.0.1:8090/?key=…`, printed in the terminal and
different every time. Team software runs on the same machine, so the panel answers nothing without
that key. If the browser does not open by itself, copy the full address from the terminal.

The panel shows:

- every zip in `hosting/submissions/`, with the result of `check` and every run it has had;
- a world selector;
- a **Build & run** button per team;
- **Run every accepted team on this world**, which queues them one after another.

While a run is on, it shows the mission clock, the score, the referee's events and a link to the live dashboard. The
leaderboard is at the bottom.

## 7. Worlds

- `practice_small_day` ships with the stack and is always offered: use it to test the pipeline.
- Competition worlds come from the same generator, with a **random 63-bit seed and a private salt**:

```bash
python3 hosting/sparkx_host.py new-world --name final_A --size medium --difficulty normal --lighting day
```

- Leave `--seed` out: the tool draws a random seed and mixes in the salt file `~/.sparkx_organiser/world_salt`
  (made on first use). Back that file up privately: without it a world cannot be rebuilt. Share it only with the
  other evaluators, the same way as the worlds.
- A world made with a plain seed (`--practice`, or `ros2 run sparkx_worlds generate_world` directly) is not
  salted, and `run` treats every run on it as unofficial.

They land in `hosting/worlds/<name>/`. Look at `hosting/worlds/<name>/private/preview.png` (survivors,
clues, fires) before you use one.

- `private/` is the answer sheet: never commit, upload or share it, and never write the seed anywhere public.
- `.gitignore` keeps the whole folder out of git.
- Every evaluator must run a team on the *same* world folder. Copy it between machines privately, or have one machine run everything.

## 8. Leaderboard

```bash
python3 hosting/sparkx_host.py board
```

Real output:

```
 # team                    total  rescued  per world
 1 demo_team                  27        0  practice_small_day: 27 (0/4)
```

The total is the sum, over all worlds, of each team's best official score on that world. A disqualified run counts 0.

## 9. Evaluator checklist (one per submission)

1. The zip arrived before the deadline and its name is the team name.
2. `check` says ACCEPTED. If it is REJECTED, tell the team the exact reason that `check` printed.
3. `setup` (or `python3 sparkx_ws/tools/sparkx_lock.py verify`) still says `stack integrity: OK` with the announced fingerprint,
   and the three machine checks in section 1 pass.
4. Read the team's code (section 9a).
5. `run` on each competition world, one run at a time, with full textures and no `--time-limit`.
   Watch it (section 9b), and check every point afterwards (section 9c).
   If points were lost because of the machine, not the team, fix the machine and run again (section 9e).
6. In `summary.json`:
   - `disqualified` is false;
   - `rule_violations` is empty;
   - `stack_integrity.status` is `ok`;
   - `finish_reason` makes sense.
7. If the run ended early, read `team.log`. A crash in the team's code counts as their result, but a
   machine problem does not: then run it again.
8. Note the `official_score`. The leaderboard keeps the best run per world.
9. Before results are announced, read the code of the top teams. A team is disqualified on a world if its code:
   - touches `/sparkx/referee_private/*`;
   - talks to Gazebo directly;
   - reads ground truth from files;
   - was driven by a person.

   See `sparkx_ws/docs/RULES.md`.

### 9a. Read the team's code before it runs

The zip is code from outside, and it runs on your machine. Unpack it into a folder of its own and look first:

```bash
mkdir -p /tmp/review_<team> && cd /tmp/review_<team>
python3 -I -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall('.')" $SPARKX_EVAL/hosting/submissions/<team>.zip
grep -rn -i -E "docker|socket|subprocess|os\.system|popen|exec\(|eval\(|ctypes|/proc|/var/run|gz |gazebo|referee_private|sendTransform|TransformBroadcaster|/clock|requests|urllib|http|token|environ" src/
grep -rhn -o -E "create_(publisher|subscription|client)\([^,]*,[^,]*" src/
diff <(cd $SPARKX_EVAL/sparkx_ws/src/sparkx_team && cat config/team.yaml) src/sparkx_team/config/team.yaml
```

- **The first `grep` should find nothing.** Every hit needs a reason. Publishing their own `map` → `base_link` transform is allowed for localisation, but note it, because the clue rule relies on it.
- **The topics** must be the ones in `sparkx_ws/docs/INTERFACES.md`: sensors, `/cmd_vel`, `/sparkx/mission/*`, `/team/*`, plus their own topics between their three nodes.
- **`team.yaml`:** absolute paths must exist on the official machine (section 1). Driving faster than 1.0 m/s is cut by the referee anyway.
- **Positions typed into the code.** List every pair of numbers that looks like a map position, and every survivor ID such as `S01`:
  ```bash
  grep -rn -E "S0[0-9]|\(\s*-?[0-9]+\.[0-9]+\s*,\s*-?[0-9]+\.[0-9]+\s*\)|-?[0-9]+\.[0-9]+\s*<=\s*map_pt" src/
  ```
  Compare them with the practice worlds' answer files (`sparkx_ws/src/sparkx_worlds/worlds/*/private/scenario.yaml`).
  Survivor positions copied from there are ground truth, and **RULES §5 disqualifies the run on that world**. The referee
  cannot see this; only reading the code finds it. On a secret world such numbers point nowhere, so also expect the team to score much lower there.
- **Code that depends on a library** (`import onnxruntime`, `ultralytics`, ...) inside a `try:`: find what the code does when the import fails.
  If it quietly switches a detector off, a missing library on your machine is a machine problem (section 9e), not a weak team.

### 9b. Watch the run

- **Open the dashboard.** The `run` command and the panel print its link. In a competition run the link carries the token, and the token is new for every run.
- **Every point appears live** in `hosting/results/runs/<run>/events.jsonl`, one line per event:
  ```bash
  tail -f hosting/results/runs/<run>/events.jsonl
  ```
- **The team's own output** is in `hosting/results/team_logs/<run>/team.log`. When points go down, it says what the rover was trying to do.
- **Time:** the referee counts simulator time. A slow machine makes the run longer in real minutes, but it does not change the score.

### 9c. Check every point after the run

In `summary.json`:

1. **The points add up.** The `points` in `score_breakdown` add up to `final_score`, apart from rounding. Since
   24 Nov 2026 the `score_delta` values in `events.jsonl` (which now include `MAP_QUALITY` and `SEMANTIC_RECORD`) add
   up to `final_score` exactly:
   ```bash
   python3 -c "import json,sys;s=json.load(open(sys.argv[1]));print(round(sum(b['points'] for b in s['score_breakdown']),1),s['final_score'])" hosting/results/runs/<run>/summary.json
   python3 -c "import json,sys;print(sum(json.loads(l)['score_delta'] for l in open(sys.argv[1])))" hosting/results/runs/<run>/events.jsonl
   ```
2. **`map` and `semantics`** explain the map and object points: coverage, wall quality, landmarks found, false objects.
3. **`collision_log`** names each wall piece touched. Several pieces at the same moment are one bump, but the rules charge each piece.
4. **`physics.needs_review`, `graph_review`, `topic_review` and `rule_violations`** must all be empty or false. If one is not, a person must look at that run before its score counts.
5. **`stack_integrity.status`** is `ok`, and `host.json` shows `sandboxed: true` and `official: true` (if `false`, its
   `insecure_reasons` or `error` says why, and the run does not count). `api_calls` shows how often the team asked for
   the mission info: thousands a second is a team bug that wastes its own CPU, not a score matter.
6. **`host.json` → `model_check`** lists every file in the team's `models/` with its `status` (`ok` with the `level` 1/2/3, `fail` with the reason, or `data` for a plain data file) and the kit versions used.

### 9d. Judge the code, not only the score

After every run, decide which of these explains the result, and write down the evidence (a log line, a number, a file and line):

| Verdict | What it looks like | What to do |
|---|---|---|
| **A. Good code, but the referee scored it wrongly** | the team did what the rules ask, but the points do not follow `RULES.md` | report it to the organisers, with the event and the rule |
| **B. Good code, but code and machine do not fit together** (the "handshake") | a file path, library, topic, frame or setting the team relies on is missing or different here; the code waits, retries or falls back, and the run slows down or drains its points | fix the machine to match the official setup and run again; the first score does not count |
| **C. Weak code on a working machine** | `team.log` shows the team's own logic or settings failing: plans that keep failing, recovery loops, nothing detected although the sensors work | the score counts; tell the team the evidence after the event |
| **D. Code that breaks the rules** | ground truth typed in (section 9a), forbidden topics, direct simulator access | disqualified on that world (RULES §5) |

Several can be true at once. Settle B first: rerun on a fixed machine before judging C, or the team is blamed for your machine.

Signs of B and C in `team.log`:

```bash
grep -c "worldToMap failed\|Failed to create plan\|Goal failed" team.log      # planner trouble: team settings (C), unless every goal fails at once (B)
grep -i -E "not found|No module|cannot open|Couldn't open|Error loading" team.log | sort | uniq -c   # missing files or libraries (B)
grep -i -E "Loaded|ready" team.log                                             # what the team's nodes say they loaded
```

A log of many megabytes full of the same error means CPU is going into logging instead of driving. That is the team's
settings (C), but it can make a weaker machine fall behind.

### 9e. Team problem or machine problem?

A team's own mistakes count. A difference between your machine and the official one does not: fix the machine and run the team again. Cases seen so far:

| What you see | Cause | Whose | What to do |
|---|---|---|---|
| `team.log`: `Error loading XML file: /opt/ros/jazzy/share/nav2_bt_navigator/...`, `Action server is inactive. Rejecting the goal.`, the rover never moves, `IDLE` −10 every minute | Nav2 not installed with `apt` (section 1) | machine | install Nav2 with `apt`, run again |
| The run is refused: `this machine lacks the official ML kit` | the kit is not installed, or the wrong version | machine | install it (section 1), run again |
| `model check: ... DOES NOT LOAD` in the run output, and the team detects few or no people | the team's model is a pickle (`.pt`, `.pkl`, `.joblib`), a format outside the three levels, or a broken file | team | the score counts (RULES §6) |
| `Nav failure` / `rotating to clear local costmap` over and over, `IDLE` −10 every minute | the team's navigation settings or recovery code | team | the score counts |
| `LATE_REPORT` −20 at a person the team never detected | the rover stood within 2 m of a person for 10 s | rule, scored as written | the score counts; note it in the findings log (section 11) if you think the rule is unfair |
| Two `COLLISION` −10 within a second | one bump touching two wall pieces, each charged | rule (v1.4), scored as written | the score counts |
| The run stops at start-up with no `summary.json` | team code crashed, or the run was stopped | read `team.log` | a crash in their code is their result; a machine problem means run again |

## 10. Troubleshooting

| Message | What to do |
|---|---|
| `the organiser stack is not built yet` | run `setup` |
| `does not match its seal` | `git status`, restore the files, run `setup` again |
| `a simulation is already running` | wait, or `python3 hosting/sparkx_host.py stop`; close any other Gazebo you started |
| `simulator / referee did not come up` | read `hosting/results/team_logs/<run>/organiser.log`; usually memory or the GPU |
| `the team software exited during start-up` | read `team.log` in the same folder: an error in the team's code |
| `navigation did not become active` | relaunch once; if it repeats with the team's `team.yaml`, their Nav2 settings are broken |
| `bubblewrap ... does not work` | `sudo apt install bubblewrap`, or set `"sandbox": "off"` only for a test run |
| `Error loading XML file: /opt/ros/...` in `team.log` | Nav2 is not installed with `apt`: section 1, then run the team again |
| `this machine lacks the official ML kit` / `the official ML kit is <numpy, cv2 or onnxruntime> <version>, this machine has ...` | install the kit as in section 1, then run the team again; the refused run has no score |
| `this machine is not safe for scored runs: ...` | section 3, "Secure the machine": run `secure_setup.sh` with sudo and set `team_user`. Each reason line says what is missing. `--unofficial` runs a test that never counts |
| `world "<name>" is not salted (plain seed)` | the world was made without `new-world` (or with `--practice`): make a competition world with `new-world` and no `--seed` (section 7) |
| `refused: seed ... is small enough to guess` | leave `--seed` out of `new-world`; the tool draws a random 63-bit seed |
| `model check: DOES NOT LOAD (loading the models took over 180 s / ran out of the team's memory)` | the team's models are too slow or too big for the kit and the team's memory: their responsibility, the run is scored |
| `record refused: the mission is over` in `team.log` | the team submitted its record after the time limit or after `EndMission`. The record is frozen at the finish; the last record handed in before it counts. The team must submit, then end |
| `record refused: at most one submission per second` in `team.log` | the team submits in a loop: only one record per second is accepted. Harmless if a later one got through |
| `REVIEW NEEDED: ... publishers on referee topics N` | the team's software published on `/sparkx/mission/status`, `events` or `hints` (it may only read them). It moves no points; look at `summary.json` `topic_review` and judge whether it was meant to mislead someone watching |
| `model check: <file>: DOES NOT LOAD` | the team's model does not work with the kit: their responsibility, the run is scored (RULES §6). Tell the team the reason printed |

## 11. Findings log

Every evaluator adds a line here when a run shows something new: a machine difference, a rule that scored an
honest team strangely, or a check that was missing. Add the date, what you saw, the cause, and what to do.
Report anything that looks like a way to cheat to the organisers privately, not here.

| Date | Seen in | Finding | What to do |
|---|---|---|---|
| 2026-11-20 | a team's run on `practice_small_day` | The evaluation laptop had Nav2 in a private folder, not in `/opt/ros/jazzy`. The team's `team.yaml` named a behaviour-tree file there, so its navigator never started. | Install Nav2 with `apt` (section 1). Run the team again. |
| 2026-11-20 | the same team | `onnxruntime` was not installed, so the team's YOLO model never loaded and it ran on thermal only. | Install the ML libraries system-wide (section 1). Run the team again. |
| 2026-11-20 | the same team | One bump into a building cost −20 (two wall pieces), and −20 for standing 1.7 m from a person the rover had not detected. | Scored as the rules say. Both are under review by the organisers. |
| 2026-11-20 | the same team | The code held the four survivor positions of `practice_small_day` (copied from its answer file) as waypoints. The referee did not notice. | Always run the position check in section 9a. Judge teams on secret worlds only. |
| 2026-11-21 | the ML question behind that team | The rules said "the organisers publish the list" of libraries, but no list existed, so teams guessed. Seven runtimes were compared (ONNX Runtime, OpenCV DNN apt and pip, OpenVINO, PyTorch + Ultralytics, LiteRT, NCNN, scikit-learn). | Official ML kit = `onnxruntime` 1.32.0 CPU plus ONNX models (RULES §6). The tool now checks every model before the run. |
| 2026-11-20 | the same team | The survivor detector ran only on the YOLO model's output, with no thermal-only fallback, so without `onnxruntime` it could never find anyone. Planner settings (tolerance 5 m, A*) wrote 81,900 errors in 15 minutes. | B (library) plus C (settings): fix the machine, run again, then judge. |
| 2026-11-21 | the same team | Their `yolov8n.onnx` is the stock pre-trained COCO model: output `[1, 84, 8400]` (4 box values + 80 COCO classes), and the code reads class 0 ("person in COCO"). Not trained by the team, and it cannot tell a person from a mannequin. The model check only proves a model loads, not that the team trained it. | Print each model's input and output shapes (`model_check` in `host.json`, or the self-test). An output with 80 classes, or a file whose hash matches a public release, is an unchanged pre-trained model: RULES §6 asks for a model the team trained. Note it in the verdict (C, or D if the rules are tightened). |
| 2026-11-21 | the ML kit decision, second step | ONNX alone forced every team into the hardest route (export, hand-written pre-processing and box filtering), and small classifiers stored as plain numbers, the simplest models that work, were not allowed. The kit now has three levels: plain numbers for numpy, OpenCV `cv2.ml` files, and ONNX; pickles are forbidden. The model check runs the stack's `tools/model_selftest.py --json`, so teams and evaluators see the same result. | In `host.json`, `model_check.models[]` has `status` (`ok`, `fail`, `data`) and `level` per file. `data` means a plain data file (names, a calibration table) that is not a model: nothing to judge. |
| 2026-11-21 | the same team, run 3 (`practice_small_day`, kit installed, team memory 1600M) | With the kit present the model check passed, `team.log` showed `Loaded ONNX model`, and the score went from −52 to 265 (1/4 rescued, home in time, map 0.88). The team found 3 of 4 people, but its own code reports only within 1.80 m while the referee accepts 2 m: it stopped at 1.81–1.83 m, waited 8 s, then abandoned two people for good. | When a team finds people but rescues few, grep `team.log` for its own distance or timing checks before suspecting the referee. A stricter check in team code is the team's problem (verdict C). |
| 2026-11-21 | this laptop's `host_config.json` | `team_memory` was 1000M while RULES §6 promises 8 GB. Raised to 1600M for run 3 (no out-of-memory kill). | Give teams the announced memory. If the machine cannot, note the limit in `host.json` and the verdict, and treat an out-of-memory kill as a machine problem. |
| 2026-11-22 | 17 runs of two submissions on practice, fresh and held-back worlds | The same code on the same unseen world scored 166 and 403 (one rescue more, plus the return bonus). One run per world is not enough to rank teams; a team that does well on `practice_small_day` can fall below zero on a medium world (221 on a small world, −183 on a held-back medium world). | Run every team at least twice per world and report the mean and the spread; judge on worlds the team has never had (fresh seeds), not on practice worlds. |
| 2026-11-23 | the evaluator tool, v1.4 hardening | Scored runs now need the secured machine (section 3) and a world made with `new-world`; everything else runs only with `--unofficial` and stays off the leaderboard. A run that fails part-way is marked unofficial too. Team software sees an empty `/media`, `/mnt`, `/srv` and `/run`, no camera or sound devices, and its own message queues; it is told the world is called `competition`. Model files are checked inside the team's memory limit. `summary.json` has two new review fields: `topic_review` (team publishers on the referee's topics) and `api_calls`. | Run `secure_setup.sh` before any scored run. Keep USB drives with submissions unplugged anyway. Make competition worlds only with `new-world` and back up `~/.sparkx_organiser/world_salt` privately. Read `topic_review` like `graph_review` |
| 2026-11-24 | referee, scoring bug fixes (approved by the organisers) | Fire costs −2 for every whole second inside a hazard zone, also when updates arrive less often than once a second (before, a slow update rate lost charges), and only once where two fires overlap (before, once per fire). Each event's points now show how far it moved the rounded total, so the events add up to `final_score` exactly (before, each event was cut to a whole number and a run could show 448 in events against 449 final). The final `MAP_QUALITY` and `SEMANTIC_RECORD` points are now written to `events.jsonl` too. A map whose rotation is not a finite number is refused, like one with a broken origin. Health still drops for each fire the rover is in. | Runs before this date can differ by a few points from a rerun under the new referee; compare like with like. A difference between the events and `final_score` is now a fault to report |

## Updating

When the organisers publish a new release:

1. `git pull` (on this branch);
2. `python3 hosting/sparkx_host.py setup` again;
3. compare the printed fingerprint with the announced one.

Results of runs made on the old release stay in `hosting/results/` and remain on the leaderboard.
