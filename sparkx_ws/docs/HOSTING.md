# Hosting Guide (organisers)

SparkX Disaster Response Challenge — IIIT Allahabad · STEMLearn.AI · Airoot · presented at IIT Bombay Techfest.

> **Running the event from the release folder?** Use `hosting/sparkx_host.py` (next to this
> workspace; described in the release folder's `README.md`). It does sections 1 and 3 below with
> one command or one button: checks a team's zip, places the four files in a clean copy of the
> stack, rebuilds, starts simulator, referee and the team's software with the right settings and
> stores the result. This document describes the pieces it is built from, and the Docker route
> for running team code in a container instead.

## 1. Release the stack to teams

```bash
cd sparkx_ws
colcon build && source install/setup.bash
python3 tools/sparkx_lock.py manifest      # hashes every locked file -> LOCKED_MANIFEST.sha256
python3 tools/sparkx_lock.py verify        # must print "stack integrity: OK"
```

Ship the workspace **with** `LOCKED_MANIFEST.sha256` and `TEAM_FILES.txt`. Keep the fingerprint
that `manifest` prints: it identifies the release, the referee logs it at every start and every
submission records the fingerprint it was built against. Re-run `manifest` whenever you change a
locked file (new practice world, bug fix) and publish the new fingerprint.

The lock-down has three layers. Only the first one is real security; say so to the teams.

| Layer | What it does | Strength |
|---|---|---|
| Submission = four files | `sparkx_lock.py pack` on the team side, `load` on yours: the archive may contain only the paths in `TEAM_FILES.txt` (+ data in `models/`), and you run it inside your own pristine stack | **This is the enforcement.** Whatever else a team edited never runs |
| Integrity check | the referee hashes the locked files against the manifest when it starts, shows the result on the dashboard, writes it to `summary.json`, and in competition mode refuses to start on a modified stack | Catches a wrong or stale stack on *your* machine; a team could defeat it on *theirs*, which is why practice scores are not official |
| `sparkx_lock.py protect` | makes locked files read-only | Stops accidents only |

## 2. Prepare secret worlds

```bash
ros2 run sparkx_worlds generate_world --name final_A --seed "$(python3 -c 'import secrets; print(secrets.randbits(63))')" \
    --salt-file ~/.sparkx_organiser/world_salt --size large --difficulty hard --lighting smoky --out /secure/worlds
```

Use a random 63-bit seed and a private salt file (at least 16 random bytes, kept outside the stack). Without the salt,
a world is only as private as its seed. The evaluator tool's `new-world` does both for you.

Check `/secure/worlds/final_A/private/preview.png` (survivors, clue chains, fires, aftershock
slots). `private/` holds the answers: it stays on the organiser machine and is never mounted into
a team container. Only `public.yaml` may be shared, after the event.

Before using a new world in a scored run, prove it end to end. The self-check reads the answer
sheet, parks the rover at every survivor (clue sources before their targets) and files a perfect
report each time; it passes only if every rescue is confirmed, every clue is released by the right
person, clue-led rescues pay their bonus, the aftershocks spawn and ending at base pays the return
and time bonuses. It takes about two minutes.

```bash
# terminal 1: simulator + referee, no team code
ros2 launch sparkx_bringup practice.launch.py world_dir:=/secure/worlds/final_A baseline:=false
# terminal 2
python3 tools/referee_selfcheck.py --world-dir /secure/worlds/final_A
```

Other organiser checks: `ros2 run sparkx_worlds check_generator` (36 generated worlds, every
guarantee verified) and `ros2 run sparkx_sim sensor_check` (every rover sensor alive and not
blind; run it after any change to the robot model).

## 3. Run a team

```bash
# 1. the team's archive, into a container built from YOUR stack
docker build -t sparkx -f docker/Dockerfile --build-arg REQUIRE_PRISTINE=true .   # once per release
docker/run_team.sh /submissions/roborescuers_submission.zip                        # prints the env for step 2

# 2. simulator + referee on the organiser machine, in a shell with the printed environment
export ROS_DOMAIN_ID=0 GZ_IP=127.0.0.1
ros2 launch sparkx_sim sim.launch.py world_dir:=/secure/worlds/final_A gui:=true
ros2 launch sparkx_referee referee.launch.py world_dir:=/secure/worlds/final_A team_name:=roborescuers \
    competition:=true auto_start:=false dashboard_host:=0.0.0.0 log_dir:=/secure/logs
```

Then open the dashboard, enter the admin token from the referee log and press **Start** once the
team container reports it is ready. `run_team.sh` rejects the archive (and builds nothing) if it
holds anything outside the allow-list; it limits the container to 8 CPUs and 16 GB RAM, drops all
capabilities and runs the team code as an unprivileged user.

`competition:=true` means:

- `require_integrity` — the mission cannot be started unless the stack verifies as `OK`
  (a missing manifest counts as not verified);
- `violation_policy:=disqualify` — any node other than the referee and its bridge that subscribes
  to or publishes on `/sparkx/referee_private/*` ends the run as `DISQUALIFIED` within ~2 s;
- the unauthenticated `/sparkx/admin/*` ROS services are not created; pause, intervention and
  abort are done from the dashboard, which needs the token.

Timing rules (v1.2): the referee raises `LATE_REPORT` (−20, once per survivor) when the rover stays
within the rescue radius of a survivor, with a clear view, for more than 10 s without a confirmed
rescue, and `IDLE` (−10) for every full 60 s without 0.5 m of movement. The values are in
`sparkx_referee/rules.py` (`REPORT_WINDOW_S`, `IDLE_LIMIT_S`, `IDLE_MOVE_M`; 0 switches a rule off).
Changing them changes a locked file: re-seal the stack and send teams the new release.

**Before each scored run, read the first lines of the launch log.** The line
`[sparkx_nav_guard]: navigation active after N s` means the navigation servers came up. If it is
followed by "this guard had to make N lifecycle transition(s)", start-up stalled and the guard
repaired it (the run is valid, the team lost a few seconds). If it never appears, stop and
relaunch: the rover cannot move.

Useful referee arguments: `time_limit_s:=<seconds>` (overrides the world's time limit; use it to
measure how long a mission really takes before you fix the limit for an event), `stack_root:=<path>` (where `TEAM_FILES.txt` and the manifest are, found
automatically inside a workspace or from `$SPARKX_STACK_ROOT`), `trusted_nodes:=name1,prefix*`
(organiser tools that may touch private topics, e.g. `rosbag2_recorder`, or `_ros2cli_*` for `ros2 topic echo`), `dashboard_token:=<token>`,
`hide_survivor_total:=true`. Practice mode (`competition:=false`, the default) only *warns*.

### Dashboard

`http://<organiser>:8080`. It shows ground truth. Bound to `127.0.0.1` (default) it is readable on
the organiser machine without a token; bound to anything else, the data endpoints (`/state`,
`/gt.png`) and every control need the admin token. The **Lock-down** panel shows the integrity
result, the stack fingerprint and every rule violation.

## 4. Network isolation

Team code is untrusted. Three things must be out of its reach: the answer files, Gazebo transport
(which exposes every model pose) and the referee-private ROS topics.

| Threat | Countermeasure | Status |
|---|---|---|
| Reading `private/scenario.yaml` | world folders exist only on the organiser machine; nothing is mounted into the team container | by construction |
| A submission carrying more than the four files | `sparkx_lock.py load` inside `Dockerfile.team`; the image build fails | **tested** (extra file, path traversal, symlink, code in `models/`, missing file, syntax error) |
| Reading or writing `/sparkx/referee_private/*` over ROS | referee graph tripwire → `RULE_VIOLATION` → `DISQUALIFIED` | **tested** (subscriber, publisher, `ros2 topic echo`, a node impersonating the bridge, a node inside a team container) |
| Calling `/sparkx/admin/*` | services absent in competition mode | **tested** |
| Viewing the dashboard from the team side | token required when not bound to loopback | **tested** |
| Gazebo transport from the team container | `GZ_IP=127.0.0.1` on the organiser side **and** the team container on its own Docker network | **tested** with a probe topic, see below |
| Everything else on the host | firewall rules below | **not tested** (needs root) |

**Gazebo transport is the big one.** Measured on the development machine with a probe topic
published on the host and read from a container on the team network:

| Organiser side | Team container | Result |
|---|---|---|
| `GZ_IP` not set | Docker network | topic listed **and read** — ground truth would leak |
| `GZ_IP=127.0.0.1` | Docker network | not listed, not readable |
| `GZ_IP=127.0.0.1` | Docker network, team sets `GZ_RELAY=<host>` | topic *name* listed, data not readable |
| `GZ_IP=127.0.0.1` | `--net=host` (`run_team.sh --simple`) | **read** — host networking shares the loopback |

So: always export `GZ_IP=127.0.0.1` before starting the simulator and the referee, and never use
`--simple` for a scored run. The referee cannot see Gazebo-transport access; in competition mode it
only warns at start-up when `GZ_IP` is not `127.0.0.1`. The probe was a single topic; a full
simulator run through this setup has not been done.

**ROS across the Docker network.** A container on the team network and the host discover each
other with default settings (tested with a small topic; sensor-rate traffic through the Docker
bridge is not measured). `ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST` breaks it, also with
`ROS_STATIC_PEERS` — do not set it. Default discovery also announces on the venue network, so give
every run a `ROS_DOMAIN_ID` the teams do not know in advance, or keep the organiser machine off
shared networks.

**Firewall (recommended, not tested here).** DDS uses UDP; Gazebo transport data and the dashboard
use TCP. Dropping TCP from the team network to the host therefore closes both without touching ROS:

```bash
sudo iptables -I INPUT -s 172.30.77.0/24 -p tcp -j DROP                          # Gazebo data, dashboard, ssh ...
sudo iptables -I INPUT -s 172.30.77.0/24 -p udp --dport 10317:10319 -j DROP      # Gazebo discovery
sudo iptables -I DOCKER-USER -s 172.30.77.0/24 ! -d 172.30.77.0/24 -j DROP       # no route off the team network
```

**Stronger still (recommended for a final, not implemented here).** Run the team container on its
own `ROS_DOMAIN_ID` and relay only the allowed topics and services with `ros-jazzy-domain-bridge`
(not installed on the development machine), so private topics do not exist at all on the team's
domain. The relay list is exactly sections 1–3 of `INTERFACES.md`; note that `/tf` must be relayed
team → organiser (the referee reads the team's `map → base_link`) and `/tf_static` organiser → team.

## 5. Results

Each run writes `<log_dir>/<date>_<team>_<world>/`:

- `summary.json` — `final_score`, `official_score` (0 if disqualified), `disqualified`,
  `rule_violations`, `stack_integrity` (status, fingerprint, changed files), score breakdown, map /
  semantic / localisation metrics, trajectory;
- `events.jsonl`, `reports.jsonl`, `evidence/` (snapshots sent with rescue reports), `team_map.png`.

```bash
ros2 run sparkx_referee leaderboard /secure/logs --csv results.csv --require-integrity --dq-voids-world
```

Total = sum over worlds of the best run per world. A disqualified run counts 0;
`--dq-voids-world` zeroes a world if *any* run on it was disqualified; `--require-integrity` also
zeroes runs made on a modified or unverified stack. The table shows the worst integrity status and
the number of disqualified runs per team.

## 6. Docker

| File | Purpose |
|---|---|
| `docker/Dockerfile` | organiser image: simulator, referee, the locked stack. `--build-arg REQUIRE_PRISTINE=true` fails the build unless the stack verifies; it always contains the official ML kit (numpy 1.26.4, OpenCV 4.6, onnxruntime 1.32.0; RULES §6) and checks those versions |
| `docker/Dockerfile.team` | organiser image + one validated submission, rebuilt `sparkx_team`, unprivileged user, starts only the autonomy stack |
| `docker/run_team.sh` | builds the team image from a submission zip and runs it with CPU / RAM / PID limits |

Both Dockerfiles were built on the development machine (organiser image 7.3 GB; the team image
builds in under a minute on top of it and starts the autonomy stack as user `team`). A full
simulator + referee run *inside* the organiser container has not been tried.

Run the organiser stack itself in Docker with
`docker run --rm -it --net=host -e DISPLAY -v /tmp/.X11-unix:/tmp/.X11-unix sparkx ros2 launch sparkx_bringup practice.launch.py`.

## 7. Hardware notes

Developed on a 20-thread Intel CPU with integrated graphics: real-time factor about 0.9–1.0 with
every sensor on. Use a discrete GPU for large worlds with the GUI.

Memory: a headless medium world with the full stack takes about 3.1 GB, of which 1.5 GB is graphics
memory (on integrated graphics that comes out of system RAM). `textures:=lite` on
`practice.launch.py` / `sim.launch.py` runs the same world with half-resolution textures and takes
about 2.7 GB; the copy is built once into `~/.cache/sparkx`. Use the full textures for scored runs.
If the machine starts swapping, the simulation drops to about half speed. If the simulation runs slower
than real time the mission clock slows with it, so scores stay comparable.
