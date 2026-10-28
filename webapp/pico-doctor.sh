#!/bin/bash
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin:/sbin:/usr/sbin:$PATH"
unset http_proxy https_proxy HTTP_PROXY HTTPS_PROXY ALL_PROXY all_proxy
cd "$(dirname "${BASH_SOURCE[0]}")/.."
[ -f webapp/.doctor-requested ] || exit 0
{
  echo "### $(date '+%H:%M:%S')"
  ping -c 1 -W 500 192.168.10.22 >/dev/null 2>&1
  if arp -a 2>/dev/null | grep -qi 88:a2:9e:fb:18:6f; then
    echo "MAC:    on the LAN"
  else
    for i in $(seq 1 254); do ping -c 1 -W 100 -t 1 192.168.10.$i >/dev/null 2>&1 & done; wait; sleep 1
    arp -a 2>/dev/null | grep -i 88:a2:9e:fb:18:6f | sed 's/^/MAC:    /' || echo "MAC:    NOT on the LAN"
  fi
  curl -s -m 8 -o /tmp/ps.$$ -w "STATUS: http %{http_code}\n" http://192.168.10.22:5000/status 2>&1
  head -c 400 /tmp/ps.$$ 2>/dev/null | sed 's/^/BODY:   /'; echo; rm -f /tmp/ps.$$
  curl -s -m 20 http://localhost:8000/api/device/status 2>&1 | head -c 400 | sed 's/^/WEBAPP: /'; echo
} >> webapp/pico-status.log 2>&1
rm -f webapp/.doctor-requested
tail -n 60 webapp/pico-status.log > webapp/pico-status.log.tmp && mv webapp/pico-status.log.tmp webapp/pico-status.log
