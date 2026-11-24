"""TEAM FILE 2 of 4 - memory.py                                       (you may edit this file)

STARTER VERSION. This file shows the inputs and outputs of the memory node. It remembers every
detection as a separate object (no fusing) and cannot resolve a clue: both are yours to write.

WHAT THIS FILE MUST DO
    1. Semantic memory node: fuse repeated detections into persistent objects in the "map" frame,
       so the same survivor, marker or landmark is one record, not hundreds.
    2. Clue resolution (`resolve`, for mission.py): turn a referee clue such as "about 15 m west of
       marker 12" into a place on your own map to go and search.

    Inputs:   /perception/detections   vision_msgs/Detection3DArray (from perception.py)
              /team/memory/update      std_msgs/String, JSON {"id": ..., "status": ..., "survivor_id": ...}
                                       (mission.py can mark an object RESCUED / REJECTED with this)
    Outputs:  /team/semantic_map       sparkx_interfaces/SemanticMap, at least every 2 s, frame "map"   (JUDGED)
              /team/keepout            sensor_msgs/PointCloud2 in "map" (optional): points listed here
                                       are treated as obstacles by the navigation costmaps (team.yaml,
                                       observation source "keepout"). Use it to keep the rover away
                                       from people (touching one costs 50) and from fires.

WHAT THE JUDGES LOOK AT
    The semantic record is scored at the end of the run: survivors and landmarks placed within 2 m
    of where they really are score, objects that do not exist cost. One record per real object.
"""
import json
import math

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from vision_msgs.msg import Detection3DArray

from sparkx_interfaces.msg import SemanticMap, SemanticObject

MAX_OBJECTS = 200       # the starter does not fuse, so it must not grow without limit


def resolve(hint, objects, start_heading_enu_rad):
    """Turn a clue into a search area on your map: return (x, y, radius_m), or None if it cannot be
    resolved yet (for example because the marker it names has not been seen).

    `hint` is a sparkx_interfaces/Hint, `objects` the SemanticObject list of this node,
    `start_heading_enu_rad` comes from GetMissionInfo.

    The marker part of a clue: the person is `hint.marker_distance_m` metres from marker
    `hint.marker_id`, on compass bearing `hint.marker_bearing_deg` (0 = north, 90 = east).
    With a = pi/2 - radians(bearing) - start_heading_enu_rad, the point in your map frame is
        marker_position + distance * (cos a, sin a)
    and the person is within 2.5 m of it (docs/INTERFACES.md, section 4).

    TODO: find the marker (or the landmark) in `objects` and compute the search area."""
    return None


class SemanticMemory(Node):
    def __init__(self):
        super().__init__('sparkx_semantic_memory')
        self.objects = []            # SemanticObject list
        self.create_subscription(Detection3DArray, '/perception/detections', self.on_detections, 20)
        self.create_subscription(String, '/team/memory/update', self.on_update, 20)
        self.pub = self.create_publisher(SemanticMap, '/team/semantic_map', 10)
        self.create_timer(1.0 / self.declare_parameter('publish_rate_hz', 1.0).value, self.publish)
        self.get_logger().info('memory node ready (starter version: no fusing, no clue resolution)')

    def on_detections(self, msg):
        """TODO: fuse. A real memory decides whether a detection is an object it already knows
        (same class, close by) and updates that record instead of adding a new one."""
        for det in msg.detections:
            if not det.results or len(self.objects) >= MAX_OBJECTS:
                continue
            h = det.results[0]
            cls, _, rest = h.hypothesis.class_id.partition(':')
            o = SemanticObject()
            o.id = f'{cls}_{len(self.objects) + 1}'
            o.object_class = cls
            if cls in ('sign', 'marker'):
                o.label = rest                       # sign text or marker number
            else:
                o.color = rest
            o.position = h.pose.pose.position
            o.confidence = float(h.hypothesis.score)
            o.num_observations = 1
            o.status = SemanticObject.STATUS_TENTATIVE
            self.objects.append(o)

    def on_update(self, msg):
        """mission.py reports what became of an object: {"id": "survivor_3", "status": "RESCUED", "survivor_id": "S02"}"""
        try:
            u = json.loads(msg.data)
        except ValueError:
            return
        for o in self.objects:
            if o.id == u.get('id'):
                o.status = u.get('status', o.status)
                o.survivor_id = u.get('survivor_id', o.survivor_id)

    def publish(self):
        m = SemanticMap()
        m.header.frame_id = 'map'
        m.header.stamp = self.get_clock().now().to_msg()
        m.objects = self.objects
        self.pub.publish(m)


def distance(a, b):
    """Horizontal distance between two geometry_msgs/Point."""
    return math.hypot(a.x - b.x, a.y - b.y)


def main():
    rclpy.init()
    node = SemanticMemory()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
