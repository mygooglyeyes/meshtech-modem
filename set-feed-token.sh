#!/usr/bin/env bash
# =============================================================================
#  meshtech-modem - feed password helper
#
#  One command to set (first run) or change the feed password:
#
#      sudo ./set-feed-token.sh
#
#  What it does:
#    1. asks you to type the password twice (so a typo can't lock you out)
#    2. writes it to .feed_token next to modem.conf  (mode 600)
#    3. restarts the modem service so the new password is active immediately
#
#  The bot pushes packets to the feed port by proving it knows this
#  password. The file is protected (mode 600) and the password never
#  sits in modem.conf or on a command line.
#
#  Run it again any time you want to change the password.
# =============================================================================
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TOKEN_FILE="${TOKEN_FILE:-$DIR/.feed_token}"

log()  { printf '\033[1;32m[feed-token]\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31m[feed-token]\033[0m ERROR: %s\n' "$*" >&2; exit 1; }

if [[ "$(id -u)" -ne 0 ]]; then
  die "Please run with sudo:  sudo ./set-feed-token.sh"
fi

echo "---------------------------------------------------------------------"
echo " meshtech-modem feed password"
echo " The modem reads the first line of .feed_token at startup."
echo " The bot must send this same password to push packets."
echo "---------------------------------------------------------------------"

read -r -s -p " New feed password: " password
echo
read -r -s -p " Type it again to confirm: " confirm
echo

if [[ -z "$password" ]]; then
  die "The password cannot be empty - run the script again."
fi
if [[ "$password" != "$confirm" ]]; then
  die "The two entries did not match - run the script again."
fi

# Write the file. The service account owns the install folder - take
# ownership from the folder itself so the right account can read it.
printf '%s\n' "$password" > "$TOKEN_FILE"
chown "$(stat -c %U:%G "$DIR")" "$TOKEN_FILE" 2>/dev/null || true
chmod 600 "$TOKEN_FILE"

log "Password saved to $TOKEN_FILE (mode 600)."

# Remove any old plaintext password line from modem.conf (superseded).
if [[ -f "$DIR/modem.conf" ]] && grep -q '^feed_token' "$DIR/modem.conf"; then
  sed -i '/^feed_token/d' "$DIR/modem.conf"
  log "Removed the old feed_token line from modem.conf (no longer used)."
fi

# Restart the service if it is running so the change applies right away.
if systemctl list-unit-files meshtech-modem.service &>/dev/null; then
  if systemctl is-active --quiet meshtech-modem.service; then
    log "Restarting meshtech-modem ..."
    systemctl restart meshtech-modem.service
    log "Done - the feed port is open with the new password."
    exit 0
  fi
fi

log "The modem service is not running - start it, then the feed port opens."
