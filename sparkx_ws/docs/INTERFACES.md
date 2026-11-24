# SparkX Competition Interfaces (rules v1.4)

Team software may use only what is listed here. Anything under `/sparkx/referee_private/`, and
Gazebo transport itself, is off limits: the referee watches the ROS graph and a run that touches
those topics is disqualified (`docs/RULES.md`, section 5).

## 1. The robot

Husky A200-class four-wheel skid-steer rover, 0.99 × 0.67 m, ~50 kg, electronics bay and sensor
mast on the deck. TF tree: `base_footprint → base_link → {lidar_link, camera_link →
camera_color_optical_frame, thermal_link → thermal_optical_frame, imu_link, wheels}`.

| Sensor | Modelled on | Specification | Topic(s) |
|---|---|---|---|
| 3D LiDAR | Ouster OS1-32 | 32 beams × 1024, 360° × 45°, 0.3–60 m, 10 Hz, σ = 1 cm | `/lidar/points` (`PointCloud2`: x, y, z, intensity, ring) |
| RGB-D camera | RealSense D455 | 640 × 480, 87° HFOV, 15 Hz, depth 0.3–12 m, pitched 7° down | `/camera/color/image_raw` (`rgb8`), `/camera/depth/image_raw` (`32FC1`, metres), `/camera/depth/points`, `/camera/color/camera_info` |
| Thermal camera | FLIR Boson 320 | 320 × 256, 57° HFOV, 9 Hz, `mono16`, **kelvin = value × 0.01**, range 253–653 K | `/thermal/image_raw`, `/thermal/camera_info` |
| IMU | 9-DoF MEMS | 200 Hz, with noise and bias | `/imu/data` |
| Wheel odometry | — | 50 Hz, drifts ~5 % in yaw | `/wheel/odom` |
| Joint states, clock | — | — | `/joint_states`, `/tf_static`, `/clock` (`use_sim_time: true`) |

Thermal signatures: people 303–312 K, burnt-out cars 330–360 K, ambient ~298 K. Fires burn at
750–900 K, above the camera's 653 K ceiling, so a fire shows as a **saturated** blob (≈ 653 K).
Mannequin decoys are at ambient temperature. In worlds with `smoky` lighting there are also heat
sources at 304–313 K that are not people (drums, beams, lockers the size of a person; `docs/RULES.md`,
section 1): warm and of the right size is not yet a survivor.

## 2. What the team stack must publish

| Topic / TF | Type | Notes |
|---|---|---|
| `/cmd_vel` | `geometry_msgs/Twist` | limited to 1.0 m/s, 1.5 rad/s; passed to the motors only while RUNNING; 0.5 s timeout |
| TF `map → odom → base_link` | tf2 | used for the drift-free rescue check and the localisation score |
| `/map` | `nav_msgs/OccupancyGrid` | frame `map`, transient-local; **the `map` origin must be the start pose** (x forward at start) |
| `/team/semantic_map` | `sparkx_interfaces/SemanticMap` | ≥ 0.5 Hz, frame `map` |
| `/team/clues` | `sparkx_interfaces/ClueArray` | status of every received clue; a `SEARCHING` entry's `search_center` + `search_radius_m` (≤ 8 m, centre jumps ≤ 3) decide the clue-led bonus (`RULES.md` §2) |
| `/team/behavior_state` | `sparkx_interfaces/BehaviorState` | ≥ 1 Hz |

In the supplied stack the locked launch file starts EKF, SLAM Toolbox and Nav2 (tuned through
`team.yaml`), which provide `/map`, the TF chain and the `navigate_to_pose` action; the three team
nodes provide the rest. See `docs/TEAM_GUIDE.md`.

## 3. Referee API

| Name | Type | Notes |
|---|---|---|
| `/sparkx/mission/status` | `MissionStatus`, 2 Hz | state WAITING / RUNNING / PAUSED / FINISHED, time, score, health, counters (collisions, rejected and late reports, idle penalties), `finish_reason` |
| `/sparkx/mission/events` | `MissionEvent` | rescues, penalties (`RESCUE_REJECTED`, `LATE_REPORT`, `IDLE`, `COLLISION` …), `AFTERSHOCK`, `TIME_WARNING` (300, 120, 60 s left), `RULE_VIOLATION`, `STACK_INTEGRITY` … |
| `/sparkx/mission/hints` | `Hint`, transient-local | clues, published when released |
| `/sparkx/mission/get_info` | `GetMissionInfo` | limits (rescue radius, dwell, report window, idle limit, time limit) and the published vocabulary. Ask once at the start: it never changes. In an evaluation `world_name` (here and in `MissionStatus`) is `competition`, not the world's real name |
| `/sparkx/mission/get_hints` | `GetHints` | every clue released so far |
| `/sparkx/mission/report_survivor` | `ReportSurvivor` | rescue confirmation; conditions in `docs/RULES.md` section 2 and in the `.srv` file |
| `/sparkx/mission/submit_record` | `SubmitMissionRecord` | final map + semantic memory + clue log; the last submission counts. Submit **before** `EndMission` and before the time limit: once the mission is over the record is frozen and later submissions are refused. At most one submission per second. If never called, the last `/map` and `/team/semantic_map` received before the finish are used |
| `/sparkx/mission/end` | `EndMission` | declares completion; return bonus only inside the base zone |

