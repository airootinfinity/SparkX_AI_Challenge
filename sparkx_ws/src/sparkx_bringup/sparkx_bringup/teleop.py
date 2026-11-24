"""Keyboard teleop for practice / manual-intervention drills. Publishes /cmd_vel (gated by the referee).
Keys: w/s forward/back, a/d turn, space stop, q quit. Using it during a scored run is an intervention."""
import select
import sys
import termios
import tty

import rclpy
from geometry_msgs.msg import Twist


def main():
    rclpy.init()
    n = rclpy.create_node('sparkx_teleop')
    pub = n.create_publisher(Twist, '/cmd_vel', 10)
    v = w = 0.0
    old = termios.tcgetattr(sys.stdin)
    print(__doc__)
    try:
        tty.setcbreak(sys.stdin.fileno())
        while rclpy.ok():
            if select.select([sys.stdin], [], [], 0.1)[0]:
                k = sys.stdin.read(1)
                if k == 'q':
                    break
                v = {'w': min(v + 0.1, 1.0), 's': max(v - 0.1, -0.5), ' ': 0.0}.get(k, v)
                w = {'a': min(w + 0.2, 1.5), 'd': max(w - 0.2, -1.5), ' ': 0.0}.get(k, w)
                print(f'\rv={v:+.1f} m/s  w={w:+.1f} rad/s   ', end='', flush=True)
            t = Twist()
            t.linear.x, t.angular.z = v, w
            pub.publish(t)
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, old)
        pub.publish(Twist())
        rclpy.shutdown()


if __name__ == '__main__':
    main()
