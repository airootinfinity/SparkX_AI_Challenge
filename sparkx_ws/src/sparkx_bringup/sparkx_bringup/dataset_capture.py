"""Dataset capture for training detectors (practice worlds only).

Launch the sim with the ground-truth bounding-box camera, drive around (teleop or baseline), and run:
  ros2 launch sparkx_sim sim.launch.py world:=practice_small_day gt_bbox_camera:=true
  ros2 run sparkx_bringup dataset_capture --ros-args -p out_dir:=~/sparkx_dataset -p every_n:=5
Writes YOLO-format images/ + labels/ (class ids = sparkx_worlds.vocab.LABEL_IDS - 1) and classes.txt.
The GT box topic is bridged directly from Gazebo by this tool (never available in competition).
"""
import os
import subprocess

import cv2
import rclpy
from cv_bridge import CvBridge
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Image
from vision_msgs.msg import Detection2DArray

from sparkx_worlds.vocab import LABEL_NAMES


class Capture(Node):
    def __init__(self):
        super().__init__('sparkx_dataset_capture')
        self.out = os.path.expanduser(self.declare_parameter('out_dir', '~/sparkx_dataset').value)
        self.every = self.declare_parameter('every_n', 5).value
        for d in ('images', 'labels'):
            os.makedirs(os.path.join(self.out, d), exist_ok=True)
        with open(os.path.join(self.out, 'classes.txt'), 'w') as f:
            f.write('\n'.join(LABEL_NAMES[k] for k in sorted(LABEL_NAMES)) + '\n')
        self.bridge_proc = subprocess.Popen(['ros2', 'run', 'ros_gz_bridge', 'parameter_bridge',
                                             '/sparkx/dataset/boxes@vision_msgs/msg/Detection2DArray'
                                             '[gz.msgs.AnnotatedAxisAligned2DBox_V'])
        self.img, self.k, self.n = None, 0, 0
        self.cv = CvBridge()
        self.create_subscription(Image, '/camera/color/image_raw', lambda m: setattr(self, 'img', m),
                                 qos_profile_sensor_data)
        self.create_subscription(Detection2DArray, '/sparkx/dataset/boxes', self.on_boxes, 10)

    def on_boxes(self, msg):
        self.k += 1
        if self.img is None or self.k % self.every:
            return
        im = self.cv.imgmsg_to_cv2(self.img, 'bgr8')
        h, w = im.shape[:2]
        lines = []
        for d in msg.detections:
            cid = int(d.results[0].hypothesis.class_id) if d.results else 0
            if cid not in LABEL_NAMES:
                continue
            bw, bh = d.bbox.size_x, d.bbox.size_y
            if bw * bh < 64:
                continue
            lines.append(f'{cid - 1} {d.bbox.center.position.x / w:.5f} {d.bbox.center.position.y / h:.5f} '
                         f'{bw / w:.5f} {bh / h:.5f}')
        name = f'{self.get_clock().now().nanoseconds}'
        cv2.imwrite(os.path.join(self.out, 'images', name + '.jpg'), im)
        with open(os.path.join(self.out, 'labels', name + '.txt'), 'w') as f:
            f.write('\n'.join(lines))
        self.n += 1
        if self.n % 50 == 0:
            self.get_logger().info(f'{self.n} frames saved to {self.out}')

    def destroy_node(self):
        self.bridge_proc.terminate()
        super().destroy_node()


def main():
    rclpy.init()
    n = Capture()
    try:
        rclpy.spin(n)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        n.destroy_node()


if __name__ == '__main__':
    main()
