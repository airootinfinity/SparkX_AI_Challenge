"""SparkX simulation: Gazebo world + UGV spawned at the scenario start pose + ROS bridges.

  ros2 launch sparkx_sim sim.launch.py world:=practice_small_day [gui:=true] [world_dir:=/abs/path]

`world` is looked up in sparkx_worlds/share/worlds unless `world_dir` (directory containing
world.sdf and private/scenario.yaml) is given — organizers keep secret worlds outside the workspace.
"""
import math
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, IncludeLaunchDescription, OpaqueFunction,
                            SetEnvironmentVariable, TimerAction)
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def resolve_world(context):
    wd = LaunchConfiguration('world_dir').perform(context)
    if not wd:
        wd = os.path.join(get_package_share_directory('sparkx_worlds'), 'worlds',
                          LaunchConfiguration('world').perform(context))
    return os.path.abspath(os.path.expanduser(wd))


def setup(context):
    wd = resolve_world(context)
    sdf = os.path.join(wd, 'world.sdf')
    if not os.path.exists(sdf):
        raise RuntimeError(f'SparkX world not found: {sdf}')
    scen = os.path.join(wd, 'private', 'scenario.yaml')
    start = yaml.safe_load(open(scen))['start'] if os.path.exists(scen) else dict(x=0, y=0, z=0.05, yaw=0)
    world_name = os.path.basename(wd.rstrip('/'))
    with open(sdf) as f:
        head = f.read(4096)
    if '<world name="' in head:
        world_name = head.split('<world name="', 1)[1].split('"', 1)[0]
    gui = LaunchConfiguration('gui').perform(context).lower() == 'true'
    models = os.path.join(get_package_share_directory('sparkx_worlds'), 'models')
    if LaunchConfiguration('textures').perform(context).lower() == 'lite':
        # half-resolution textures: about 0.7 GB less graphics memory (matters on integrated graphics)
        from sparkx_worlds import lite
        models = lite.ensure(models)
    res_path = os.pathsep.join([models, os.path.join(get_package_share_directory('sparkx_worlds'), 'worlds'),
                                os.environ.get('GZ_SIM_RESOURCE_PATH', '')])
    sim_share = get_package_share_directory('sparkx_sim')
    desc_share = get_package_share_directory('sparkx_description')

    gz_args = ['gz', 'sim', '-r', sdf] if gui else ['gz', 'sim', '-s', '-r', '--headless-rendering', sdf]
    actions = [
        ExecuteProcess(cmd=gz_args, cwd=wd, output='log', name='gazebo',
                       additional_env={'GZ_SIM_RESOURCE_PATH': res_path}),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(os.path.join(desc_share, 'launch', 'description.launch.py')),
            launch_arguments={'use_sim_time': 'true',
                              'headlights': LaunchConfiguration('headlights').perform(context),
                              'gt_bbox_camera': LaunchConfiguration('gt_bbox_camera').perform(context)}.items()),
        TimerAction(period=4.0, actions=[Node(
            package='ros_gz_sim', executable='create', output='screen', name='spawn_ugv',
            arguments=['-world', world_name, '-topic', 'robot_description', '-name', 'sparkx_ugv',
                       '-x', str(start['x']), '-y', str(start['y']), '-z', str(start.get('z', 0.05)),
                       '-Y', str(start['yaw'])])]),
        # bridges start once the Gazebo server is up: a bridge that subscribes before the server
        # exists can miss /clock, and without simulation time nothing downstream runs
        TimerAction(period=3.0, actions=[Node(package='ros_gz_bridge', executable='parameter_bridge', name='sparkx_team_bridge', output='log',
             parameters=[{'config_file': os.path.join(sim_share, 'config', 'bridge_team.yaml'),
                          'use_sim_time': True}])]),
    ]
    if gui:
        # open the 3D view on the rescue base instead of Gazebo's default origin view
        cx, cy, cz, pitch, yaw = start['x'] - 9.0, start['y'] - 9.0, 8.5, 0.5, math.pi / 4
        qy, qz, qw = math.sin(pitch / 2), math.sin(yaw / 2), math.cos(yaw / 2)
        cp = math.cos(pitch / 2)
        req = (f'pose: {{position: {{x: {cx}, y: {cy}, z: {cz}}}, orientation: {{x: {-qz * qy}, y: {qw * qy}, '
               f'z: {qz * cp}, w: {qw * cp}}}}}')
        actions.append(TimerAction(period=12.0, actions=[ExecuteProcess(
            cmd=['gz', 'service', '-s', '/gui/move_to/pose', '--reqtype', 'gz.msgs.GUICamera', '--reptype',
                 'gz.msgs.Boolean', '--timeout', '20000', '--req', req], output='log', name='gui_camera')]))
    if LaunchConfiguration('referee_bridge').perform(context).lower() == 'true':
        actions.append(TimerAction(period=3.0, actions=[Node(package='ros_gz_bridge', executable='parameter_bridge', name='sparkx_referee_bridge',
                            output='log', parameters=[{'config_file': os.path.join(sim_share, 'config',
                                                                                   'bridge_referee.yaml'),
                                                       'use_sim_time': True}])]))
    if LaunchConfiguration('rviz').perform(context).lower() == 'true':
        actions.append(Node(package='rviz2', executable='rviz2', output='log',
                            arguments=['-d', os.path.join(desc_share, 'rviz', 'sparkx.rviz')],
                            parameters=[{'use_sim_time': True}]))
    return actions


def generate_launch_description():
    worlds = os.path.join(get_package_share_directory('sparkx_worlds'), 'worlds')
    return LaunchDescription([
        DeclareLaunchArgument('world', default_value='practice_small_day'),
        DeclareLaunchArgument('world_dir', default_value=''),
        DeclareLaunchArgument('gui', default_value='false'),
        DeclareLaunchArgument('rviz', default_value='false'),
        DeclareLaunchArgument('headlights', default_value='true'),
        DeclareLaunchArgument('gt_bbox_camera', default_value='false'),
        DeclareLaunchArgument('referee_bridge', default_value='true'),
        DeclareLaunchArgument('textures', default_value='full'),       # 'lite' = half-resolution textures
        SetEnvironmentVariable('GZ_SIM_RESOURCE_PATH',
                               os.pathsep.join([os.path.join(get_package_share_directory('sparkx_worlds'), 'models'),
                                                worlds, os.environ.get('GZ_SIM_RESOURCE_PATH', '')])),
        OpaqueFunction(function=setup),
    ])
