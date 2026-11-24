cmake_minimum_required(VERSION 3.8)
project(sparkx_interfaces)

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(std_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(nav_msgs REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  # --- Published by the referee (organizer side) ---
  "msg/LandmarkRef.msg"
  "msg/Hint.msg"
  "msg/MissionStatus.msg"
  "msg/MissionEvent.msg"
  # --- Published by teams (required outputs, recorded for judging) ---
  "msg/SemanticObject.msg"
  "msg/SemanticMap.msg"
  "msg/ClueStatus.msg"
  "msg/ClueArray.msg"
  "msg/BehaviorState.msg"
  # --- Services offered by the referee ---
  "srv/GetMissionInfo.srv"
  "srv/GetHints.srv"
  "srv/ReportSurvivor.srv"
  "srv/SubmitMissionRecord.srv"
  "srv/EndMission.srv"
  DEPENDENCIES builtin_interfaces std_msgs geometry_msgs sensor_msgs nav_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
