#!/bin/bash
# deploy-orchid.sh - put the latest main on the hosted server, safely.
#
# Runs ONLY as the forced command of the GitHub Actions deploy key
# (.github/workflows/deploy.yml): that key can do nothing on the server except
# start this script. Installed at /root/deploy-orchid.sh. THIS COPY IS THE
# REFERENCE; a change here takes effect only once it is copied to the server.
#
#   1. Not between 06:00 and 09:00 farm time - the plants are watered then, and
#      a restart in the middle of a pour was a real risk. A deploy asked for in
#      that window is scheduled for 09:05 instead.
#   2. Fast-forward the checkout to origin/main. Never a merge, never a reset:
#      local changes on the server stop the deploy rather than vanish.
#   3. Reinstall the Python packages only if requirements.txt changed.
#   4. Restart the service and check it really started: active, "Application
#      startup complete" in its log, and the API answering.
#   5. If it did not: go back to the commit that was running, restart, and fail
#      loudly, so a bad merge costs a minute rather than the farm's whole API.
#
# Log: /var/log/deploy-orchid.log
set -uo pipefail
REPO=/root/R26-SE-018
LOG=/var/log/deploy-orchid.log
SERVICE=orchid
SELF=/root/deploy-orchid.sh

exec 9>/run/deploy-orchid.lock
flock -n 9 || { echo "Another deploy is already running."; exit 1; }
say() { echo "$(date '+%F %T') $*" | tee -a "$LOG"; }

# What the key asked for. `check` proves the key works without deploying; the
# workflow sends `deploy`; a run scheduled by this script itself sends nothing.
case "${SSH_ORIGINAL_COMMAND:-deploy}" in
  check)
    cd "$REPO" && git fetch -q origin main
    echo "Deploy key OK. Running $(git rev-parse --short HEAD); origin/main is $(git rev-parse --short origin/main)."
    exit 0 ;;
  deploy) ;;
  *) echo "Unknown request. Use: deploy or check."; exit 1 ;;
esac

hour=$((10#$(TZ=Asia/Colombo date +%H)))
if (( hour >= 6 && hour < 9 )) && [[ "${DEPLOY_NOW:-}" != "1" ]]; then
  wait=$(( $(TZ=Asia/Colombo date -d '09:05' +%s) - $(date +%s) ))
  systemd-run --quiet --unit="deploy-orchid-$(date +%s)" --on-active="${wait}s" \
              --setenv=DEPLOY_NOW=1 "$SELF"
  say "Watering window (06:00-09:00 farm time): deploy scheduled for 09:05, in ${wait}s."
  exit 0
fi

cd "$REPO" || { say "No checkout at $REPO"; exit 1; }
prev=$(git rev-parse HEAD)
if ! git fetch -q origin main; then say "git fetch failed. Nothing deployed."; exit 1; fi
if ! git merge -q --ff-only origin/main; then
  say "Cannot fast-forward ${prev:0:7} to origin/main (local changes on the server?). Nothing deployed."
  exit 1
fi
now=$(git rev-parse HEAD)
if [[ "$now" == "$prev" ]]; then say "Already at ${now:0:7}. Nothing to do."; exit 0; fi
say "Deploying ${prev:0:7} -> ${now:0:7}"

pip_if_changed() {
  if ! git diff --quiet "$1" "$2" -- backend/requirements.txt; then
    say "requirements.txt changed: installing"
    backend/.venv/bin/pip install -q -r backend/requirements.txt || return 1
  fi
}
started_ok() {
  sleep 25
  systemctl is-active --quiet "$SERVICE" || return 1
  # NOT `grep -q`: it stops reading at the first match, journalctl is killed by
  # SIGPIPE while writing the rest, and pipefail turns that 141 into a failure.
  # Once about 8 KB of log followed the match this failed every time: on
  # 19 Oct 2026 PR #77 was rolled back although it had started fine, and the
  # "rollback" was reported failed too. Replayed: 30/30 failures with -q, 0/30
  # without.
  journalctl -u "$SERVICE" --since "-45s" --no-pager -o cat | grep "Application startup complete" >/dev/null || return 1
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 http://127.0.0.1:8000/api/v2/care/overview)
  [[ "$code" == "401" || "$code" == "403" || "$code" == "200" ]]
}

if pip_if_changed "$prev" "$now" && systemctl restart "$SERVICE" && started_ok; then
  say "OK: $SERVICE is running ${now:0:7}"
  exit 0
fi
say "FAILED to start ${now:0:7}. Rolling back to ${prev:0:7}."
git reset -q --hard "$prev"
pip_if_changed "$now" "$prev"
systemctl restart "$SERVICE"
if started_ok; then
  say "Rolled back: $SERVICE is running ${prev:0:7} again."
else
  say "ROLLBACK ALSO FAILED. Check the server: journalctl -u $SERVICE"
fi
exit 1
