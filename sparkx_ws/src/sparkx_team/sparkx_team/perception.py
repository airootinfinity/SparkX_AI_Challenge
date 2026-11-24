"""TEAM FILE 1 of 4 - perception.py                                   (you may edit this file)

STARTER VERSION. This file shows how to read every sensor and how to publish a detection. It
detects NOTHING: `detect()` returns an empty list. Finding people, fires, markers and landmarks
is yours to write, and this is where your trained model runs.

WHAT THIS NODE MUST DO
    Turn the rover's sensors into detections of survivors, hazards, numbered markers and landmarks.

    Inputs (the only sensor topics that exist in competition; details in docs/INTERFACES.md):
        /thermal/image_raw        mono16, 320x256, kelvin = value * 0.01     frame thermal_optical_frame
        /camera/color/image_raw   rgb8 640x480                                frame camera_color_optical_frame
        /camera/depth/image_raw   32FC1, metres (0.3 .. 12 m), same view as the colour image
        /thermal/camera_info, /camera/color/camera_info                       intrinsics (K matrix)
        /lidar/points             PointCloud2, if you want it
        TF                        map -> odom -> base_link -> sensor frames
    Output (read by memory.py - keep this contract, or change both files together):
        /perception/detections    vision_msgs/Detection3DArray in the "map" frame, one hypothesis
                                  per detection with class_id =
                                      'survivor' | 'fire' | 'marker:<number>' |
                                      '<landmark_class>:<color>' | 'sign:<LABEL>'
        /perception/snapshot      sensor_msgs/CompressedImage; attach it to a rescue report as evidence

FACTS YOU CAN BUILD ON
    people 303-312 K, burnt-out cars 330-360 K, surroundings ~298 K; fires saturate the thermal
    camera at 653 K; mannequin decoys look like people in the colour image but are cold.
    Numbered markers carry ArUco tags (dictionary DICT_4X4_100, black square 0.825 m wide):
    cv2.aruco reads them from the colour image.

WHERE YOUR TRAINED MODEL GOES
    Put the weights in sparkx_team/models/ (data only). That folder is given to this node as the
    `model_dir` parameter; load them in `load_team_model()`. Formats the evaluation can open: RULES.md
    section 6 (plain numbers for numpy, a cv2.ml model, or ONNX). A small classifier is recommended.
"""
import cv2
import numpy as np
import rclpy
import tf2_ros
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CameraInfo, CompressedImage, Image
from vision_msgs.msg import Detection3D, Detection3DArray, ObjectHypothesisWithPose


