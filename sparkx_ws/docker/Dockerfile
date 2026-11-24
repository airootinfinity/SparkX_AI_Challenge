# SparkX Disaster Response Challenge - ORGANISER image (simulator + referee + the locked stack).
#
#   cd sparkx_ws
#   python3 tools/sparkx_lock.py manifest            # once per release, on a clean checkout
#   docker build -t sparkx -f docker/Dockerfile .
#   docker build -t sparkx -f docker/Dockerfile --build-arg REQUIRE_PRISTINE=true .   # competition release
#
# The same image is the base of every team image (docker/Dockerfile.team), so a team's code always
# runs against exactly this stack, with the official ML kit (numpy 1.26.4, OpenCV 4.6, onnxruntime 1.32.0 CPU).
FROM osrf/ros:jazzy-desktop-full
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      ros-jazzy-ros-gz ros-jazzy-navigation2 ros-jazzy-nav2-bringup ros-jazzy-slam-toolbox \
      ros-jazzy-robot-localization ros-jazzy-pointcloud-to-laserscan ros-jazzy-vision-msgs \
      ros-jazzy-cv-bridge ros-jazzy-xacro python3-scipy python3-opencv python3-pil python3-yaml python3-pip \
    && rm -rf /var/lib/apt/lists/*

# The official ML kit (RULES.md section 6): apt's numpy and OpenCV (above) plus onnxruntime.
# Pinned and installed without dependencies, so apt's numpy 1.26 (which ROS needs) stays untouched.
RUN pip3 install --no-cache-dir --break-system-packages --no-deps onnxruntime==1.32.0 \
    && python3 -c "import numpy, cv2, onnxruntime; assert (numpy.__version__, cv2.__version__, onnxruntime.__version__) == ('1.26.4', '4.6.0', '1.32.0'), (numpy.__version__, cv2.__version__)"

WORKDIR /sparkx_ws
COPY TEAM_FILES.txt LOCKED_MANIFEST.sha256* ./
COPY tools ./tools
COPY docs ./docs
COPY docker ./docker
COPY src ./src

# Record (and for a competition release: require) that the image was built from an unmodified stack.
ARG REQUIRE_PRISTINE=false
RUN python3 tools/sparkx_lock.py verify | tee /sparkx_ws/BUILD_INTEGRITY.txt ; \
    if [ "$REQUIRE_PRISTINE" = "true" ] && ! grep -q "stack integrity: OK" /sparkx_ws/BUILD_INTEGRITY.txt ; then \
      echo "REQUIRE_PRISTINE=true but the stack does not verify" ; exit 1 ; fi

RUN . /opt/ros/jazzy/setup.sh && colcon build \
 && echo 'source /opt/ros/jazzy/setup.bash && source /sparkx_ws/install/setup.bash' >> /etc/bash.bashrc
ENV SPARKX_STACK_ROOT=/sparkx_ws
ENTRYPOINT ["/bin/bash", "-c", "source /opt/ros/jazzy/setup.bash && source /sparkx_ws/install/setup.bash && exec \"$@\"", "--"]
CMD ["ros2", "launch", "sparkx_bringup", "practice.launch.py"]
