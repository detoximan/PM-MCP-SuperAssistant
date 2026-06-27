#!/bin/bash
# =====================================================================
#  PM Bridge — веб-чат-мост (MCP SuperAssistant Proxy, порт 3006).
#  Вынесен из pm-filesystem-mcp: живёт рядом с расширением.
#  Серверная часть (MCP-сервер 8766 + cloudflared) — в pm-filesystem-mcp
#  (bridge_for_mac/bridge-up.sh). Сначала запускай её, потом этот скрипт.
#  ВАЖНО: используем Streamable HTTP, а не SSE.
#  SSE у MCP SuperAssistant зависает/падает при переподключениях.
# =====================================================================
set -u

LOG_DIR="/Users/pavelmalyk/pm_developer/.bridge-logs"
CONFIG="/Users/pavelmalyk/pm_developer/pm_filesystem_mcp/superassistant-config.json"
PROXY_VERSION="0.1.8"   # зафиксировано (без @latest), чтобы не тянуть обновления
RESTART_DELAY=8         # пауза авто-перезапуска, сек (было 1 — грузило старый Mac)
mkdir -p "$LOG_DIR"

echo "======================================================"
echo "  PM Bridge — веб-чат-мост (proxy 3006)"
echo "======================================================"

if pgrep -f "PMBRIDGE_PROXY_KEEPER" >/dev/null 2>&1; then
  echo "Веб-чат-мост (хранитель) уже работает — пропускаю."
elif command -v npx >/dev/null 2>&1; then
  echo "Запускаю веб-чат-мост Streamable HTTP (с авто-перезапуском)..."
  nohup bash -c '
# PMBRIDGE_PROXY_KEEPER — метка для поиска/остановки цикла
CONFIG="'"$CONFIG"'"
PROXY_VERSION="'"$PROXY_VERSION"'"
RESTART_DELAY="'"$RESTART_DELAY"'"
while true; do
  npx -y "@srbhptl39/mcp-superassistant-proxy@${PROXY_VERSION}" \
    --config "$CONFIG" \
    --port 3006 \
    --outputTransport streamableHttp \
    --stateful
  echo "[keeper] посредник упал, перезапуск через ${RESTART_DELAY}с ($(date))"
  sleep "$RESTART_DELAY"
done
' > "$LOG_DIR/superassistant.log" 2>&1 &
else
  echo "npx/Node.js не найден — пропускаю (веб-чат-мост не поднимется)."
  echo "Установи Node.js: https://nodejs.org/en/download"
fi

sleep 6
echo ""
lsof -iTCP:3006 -sTCP:LISTEN >/dev/null 2>&1 \
  && echo "  [OK] Веб-чат-мост   : http://localhost:3006/mcp" \
  || echo "  [--] Веб-чат-мост   : ещё поднимается -> $LOG_DIR/superassistant.log"
echo ""
echo "Для MCP SuperAssistant используй:"
echo "  Connection Type: Streamable HTTP"
echo "  Server URI:      http://localhost:3006/mcp"
echo "Окно можно закрыть — мост работает в фоне."
echo ""