class Perception(Node):
    def __init__(self):
        super().__init__('sparkx_perception')
        self.bridge = CvBridge()
        self.model_dir = self.declare_parameter('model_dir', '').value
        self.model = self.load_team_model()

        # ---- latest sensor data (None until the first message arrives)
        self.thermal_k = None       # float32 image, kelvin
        self.rgb = None             # uint8 image, RGB
        self.depth_m = None         # float32 image, metres (NaN / inf where there is no return)
        self.stamp = None           # time stamp of the latest thermal image
        self.K_thermal = None       # 3x3 intrinsics of the thermal camera
        self.K_rgb = None           # 3x3 intrinsics of the colour / depth camera
        self.create_subscription(Image, '/thermal/image_raw', self.on_thermal, qos_profile_sensor_data)
        self.create_subscription(Image, '/camera/color/image_raw', self.on_rgb, qos_profile_sensor_data)
        self.create_subscription(Image, '/camera/depth/image_raw', self.on_depth, qos_profile_sensor_data)
        self.create_subscription(CameraInfo, '/thermal/camera_info',
                                 lambda m: setattr(self, 'K_thermal', np.array(m.k).reshape(3, 3)), 5)
        self.create_subscription(CameraInfo, '/camera/color/camera_info',
                                 lambda m: setattr(self, 'K_rgb', np.array(m.k).reshape(3, 3)), 5)
        self.tf = tf2_ros.Buffer()
        self.tf_listener = tf2_ros.TransformListener(self.tf, self)

        self.pub = self.create_publisher(Detection3DArray, '/perception/detections', 10)
        self.pub_snap = self.create_publisher(CompressedImage, '/perception/snapshot', 2)
        self.create_timer(1.0 / self.declare_parameter('rate_hz', 5.0).value, self.process)
        self.get_logger().info('perception node ready (starter version: detects nothing)')

    # ------------------------------------------------------------------ your trained model
    def load_team_model(self):
        """TODO: load the model you trained from self.model_dir and return it."""
        return None

    # ------------------------------------------------------------------ sensors
    def on_thermal(self, msg):
        raw = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')     # uint16
        self.thermal_k = raw.astype(np.float32) * 0.01                            # kelvin
        self.stamp = msg.header.stamp

    def on_rgb(self, msg):
        self.rgb = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')

    def on_depth(self, msg):
        self.depth_m = self.bridge.imgmsg_to_cv2(msg, desired_encoding='passthrough')   # float32 metres

    # ------------------------------------------------------------------ geometry helper
    def pixel_to_map(self, u, v, range_m, K, frame):
        """Map-frame (x, y, z) of the point seen at pixel (u, v) of a camera, `range_m` metres along
        the camera's viewing axis. `K` is that camera's intrinsics, `frame` its optical frame
        ('thermal_optical_frame' or 'camera_color_optical_frame'). None while TF is not ready.

        This uses the latest transform. While the rover turns, the pose at the image's own time
        stamp is more accurate: a pose that is 0.1 s old puts a person 10 m away about a metre to
        the side."""
        try:
            t = self.tf.lookup_transform('map', frame, rclpy.time.Time()).transform
        except Exception:
            return None
        # optical frame: z forward, x right, y down
        p = np.array([(u - K[0, 2]) / K[0, 0] * range_m, (v - K[1, 2]) / K[1, 1] * range_m, range_m])
        q = t.rotation
        x, y, z, w = q.x, q.y, q.z, q.w
        R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                      [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                      [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
        m = R @ p + np.array([t.translation.x, t.translation.y, t.translation.z])
        return float(m[0]), float(m[1]), float(m[2])

    # ------------------------------------------------------------------ detecting
    def detect(self):
        """YOUR PERCEPTION GOES HERE. Return a list of (class_id, (x, y, z) in the map frame, score).

        Example of ONE finished detection, to show the format:
            return [('survivor', (12.4, -3.1, 0.3), 0.9)]
        class_id: 'survivor', 'fire', 'marker:17', 'water_tank:red', 'sign:PHARMACY', ...

        Inputs: self.thermal_k, self.rgb, self.depth_m, self.K_thermal, self.K_rgb, self.model,
        and self.pixel_to_map() to place something you found in the image on the map."""
        return []

    def process(self):
        if self.thermal_k is None or self.rgb is None or self.depth_m is None:
            return
        out = Detection3DArray()
        out.header.frame_id = 'map'
        out.header.stamp = self.stamp
        for class_id, (x, y, z), score in self.detect():
            d = Detection3D()
            d.header = out.header
            h = ObjectHypothesisWithPose()
            h.hypothesis.class_id, h.hypothesis.score = class_id, float(score)
            h.pose.pose.position.x, h.pose.pose.position.y, h.pose.pose.position.z = float(x), float(y), float(z)
            d.results.append(h)
            d.bbox.center.position = h.pose.pose.position
            out.detections.append(d)
        self.pub.publish(out)                     # published even when empty, so memory.py sees we are alive
        # evidence picture for rescue reports: the current colour image as JPEG
        ok, jpg = cv2.imencode('.jpg', cv2.cvtColor(self.rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 70])
        if ok:
            snap = CompressedImage()
            snap.header = out.header
            snap.format, snap.data = 'jpeg', jpg.tobytes()
            self.pub_snap.publish(snap)


def main():
    rclpy.init()
    node = Perception()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
