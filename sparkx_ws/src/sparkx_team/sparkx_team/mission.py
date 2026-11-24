"""TEAM FILE 3 of 4 - mission.py                                      (you may edit this file)

STARTER VERSION. This file shows every call a mission node needs and contains NO strategy: the
rover does not explore, does not look for anybody and does not follow clues. That part is yours.

WHAT THIS NODE MUST DO
    Decide what the rover does next: where to explore, when to approach a survivor, how to follow
    a clue, when to go home. It talks to the referee and drives the rover.

HOW THE ROVER TALKS TO THE REFEREE (docs/INTERFACES.md - these names cannot change)
    you receive
        /sparkx/mission/status           MissionStatus   state WAITING / RUNNING / PAUSED / FINISHED, time left, score
        /sparkx/mission/events           MissionEvent    every rescue, penalty, aftershock, time warning
        /sparkx/mission/hints            Hint            a clue, released when a rescue is confirmed
    you call
        /sparkx/mission/get_info         GetMissionInfo        limits of this run (radius, dwell, time, ...)
        /sparkx/mission/report_survivor  ReportSurvivor        "there is a person at (x, y)" -> confirmed or rejected
        /sparkx/mission/submit_record    SubmitMissionRecord   your map + semantic memory + clue log
        /sparkx/mission/end              EndMission            "I am finished" (return bonus only inside the base zone)
    you publish (judged - keep them)
        /team/behavior_state  BehaviorState  at least once a second
        /team/clues           ClueArray      status of every clue you received

HOW THE ROVER MOVES
    go_to(x, y, yaw)   sends a goal to Nav2 (`navigate_to_pose`, configured in team.yaml); Nav2 plans
                       a path on the SLAM map and drives it.
    drive(v, w)        publishes geometry_msgs/Twist on /cmd_vel yourself. The platform limits it to
                       1.0 m/s and 1.5 rad/s, passes it on only while the mission is RUNNING, and
                       stops the rover when no command arrived for 0.5 s.
    All positions are in the `map` frame: origin = where the rover started, x = forward at start.

RULES YOUR DECISIONS HAVE TO RESPECT (docs/RULES.md has all of them)
    * A rescue is confirmed only if the rover has stood still for 2 s, is within 2.0 m of the person,
      has a clear view of them and reports their position to within 1 m. A rejected report costs 25.
    * REPORT WINDOW: once the rover is within 2.0 m of a person with a clear view, the rescue must be
      confirmed within 10 s. Staying longer without a confirmed rescue costs 20 (once per person).
    * IDLE LIMIT: every full 60 s in which the rover does not move 0.5 m costs 10.
    * The run ends at the time limit. The return bonus needs EndMission called inside the base zone.

WHAT THE DEMO BELOW DOES (parameter `demo: true` in team.yaml)
    waits for RUNNING -> asks the referee for the mission limits -> drives 3 m forward with Nav2 ->
    drives back to the start -> submits its (empty) record -> ends the mission inside the base zone.
    It never calls report_survivor, because it has not found anybody. Replace `decide()`.
"""
import math

import rclpy
import tf2_ros
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PointStamped, PoseStamped, Twist
from nav2_msgs.action import NavigateToPose
from nav_msgs.msg import OccupancyGrid
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy

from sparkx_interfaces.msg import BehaviorState, ClueArray, ClueStatus, Hint, MissionEvent, MissionStatus, SemanticMap
from sparkx_interfaces.srv import EndMission, GetMissionInfo, ReportSurvivor, SubmitMissionRecord

RUNNING = MissionStatus.RUNNING


