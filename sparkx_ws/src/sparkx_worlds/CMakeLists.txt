cmake_minimum_required(VERSION 3.8)
project(sparkx_worlds)

find_package(ament_cmake REQUIRED)
find_package(ament_cmake_python REQUIRED)

ament_python_install_package(${PROJECT_NAME})

install(PROGRAMS
  scripts/generate_world
  scripts/make_practice_worlds
  scripts/import_assets
  scripts/make_textures
  scripts/check_generator
  DESTINATION lib/${PROJECT_NAME})

install(DIRECTORY models config DESTINATION share/${PROJECT_NAME})
install(DIRECTORY worlds DESTINATION share/${PROJECT_NAME} OPTIONAL)

# Make model:// URIs (survivors, vehicles, textures) resolvable by Gazebo
ament_environment_hooks("${CMAKE_CURRENT_SOURCE_DIR}/env-hooks/${PROJECT_NAME}.dsv.in")

ament_package()
