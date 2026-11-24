"""Publish the SparkX UGV description (robot_state_publisher). Used by sparkx_sim and for RViz checks."""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import Command, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    xacro_file = PathJoinSubstitution([FindPackageShare('sparkx_description'), 'urdf', 'sparkx_ugv.urdf.xacro'])
    description = ParameterValue(
        Command(['xacro ', xacro_file,
                 ' gt_bbox_camera:=', LaunchConfiguration('gt_bbox_camera'),
                 ' headlights:=', LaunchConfiguration('headlights'),
                 ' lidar_h_samples:=', LaunchConfiguration('lidar_h_samples')]),
        value_type=str)
    return LaunchDescription([
        DeclareLaunchArgument('use_sim_time', default_value='true'),
        DeclareLaunchArgument('gt_bbox_camera', default_value='false',
                              description='Dataset mode only: add a ground-truth bounding-box camera'),
        DeclareLaunchArgument('headlights', default_value='true'),
        DeclareLaunchArgument('lidar_h_samples', default_value='1024'),
        Node(package='robot_state_publisher', executable='robot_state_publisher', name='robot_state_publisher',
             output='screen',
             parameters=[{'robot_description': description,
                          'use_sim_time': LaunchConfiguration('use_sim_time')}]),
    ])
