"""SparkX one-command bringup.

Practice (sim + referee + the autonomy stack running the team files in sparkx_team):
  ros2 launch sparkx_bringup practice.launch.py world:=practice_small_day
Sim + referee only (start the autonomy stack yourself, e.g. in a team container):
  ros2 launch sparkx_bringup practice.launch.py baseline:=false
Competition (organizer machine; team software is started separately on the team laptop/container):
  ros2 launch sparkx_bringup practice.launch.py world_dir:=/secure/worlds/final_A team_name:=RoboRescuers \
       baseline:=false gui:=true dashboard_host:=0.0.0.0
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration as L


def inc(pkg, f, args, cond=None, delay=0.0):
    a = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(os.path.join(get_package_share_directory(pkg), 'launch', f)),
        launch_arguments=args.items(), condition=cond)
    return TimerAction(period=delay, actions=[a]) if delay else a


def generate_launch_description():
    defaults = dict(world='practice_small_day', world_dir='', team_name='practice', gui='false',
                    rviz='false', textures='full', baseline='true', use_yolo='false', aftershocks='true', dashboard_port='8080',
                    dashboard_host='127.0.0.1', log_dir='~/sparkx_logs', start_delay_s='25.0', time_limit_s='0.0',
                    # referee lock-down options (see docs/HOSTING.md); defaults = practice mode
                    competition='false', require_integrity='false', violation_policy='', stack_root='',
                    trusted_nodes='', dashboard_token='', hide_survivor_total='false', auto_start='true',
                    team_config=os.path.join(get_package_share_directory('sparkx_team'), 'config', 'team.yaml'))
    return LaunchDescription([DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()] + [
        inc('sparkx_sim', 'sim.launch.py', dict(world=L('world'), world_dir=L('world_dir'), gui=L('gui'),
                                                rviz=L('rviz'), textures=L('textures'))),
        inc('sparkx_referee', 'referee.launch.py', dict(
            world=L('world'), world_dir=L('world_dir'), team_name=L('team_name'), aftershocks=L('aftershocks'),
            dashboard_port=L('dashboard_port'), dashboard_host=L('dashboard_host'), log_dir=L('log_dir'),
            start_delay_s=L('start_delay_s'), time_limit_s=L('time_limit_s'), competition=L('competition'), require_integrity=L('require_integrity'),
            violation_policy=L('violation_policy'), stack_root=L('stack_root'), trusted_nodes=L('trusted_nodes'),
            dashboard_token=L('dashboard_token'), hide_survivor_total=L('hide_survivor_total'),
            auto_start=L('auto_start'))),
        inc('sparkx_baseline', 'baseline.launch.py', dict(use_yolo=L('use_yolo'), team_config=L('team_config')),
            cond=IfCondition(L('baseline')), delay=10.0),
    ])
