#!/usr/bin/env bash
# Build and run ONE team's submission against the organiser's simulator + referee.
#
#   docker/run_team.sh <team>_submission.zip            isolated network (recommended)
#   docker/run_team.sh <team>_submission.zip --simple   host network (practice / lab use only)
#   options: --cpus N (8)  --memory SIZE (16g)  --gpus  --domain ID (0)  --base IMAGE (sparkx:latest)
#
# What this script guarantees: the container holds the pristine stack plus only the files of the
# submission (validated against TEAM_FILES.txt), runs as an unprivileged user with all capabilities
# dropped, and is limited in CPU, memory and process count.
#
# Isolated mode puts the container on its own Docker network (172.30.77.0/24). ROS discovery
# reaches it with default settings. Start the organiser stack with GZ_IP=127.0.0.1 (printed below):
# without it a container on a Docker network can read Gazebo topics, i.e. ground truth - measured,
# see docs/HOSTING.md "Network isolation". The firewall rules listed there need root and are not
# applied by this script.
set -euo pipefail
ZIP=${1:?usage: run_team.sh <submission.zip> [--simple] [--cpus N] [--memory SIZE] [--gpus] [--domain ID] [--base IMAGE]}
shift
MODE=isolated; CPUS=8; MEM=16g; GPUS=(); DOMAIN=0; BASE=sparkx:latest
while [ $# -gt 0 ]; do
  case "$1" in
    --simple) MODE=simple ;;
    --cpus) CPUS=$2; shift ;;
    --memory) MEM=$2; shift ;;
    --gpus) GPUS=(--gpus all) ;;
    --domain) DOMAIN=$2; shift ;;
    --base) BASE=$2; shift ;;
    *) echo "unknown option $1" >&2; exit 2 ;;
  esac
  shift
done
[ -f "$ZIP" ] || { echo "no such file: $ZIP" >&2; exit 2; }
HERE=$(cd "$(dirname "$0")" && pwd)
TEAM=$(basename "$ZIP" .zip); TEAM=${TEAM%_submission}
TEAM=$(printf '%s' "$TEAM" | tr -c 'A-Za-z0-9_-' '_' | tr 'A-Z' 'a-z')
IMAGE=sparkx_team_$TEAM
CTX=$(mktemp -d)
trap 'rm -rf "$CTX"' EXIT
cp "$ZIP" "$CTX/submission.zip"
docker build -t "$IMAGE" -f "$HERE/Dockerfile.team" --build-arg BASE="$BASE" --build-arg SUBMISSION=submission.zip "$CTX"

COMMON=(--rm --name "$IMAGE" --cpus="$CPUS" --memory="$MEM" --memory-swap="$MEM" --pids-limit=2048
        --cap-drop=ALL --security-opt no-new-privileges "${GPUS[@]}" -e ROS_DOMAIN_ID="$DOMAIN")
if [ "$MODE" = simple ]; then
  echo "[run_team] SIMPLE mode: host network. Gazebo transport is reachable from team code - practice only."
  exec docker run "${COMMON[@]}" --net=host "$IMAGE"
fi
NET=sparkx_team_net; SUBNET=172.30.77.0/24; GATEWAY=172.30.77.1; TEAM_IP=172.30.77.2
docker network inspect $NET >/dev/null 2>&1 || docker network create --subnet $SUBNET --gateway $GATEWAY $NET >/dev/null
cat <<MSG
[run_team] ISOLATED mode. Start the organiser stack (simulator + referee) in a shell that has:
    export ROS_DOMAIN_ID=$DOMAIN GZ_IP=127.0.0.1
[run_team] team container: $TEAM_IP on $NET, $CPUS CPUs, $MEM RAM
MSG
exec docker run "${COMMON[@]}" --network $NET --ip $TEAM_IP "$IMAGE"
