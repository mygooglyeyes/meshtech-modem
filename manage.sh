#!/usr/bin/env bash
# =============================================================================
#  meshtech-modem - control panel (SSH / headless friendly)
#
#  One command for day-to-day modem management, run from the install:
#
#      sudo ./manage.sh          # interactive menu
#      sudo ./manage.sh restart  # restart the service
#
#  Same style as the bot's control panel: whiptail arrow-key dialogs
#  when available, plain prompts otherwise. Plain ASCII throughout.
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE="meshtech-modem"

log()  { printf '\033[1;32m[modem]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[modem]\033[0m WARNING: %s\n' "$*"; }

# --- whiptail detection (same rule as the bot's panel) ----------------
WT=""
if command -v whiptail >/dev/null 2>&1 && [[ -t 0 && -t 1 ]]; then
  WT=1
fi

confirm() {
  if [[ -n "$WT" ]]; then
    local args=(--yes-button Yes --no-button No)
    [[ "$2" == "n" ]] && args+=(--defaultno)
    whiptail --title " meshtech-modem " "${args[@]}" --yesno "$1" 0 0
  else
    read -r -p "  $1 [y/N]: " yn
    [[ "$yn" =~ ^[Yy] ]]
  fi
}

paused() { read -r -p "  Press Enter to return to the menu..." _; }

status_line() {
  if [[ -f /etc/systemd/system/$SERVICE.service ]]; then
    systemctl is-active --quiet "$SERVICE.service" && echo running || echo stopped
  else
    echo "(not installed)"
  fi
}

version_line() {
  # Topmost "## 0.0.NNN" in the changelog doubles as the version.
  grep -oE '^## 0\.0\.[0-9]+' "$DIR/CHANGELOG.md" 2>/dev/null \
    | head -1 | grep -oE '0\.0\.[0-9]+' || echo unknown
}

# --- 1) set / change the feed password --------------------------------
do_feed_token() {
  "$DIR/set-feed-token.sh"
}

# --- 2) update ---------------------------------------------------------
do_update() {
  log "Updating (git pull)..."
  git -C "$DIR" pull --ff-only || { warn "pull failed - fix git first"; return 1; }
  log "Restarting the service..."
  systemctl restart "$SERVICE.service"
  sleep 2
  systemctl --no-pager -n 3 status "$SERVICE.service" | sed -n '1,6p'
}

choose_option() {
  if [[ -n "$WT" ]]; then
    CHOICE="$(whiptail --title " meshtech-modem control panel " \
      --ok-button Select --cancel-button Quit \
      --menu "status: $(status_line)   v$(version_line)" 0 0 0 \
        "1" "Set / change the feed password (opens the feed port)" \
        "2" "Update the modem software (pull + restart)" \
        "3" "Restart the service" \
        "4" "View live logs (Ctrl-C stops watching)" \
        "q" "Quit" 3>&1 1>&2 2>&3)" || CHOICE="q"
  else
    clear 2>/dev/null || true
    echo "=============================================================================="
    echo "   meshtech-modem control panel       status: $(status_line)   v$(version_line)"
    echo "=============================================================================="
    echo "     1) Set / change the feed password"
    echo "     2) Update the modem software (git pull + restart)"
    echo "     3) Restart the service"
    echo "     4) View live logs (Ctrl-C to stop)"
    echo "     q) Quit"
    echo "------------------------------------------------------------------------------"
    read -r -p "  Choose an option: " CHOICE
  fi
}

# --- main loop ---------------------------------------------------------
if [[ "$(id -u)" -ne 0 ]]; then
  warn "Most options need root - run with:  sudo ./manage.sh"
fi

while true; do
  choose_option
  echo
  case "${CHOICE:-q}" in
    1) do_feed_token; paused ;;
    2) do_update;     paused ;;
    3) if systemctl restart "$SERVICE.service"; then
         log "Service restarted."
       else
         warn "restart failed - is the service installed?"
       fi
       paused ;;
    4) echo "  Live logs - press Ctrl-C to stop, then you return here."
       trap ':' INT
       journalctl -u "$SERVICE.service" -f --no-pager || true
       trap - INT
       paused ;;
    q|Q) echo "  73!"; exit 0 ;;
    *) echo "  Unknown option: $CHOICE"; sleep 1 ;;
  esac
done
