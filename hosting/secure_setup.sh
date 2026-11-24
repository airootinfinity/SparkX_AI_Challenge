#!/bin/bash
# SparkX evaluator: one-time hardening of this machine (run once, with sudo).
#
#   sudo bash hosting/secure_setup.sh            # set up (safe to run again)
#   sudo bash hosting/secure_setup.sh --remove   # undo everything
#
# Team software then runs as its own Unix user "sparkxteam" instead of as you. That user:
#   - cannot open your X display (screenshots, keystrokes): the display only admits your own user;
#   - has no TCP at all, no simulator discovery (UDP 10317/10318) and no traffic leaving this machine,
#     enforced by an nftables table "sparkx" that matches on that user only. ROS 2 (DDS, UDP on this
#     machine) keeps working;
#   - can read only the built stack and the run folders of this tool, not the rest of your files.
# Then set  "team_user": "sparkxteam"  in hosting/host_config.json.
set -euo pipefail
TEAM=sparkxteam
ORG=${SUDO_USER:?run this with sudo from your normal account}
HOSTING=$(cd "$(dirname "$0")" && pwd)
ROOT=$(dirname "$HOSTING")
SUDOERS=/etc/sudoers.d/sparkx-team
UNIT=/etc/systemd/system/sparkx-team-firewall.service
RULES=/etc/sparkx/team-firewall.nft

visible_paths() {   # folders from host_config.json the team may read, one per line (passed as argv, not pasted)
  python3 - "$HOSTING/host_config.json" "$ORG" <<'PY'
import json, os, sys
cfg, org = sys.argv[1], sys.argv[2]
c = json.load(open(cfg)) if os.path.isfile(cfg) else {}
home = os.path.expanduser('~' + org)
fix = lambda x: home + x[1:] if x.startswith('~') else x
out = [fix(x) for x in c.get('team_visible_paths', [])] + [os.path.dirname(fix(x)) for x in c.get('extra_setup', [])]
for p in out:
    rp = os.path.realpath(p)
    if rp in ('/', os.path.realpath(home)) or os.path.realpath(sys.argv[1]).startswith(rp + os.sep):
        sys.exit(f'refusing to share {p}: it contains your home or this tool; use a folder of its own')
    print(rp)
PY
}

if [ "${1:-}" = "--remove" ]; then
  systemctl disable --now sparkx-team-firewall.service 2>/dev/null || true
  nft delete table inet sparkx 2>/dev/null || true
  rm -f "$UNIT" "$RULES" "$SUDOERS" /etc/sparkx/team-firewall.ok
  setfacl -R -x "u:$TEAM" "$ROOT" 2>/dev/null || true
  d="$ROOT"; while [ "$d" != "/" ]; do setfacl -x "u:$TEAM" "$d" 2>/dev/null || true; d=$(dirname "$d"); done
  if visible_paths > /tmp/sparkx_visible.$$ 2>/dev/null; then
    while IFS= read -r p; do
      setfacl -R -x "u:$TEAM" "$p" 2>/dev/null || true
      q="$p"; while [ "$q" != "/" ]; do setfacl -x "u:$TEAM" "$q" 2>/dev/null || true; q=$(dirname "$q"); done
    done < /tmp/sparkx_visible.$$
  fi
  rm -f /tmp/sparkx_visible.$$
  userdel "$TEAM" 2>/dev/null || true
  echo "removed: user $TEAM, firewall table sparkx, sudo rule, folder permissions"
  exit 0
fi

command -v nft >/dev/null || apt-get install -y nftables
command -v setfacl >/dev/null || apt-get install -y acl
command -v bwrap >/dev/null || apt-get install -y bubblewrap

# 1. the team user: no login, no password, nothing of its own outside the run folders
id "$TEAM" >/dev/null 2>&1 || useradd --system --no-create-home --home-dir /nonexistent --shell /usr/sbin/nologin "$TEAM"
TUID=$(id -u "$TEAM")

# 2. firewall for that user only (IPv4 and IPv6)
mkdir -p /etc/sparkx
cat > "$RULES" <<EOF
table inet sparkx
delete table inet sparkx
table inet sparkx {
  chain out {
    type filter hook output priority 0; policy accept;
    meta skuid $TUID oifname != "lo" drop                      # nothing leaves this machine
    meta skuid $TUID meta l4proto tcp drop                     # no TCP: dashboard, panel, simulator transport
    meta skuid $TUID udp dport { 10317, 10318 } drop           # no simulator discovery
  }
}
EOF
nft -f "$RULES"
cat > "$UNIT" <<EOF
[Unit]
Description=SparkX: network limits for the sandboxed team software
After=network-pre.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/nft -f $RULES
ExecStop=/usr/sbin/nft delete table inet sparkx
[Install]
WantedBy=multi-user.target
EOF
systemctl daemon-reload
systemctl enable --now sparkx-team-firewall.service >/dev/null

# 3. you may start programs as that user (only that user, only env + bwrap), without a password
echo "$ORG ALL=($TEAM) NOPASSWD: /usr/bin/env" > "$SUDOERS"
chmod 440 "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

# 4. folder permissions: pass through the parents, read the built stack, read/write the run folders
d="$ROOT"
while [ "$d" != "/" ]; do setfacl -m "u:$TEAM:--x" "$d"; d=$(dirname "$d"); done
setfacl -R -m "u:$TEAM:rX" "$ROOT/sparkx_ws/install"
mkdir -p "$HOSTING/work"; chown "$ORG": "$HOSTING/work"
setfacl -m "u:$TEAM:--x" "$HOSTING"
setfacl -R -m "u:$TEAM:rwX,u:$ORG:rwX" -m "d:u:$TEAM:rwX,d:u:$ORG:rwX" "$HOSTING/work"
visible_paths > /tmp/sparkx_visible.$$ || { rm -f /tmp/sparkx_visible.$$; exit 1; }
while IFS= read -r p; do
  [ -e "$p" ] || continue
  setfacl -R -m "u:$TEAM:rX" "$p"
  q="$p"; while [ "$q" != "/" ]; do setfacl -m "u:$TEAM:--x" "$q"; q=$(dirname "$q"); done
done < /tmp/sparkx_visible.$$
rm -f /tmp/sparkx_visible.$$

# 5. verify: the team user must hold no group that gives root (docker, sudo, ...), and the firewall
#    (no internet, no TCP) must be loaded
for g in docker sudo admin wheel lxd libvirt incus-admin podman disk adm; do
  if id -nG "$TEAM" | tr ' ' '\n' | grep -qx "$g"; then gpasswd -d "$TEAM" "$g" >/dev/null; echo "removed $TEAM from group $g"; fi
done
nft list table inet sparkx >/dev/null || { echo "ERROR: the firewall table did not load"; exit 1; }
if [ -S /run/docker.sock ] && sudo -n -u "$TEAM" test -w /run/docker.sock; then
  echo "ERROR: $TEAM can still write to the Docker socket"; exit 1
fi

echo "$TUID" > /etc/sparkx/team-firewall.ok
echo "done: team software can run as '$TEAM' (uid $TUID)."
echo "now set  \"team_user\": \"$TEAM\"  in $HOSTING/host_config.json"
echo "(after you rebuild the stack with 'setup', run this script again to refresh the read permissions)"
