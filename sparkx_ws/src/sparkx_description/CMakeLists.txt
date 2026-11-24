cmake_minimum_required(VERSION 3.8)
project(sparkx_description)

find_package(ament_cmake REQUIRED)

install(DIRECTORY urdf launch rviz meshes DESTINATION share/${PROJECT_NAME})

# Gazebo resolves package://sparkx_description/... through GZ_SIM_RESOURCE_PATH
ament_environment_hooks("${CMAKE_CURRENT_SOURCE_DIR}/env-hooks/${PROJECT_NAME}.dsv.in")

ament_package()
