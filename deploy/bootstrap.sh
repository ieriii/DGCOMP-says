#!/usr/bin/env bash
# Bootstrap a fresh Ubuntu 24.04 VPS for DGCOMP-says.
#
# Tested on Hostinger KVM 2 (x86_64), but provider-agnostic — anything
# running Ubuntu 24.04 with root SSH access works.
#
# Run as root on the freshly-created VPS (`ssh root@<IP>`). It:
#   1. Installs base packages and uv.
#   2. Creates an unprivileged `dgcomp` user with the same authorized_keys as root.
#   3. Disables root SSH login.
#   4. Clones the repo, runs `uv sync`, drops in the systemd unit + timer.
#
# After this completes:
#   - `scp` your local data/vocab.sqlite into /home/dgcomp/DGCOMP-says/data/
#   - Drop a /home/dgcomp/DGCOMP-says/.env with the secrets
#   - `systemctl enable --now dgcomp.timer`
#
# Re-running is safe: every step is idempotent.

set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/ieriii/DGCOMP-says.git}"
TARGET_USER="dgcomp"
TARGET_HOME="/home/${TARGET_USER}"
TARGET_REPO="${TARGET_HOME}/DGCOMP-says"

if [[ "${EUID}" -ne 0 ]]; then
  echo "must be run as root" >&2
  exit 1
fi

echo ">>> apt update + base packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get -y upgrade
apt-get -y install \
  ca-certificates curl git build-essential pkg-config \
  python3.12 python3.12-venv python3-pip \
  unattended-upgrades sqlite3 jq

echo ">>> create ${TARGET_USER} user (idempotent)"
if ! id -u "${TARGET_USER}" >/dev/null 2>&1; then
  adduser --disabled-password --gecos "" "${TARGET_USER}"
fi
install -d -m 700 -o "${TARGET_USER}" -g "${TARGET_USER}" "${TARGET_HOME}/.ssh"
if [[ -f /root/.ssh/authorized_keys ]]; then
  install -m 600 -o "${TARGET_USER}" -g "${TARGET_USER}" \
    /root/.ssh/authorized_keys "${TARGET_HOME}/.ssh/authorized_keys"
fi

echo ">>> install uv for ${TARGET_USER}"
sudo -u "${TARGET_USER}" -- bash -lc '
  set -euo pipefail
  if ! command -v uv >/dev/null 2>&1 && [[ ! -x "$HOME/.local/bin/uv" ]]; then
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
'

echo ">>> clone or update repo"
if [[ ! -d "${TARGET_REPO}/.git" ]]; then
  sudo -u "${TARGET_USER}" -- git clone "${REPO_URL}" "${TARGET_REPO}"
else
  sudo -u "${TARGET_USER}" -- git -C "${TARGET_REPO}" pull --ff-only
fi

echo ">>> uv sync"
sudo -u "${TARGET_USER}" -- bash -lc "
  set -euo pipefail
  cd '${TARGET_REPO}'
  \$HOME/.local/bin/uv sync
"

echo ">>> install systemd unit + timer"
install -m 644 "${TARGET_REPO}/deploy/dgcomp.service" /etc/systemd/system/dgcomp.service
install -m 644 "${TARGET_REPO}/deploy/dgcomp.timer"   /etc/systemd/system/dgcomp.timer
systemctl daemon-reload

echo ">>> enable unattended-upgrades"
dpkg-reconfigure -f noninteractive unattended-upgrades

if [[ ! -f "${TARGET_REPO}/.env" ]]; then
  cat <<EOF

================================================================================
NEXT STEPS — bot is NOT running yet:

  1. Drop .env on the box (chmod 600). Required keys:

       ANTHROPIC_API_KEY=sk-ant-...
       BUTTONDOWN_API_KEY=...

  2. From your laptop, push the seeded SQLite (~340 MB):

       scp data/vocab.sqlite ${TARGET_USER}@<IP>:${TARGET_REPO}/data/

  3. Smoke-test once interactively:

       sudo -u ${TARGET_USER} -- bash -lc 'cd ${TARGET_REPO} && ~/.local/bin/uv run dgcomp run --skip-post --verbose'

  4. Enable the timer:

       systemctl enable --now dgcomp.timer
       systemctl list-timers dgcomp.timer
       journalctl -u dgcomp.service -e

  5. (Optional) Disable root SSH once you've confirmed dgcomp@ login works:

       sed -i 's/^#*PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
       systemctl restart ssh

================================================================================
EOF
else
  echo ">>> .env already present — leaving it alone"
fi

echo ">>> bootstrap complete"
