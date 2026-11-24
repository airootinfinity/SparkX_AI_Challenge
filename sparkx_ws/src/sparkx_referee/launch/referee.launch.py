"""Launch the SparkX referee.

  practice     ros2 launch sparkx_referee referee.launch.py world:=<name> team_name:=<team>
  competition  ros2 launch sparkx_referee referee.launch.py world_dir:=/secure/worlds/final_A team_name:=<team> \
                   competition:=true dashboard_host:=0.0.0.0 log_dir:=/secure/logs

competition:=true = refuse to start on a modified / unverifiable stack (require_integrity), disqualify on
access to /sparkx/referee_private/* (violation_policy:=disqualify) and remove the unauthenticated ROS
admin services (control the run from the dashboard with its admin token).
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration as L
from launch_ros.actions import Node

ARGS = {'world': 'practice_small_day', 'world_dir': '', 'team_name': 'team', 'auto_start': 'true',
        'start_delay_s': '8.0', 'aftershocks': 'true', 'dashboard_port': '8080', 'dashboard_host': '127.0.0.1',
        'log_dir': '~/sparkx_logs', 'hide_survivor_total': 'false', 'time_limit_s': '0.0',
        # lock-down (docs/HOSTING.md)
        'competition': 'false', 'require_integrity': 'false', 'violation_policy': '', 'stack_root': '',
        'trusted_nodes': '', 'dashboard_token': ''}


def generate_launch_description():
    params = {k: L(k) for k in ARGS}
    params['use_sim_time'] = True
    return LaunchDescription([DeclareLaunchArgument(k, default_value=v) for k, v in ARGS.items()] + [
        Node(package='sparkx_referee', executable='referee', name='sparkx_referee', output='screen',
             parameters=[params])])