class Mission(Node):
    def __init__(self):
        super().__init__('sparkx_mission')
        self.demo = self.declare_parameter('demo', True).value
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE)

        # ---- what the referee tells you
        self.status = None          # latest MissionStatus
        self.info = None            # GetMissionInfo response (asked for once)
        self.hints = {}             # hint_id -> Hint
        self.create_subscription(MissionStatus, '/sparkx/mission/status', self.on_status, 5)
        self.create_subscription(MissionEvent, '/sparkx/mission/events', self.on_event, 20)
        self.create_subscription(Hint, '/sparkx/mission/hints', self.on_hint, QoSProfile(
            depth=50, durability=DurabilityPolicy.TRANSIENT_LOCAL, reliability=ReliabilityPolicy.RELIABLE))
        self.cli_info = self.create_client(GetMissionInfo, '/sparkx/mission/get_info')
        self.cli_report = self.create_client(ReportSurvivor, '/sparkx/mission/report_survivor')
        self.cli_submit = self.create_client(SubmitMissionRecord, '/sparkx/mission/submit_record')
        self.cli_end = self.create_client(EndMission, '/sparkx/mission/end')

        # ---- what your own stack tells you
        self.grid = None            # latest nav_msgs/OccupancyGrid from SLAM (frame "map")
        self.objects = []           # latest SemanticObject list from memory.py
        self.create_subscription(OccupancyGrid, '/map', lambda m: setattr(self, 'grid', m), latched)
        self.create_subscription(SemanticMap, '/team/semantic_map', lambda m: setattr(self, 'objects', list(m.objects)), 5)
        self.tf = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf, self)

        # ---- what you send
        self.pub_state = self.create_publisher(BehaviorState, '/team/behavior_state', 5)
        self.pub_clues = self.create_publisher(ClueArray, '/team/clues', 5)
        self.pub_cmd = self.create_publisher(Twist, '/cmd_vel', 5)
        self.nav = ActionClient(self, NavigateToPose, 'navigate_to_pose')
        self.nav_handle = None      # goal handle of the navigation goal that is running
        self.nav_result = None      # None while driving, then True (arrived) or False (failed / cancelled)

        self.state, self.detail, self.target = 'WAIT_START', '', (0.0, 0.0)
        self.busy = False           # a referee call is on its way; wait for its answer before deciding again
        self.create_timer(0.5, self.step)
        self.get_logger().info('mission node ready (starter version: no strategy inside)')

    # ------------------------------------------------------------------ referee -> you
    def on_status(self, msg):
        self.status = msg

    def on_event(self, msg):
        """Everything the referee decides arrives here, e.g. RESCUE_CONFIRMED, RESCUE_REJECTED,
        LATE_REPORT, IDLE, COLLISION, AFTERSHOCK (a street may now be blocked), TIME_WARNING."""
        self.get_logger().info(f'referee event {msg.type}: {msg.description} ({msg.score_delta:+d})')

    def on_hint(self, hint):
        """A clue. It never contains coordinates. `hint.marker_id`, `hint.marker_bearing_deg` and
        `hint.marker_distance_m` place the person relative to a numbered marker that your rover must
        have seen; docs/INTERFACES.md section 4 has the formula for your map frame."""
        if hint.hint_id not in self.hints:
            self.hints[hint.hint_id] = hint
            self.get_logger().info(f'clue {hint.hint_id}: {hint.text}')
        # TODO: turn the clue into a place to search (memory.resolve) and go there

    # ------------------------------------------------------------------ you -> referee
    def ask_info(self):
        """Limits of this run: info.rescue_radius_m, stop_dwell_s, report_tolerance_m, report_window_s,
        idle_limit_s, time_limit_s, base_zone_radius_m, start_heading_enu_rad, markers_total, ..."""
        if not self.cli_info.service_is_ready():
            return
        self.busy = True
        self.cli_info.call_async(GetMissionInfo.Request()).add_done_callback(self._on_info)

    def _on_info(self, future):
        self.busy = False
        self.info = future.result()
        i = self.info
        self.get_logger().info(
            f'mission info: rules {i.rules_version}, time limit {i.time_limit_s:.0f} s, rescue radius {i.rescue_radius_m} m, '
            f'stand still {i.stop_dwell_s} s, report window {i.report_window_s:.0f} s, idle limit {i.idle_limit_s:.0f} s, '
            f'{i.markers_total} markers ({i.marker_dictionary})')

    def report_survivor(self, x, y, confidence=1.0, source='thermal+depth'):
        """Tell the referee there is a person at (x, y) in your map frame. Call it only when the rover
        has been standing still for 2 s within 2 m of the person, with a clear view. The answer
        arrives in on_report()."""
        req = ReportSurvivor.Request()
        req.estimated_position = PointStamped()
        req.estimated_position.header.frame_id = 'map'
        req.estimated_position.header.stamp = self.get_clock().now().to_msg()
        req.estimated_position.point.x, req.estimated_position.point.y = float(x), float(y)
        req.detection_source, req.confidence = source, float(confidence)
        self.busy = True
        self.cli_report.call_async(req).add_done_callback(self.on_report)

    def on_report(self, future):
        self.busy = False
        res = future.result()
        # res.success, res.result_code (ReportSurvivor.Request.CONFIRMED, NOT_STOPPED, NO_SURVIVOR_IN_RANGE,
        # NO_LINE_OF_SIGHT, POSITION_MISMATCH, ALREADY_RESCUED, RATE_LIMITED ...), res.survivor_id,
        # res.score_delta, res.hints (the clues this rescue released; they also arrive in on_hint)
        self.get_logger().info(f'report answered: {res.message} ({res.score_delta:+d})')
        # TODO: remember the rescue, or decide what to do about a rejection

    def submit_record(self):
        """Hand in the map, the semantic memory and the clue log. The last submission counts."""
        req = SubmitMissionRecord.Request()
        if self.grid is not None:
            req.map = self.grid
        req.objects = self.objects
        req.clues = self.clue_statuses()
        req.rescue_order = []       # TODO: referee survivor ids in the order you rescued them
        self.busy = True
        self.cli_submit.call_async(req).add_done_callback(self._on_simple_answer)

    def end_mission(self, reason='COMPLETED'):
        """Declare the mission finished. The return bonus is paid only inside the base zone."""
        self.busy = True
        self.cli_end.call_async(EndMission.Request(reason=reason)).add_done_callback(self._on_simple_answer)

    def _on_simple_answer(self, future):
        self.busy = False
        self.get_logger().info(f'referee answered: {future.result().message}')

    def clue_statuses(self):
        """One ClueStatus per clue received. TODO: fill in what you did with each clue."""
        return [ClueStatus(hint_id=h, status=ClueStatus.PENDING) for h in self.hints]

    # ------------------------------------------------------------------ moving
    def pose(self):
        """(x, y, yaw) of the rover in the map frame, or None while localisation is starting."""
        try:
            t = self.tf.lookup_transform('map', 'base_link', rclpy.time.Time()).transform
        except Exception:
            return None
        q = t.rotation
        return t.translation.x, t.translation.y, math.atan2(2 * (q.w * q.z + q.x * q.y), 1 - 2 * (q.y * q.y + q.z * q.z))

    def go_to(self, x, y, yaw=0.0):
        """Ask Nav2 to drive to (x, y) and face `yaw`. Poll `self.nav_result`: None = still driving."""
        if not self.nav.server_is_ready():
            self.nav_result = False          # navigation is still starting: try again later
            return
        goal = NavigateToPose.Goal()
        goal.pose = PoseStamped()
        goal.pose.header.frame_id = 'map'
        goal.pose.header.stamp = self.get_clock().now().to_msg()
        goal.pose.pose.position.x, goal.pose.pose.position.y = float(x), float(y)
        goal.pose.pose.orientation.z, goal.pose.pose.orientation.w = math.sin(yaw / 2), math.cos(yaw / 2)
        self.nav_result, self.nav_handle, self.target = None, None, (float(x), float(y))
        self.nav.send_goal_async(goal).add_done_callback(self._on_goal_answer)

    def _on_goal_answer(self, future):
        handle = future.result()
        if not handle.accepted:
            self.nav_result = False
            return
        self.nav_handle = handle
        handle.get_result_async().add_done_callback(
            lambda f: setattr(self, 'nav_result', f.result().status == GoalStatus.STATUS_SUCCEEDED))

    def cancel_navigation(self):
        if self.nav_handle is not None:
            self.nav_handle.cancel_goal_async()
            self.nav_handle = None

    def drive(self, v, w):
        """Direct command: v m/s forward, w rad/s turning left. Repeat it at least every 0.5 s."""
        cmd = Twist()
        cmd.linear.x, cmd.angular.z = float(v), float(w)
        self.pub_cmd.publish(cmd)

    # ------------------------------------------------------------------ deciding
    def set_state(self, state, detail=''):
        if state != self.state:
            self.get_logger().info(f'{self.state} -> {state} {detail}')
        self.state, self.detail = state, detail

    def step(self):
        """Runs twice a second: publish the judged topics, then decide."""
        b = BehaviorState()
        b.header.stamp = self.get_clock().now().to_msg()
        b.state, b.detail = self.state, self.detail
        b.target.x, b.target.y = self.target
        self.pub_state.publish(b)
        c = ClueArray()
        c.header = b.header
        c.clues = self.clue_statuses()
        self.pub_clues.publish(c)
        if self.status is None or self.status.state != RUNNING or self.busy:
            return                           # not started yet, paused, finished, or waiting for the referee
        self.decide()

    def decide(self):
        """YOUR STRATEGY GOES HERE. Useful inputs: self.pose(), self.grid (the SLAM map),
        self.objects (survivors, markers and landmarks from memory.py), self.hints,
        self.status.remaining_s, self.info.

        What is below is only the demo described at the top of this file."""
        if not self.demo:
            self.set_state('IDLE', 'no strategy implemented')
            return
        if self.state == 'WAIT_START':
            if self.info is None:
                return self.ask_info()
            self.set_state('DEMO_OUT', 'driving 3 m forward')
            self.go_to(3.0, 0.0)
        elif self.state == 'DEMO_OUT':
            if self.nav_result is False:     # refused or failed: send the goal again
                self.go_to(3.0, 0.0)
            elif self.nav_result:
                self.set_state('RETURN_TO_BASE', 'driving back to the start')
                self.go_to(0.0, 0.0, math.pi)
        elif self.state == 'RETURN_TO_BASE':
            if self.nav_result is False:
                self.go_to(0.0, 0.0, math.pi)
            elif self.nav_result:
                self.set_state('SUBMIT', 'handing in the record')
                self.submit_record()
        elif self.state == 'SUBMIT':
            self.set_state('DONE', 'ending the mission')
            self.end_mission('COMPLETED')


def main():
    rclpy.init()
    node = Mission()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
