#!/bin/bash
exec >> "/home/paul/.pm-bridge-logs/restart-20260705-135409.log" 2>&1
echo "=== restart $(date) ==="
sleep 6
pkill -f "python server.py" 2>/dev/null; echo "kill http server rc=$?"
pkill -f "mcp-superassistant-proxy" 2>/dev/null; echo "kill proxy rc=$?"
sleep 2
cd /home/paul/pm_developer/pm-filesystem-mcp/bridge_for_linux || exit 1
bash bridge-up.sh
for i in $(seq 1 12); do
  if ss -ltn 2>/dev/null | grep -q "127.0.0.1:8766"; then echo "SERVER UP (try $i)"; break; fi
  echo "waiting server... $i"
  nohup bash /home/paul/pm_developer/pm-filesystem-mcp/start.sh >> "/home/paul/.pm-bridge-logs/server.log" 2>&1 &
  sleep 2
done
ss -ltn 2>/dev/null | grep -E "8766|3006" || echo "(порты не слушают?)"
pgrep -af "mcp-superassistant-proxy" || echo "proxy: нет"
echo "=== done $(date) ==="