`finish_reason` is one of `END_MISSION:<reason> (in base | outside base)`, `TIME_LIMIT`,
`ROBOT_DISABLED`, `ABORTED`, `DISQUALIFIED: …`, `SHUTDOWN`.

## 4. Clues (hints)

A `Hint` says where a person is in two ways: relative to a **numbered location marker**, and
(when one applies) relative to a landmark from the published vocabulary. It never contains
coordinates, and it is only a lead: the person must still be detected and confirmed.

**Numbered location markers.** A marker is a four-sided beacon on a post, 2.9 m tall. Every side
shows the same ArUco tag (dictionary `DICT_4X4_100`, black square 0.825 m, number printed
underneath). One stands at each street junction and one beside each landmark that a clue can
name; a medium world has about 30. Their positions are not published: the rover must have seen a
marker to use a clue that names it. `GetMissionInfo` gives `marker_dictionary`, `markers_total`
and `marker_tag_size_m`.

| `Hint` field | Meaning |
|---|---|
| `marker_id` | tag number, or −1 if the clue has no marker reference |
| `marker_bearing_deg` | compass bearing from the marker to the person: 0 = north (+Y), 90 = east (+X), rounded to 5° |
| `marker_distance_m` | distance from the marker to the person, rounded to 1 m |

The point this states is within 2.5 m of the person (checked by the generator for every clue). In
your `map` frame, with `h = start_heading_enu_rad` and `a = π/2 − bearing − h`, it is
`marker + distance · (cos a, sin a)`. Example text: *"Someone is trapped inside the building with
the POLICE sign, about 9 m south-south-east of marker 11."*

When no landmark relation applies, `landmark.landmark_class` is `marker`, `landmark.label` is the
tag number and `relation` is the nearest of the four cardinal relations.

**Landmarks** (`LandmarkRef.landmark_class`, with `color` or `label`):

| Class | Appears as |
|---|---|
| `water_tank` | elevated steel tank; red, blue, green, yellow or white |
| `container` | 20 ft shipping container; red, blue, green, yellow, orange, white or gray |
| `tent` | relief tent; blue, white, orange, green or yellow |
| `car` | hatchback (red, white, blue, yellow, green), SUV or pickup (gray) |
| `bus` (gray), `fire_truck` (red), `ambulance` (white), `dumpster` (green) | one design each |
| `sign` | shop sign above a building entrance; `label` is PHARMACY, SCHOOL, HOTEL, BANK, POLICE, CAFE, HOSPITAL or MARKET |
| `fountain`, `crater` | no colour |
| `marker` | numbered location marker; `label` is the tag number |

A landmark used in a clue is the only one of its kind in that world (class + colour, or sign
label) and can be seen from a street within 25 m.

**Relations** — exactly what the world generator guarantees for the target survivor:

| `relation` | Guarantee | `approx_distance_m` |
|---|---|---|
| `inside` | in the same building as the named sign | 0 |
| `beside` | within 4 m of the landmark's footprint | 0 |
| `near` | within 9 m of the landmark's centre | distance, rounded to 1 m |
| `behind` | within 8 m, on the side facing away from the street point nearest to the landmark | distance |
| `opposite` | across a street from the landmark: both within 11 m of the street's centre line, at most 8 m apart along it | distance |
| `north_of`, `south_of`, `east_of`, `west_of` | 5–16 m from the landmark, bearing within ±30° of that direction | distance |

Cardinal directions are world ENU (+X east, +Y north). Your `map` frame is rotated by
`GetMissionInfo.start_heading_enu_rad`: an ENU bearing *b* is map bearing *b − start_heading*.
`area_type` is `room`, `building`, `street`, `rubble` or `open_area`; `people_count` is currently
always 1.

## 5. Lock-down facts a team should know

- The referee publishes the result of its locked-files check as a `STACK_INTEGRITY` event and
  refuses to start a competition run on a modified stack.
- A node that subscribes to or publishes on `/sparkx/referee_private/*` triggers a
  `RULE_VIOLATION` event within about two seconds; in competition the run ends as `DISQUALIFIED`.
- In competition the `/sparkx/admin/*` services do not exist.
