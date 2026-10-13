#!/bin/bash
# One-shot Pico diagnostic, run by the LaunchAgent natively on the Mac
# because the agent shells have no network interfaces at all.
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
TRIGGER="webapp/.doctor-requested"; LOG="webapp/pico-doctor.log"
[ -f "$TRIGGER" ] || exit 0
PICO_MAC="88:a2:9e:fb:18:6f"
{
  echo "=============================================="
  echo "=== pico-doctor v3 (wifi focus) $(date) ==="

  echo "--- is the Pico's MAC on the LAN at all? (quick recheck) ---"
  ping -c 1 -W 400 192.168.10.22 >/dev/null 2>&1
  arp -a 2>/dev/null | grep -i "$PICO_MAC" || echo "  not present"

  echo "--- what Wi-Fi is this Mac on, and on which band? ---"
  system_profiler SPAirPortDataType 2>/dev/null | awk '
    /Current Network Information/,/Other Local Wi-Fi Networks/' | head -30

  echo "--- is a 2.4 GHz network being broadcast? (Pico W is 2.4 GHz only) ---"
  system_profiler SPAirPortDataType 2>/dev/null \
    | grep -E '^ {12}[^ ].*:$|PHY Mode|Channel|Security' \
    | head -80

  echo "--- router model / identity ---"
  curl -s -m 4 -o /dev/null -w "router.asus.com http %{http_code}\n" http://router.asus.com/ 2>&1

  echo "--- how many devices are on the LAN right now ---"
  arp -a 2>/dev/null | grep -v incomplete | grep -vc 'ff:ff:ff' | sed 's/^/  /'

  echo "=== end pico-doctor v3 ==="
} >> "$LOG" 2>&1
rm -f "$TRIGGER"
tail -n 600 "$LOG" > "$LOG.tmp" 2>/dev/null && mv "$LOG.tmp" "$LOG"
