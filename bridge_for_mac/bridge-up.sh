#!/bin/bash
# =====================================================================
#  PM Bridge (macOS) — MCP-сервер + Cloudflare-туннель.
#  Веб-чат-мост (proxy 3006) теперь в репозитории PM-MCP-SuperAssistant:
#  запускай его скриптом proxy-up.sh оттуда.
#  Этот файл вызывается кнопкой pm-bridge.command с рабочего стола.
# =====================================================================
set -u

PROJ_DIR="$(cd "$(dirname "$0")/.." && pwd)"
LOG_DIR="$HOME/.pm-bridge-logs"
mkdir -p "$LOG_DIR"
cd "$PROJ_DIR" || exit 1

echo "======================================================"
echo "  PM Bridge (macOS) — запуск"
echo "======================================================"

# 1) MCP-сервер (проверка по ПОРТУ 8766, а не по имени процесса:
#    pgrep -f "server.py" ложно матчил stdio_server.py и ломал автозапуск).
if lsof -nP -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[1/2] MCP-сервер уже работает (порт 8766 занят)."
else
  echo "[1/2] Запускаю MCP-сервер..."
  nohup bash "$PROJ_DIR/start.sh" > "$LOG_DIR/server.log" 2>&1 &
fi

# 2) Cloudflare-туннель
if pgrep -f "cloudflared.*run" >/dev/null 2>&1; then
  echo "[2/2] Cloudflare-туннель уже работает."
elif command -v cloudflared >/dev/null 2>&1; then
  echo "[2/2] Запускаю Cloudflare-туннель..."
  nohup cloudflared tunnel --config "$PROJ_DIR/bridge_for_mac/cloudflared-config.yml" run > "$LOG_DIR/cloudflared.log" 2>&1 &
else
  echo "[2/2] cloudflared не найден — пропускаю."
fi

sleep 6
echo ""
echo "======================================================"
echo "  Итог:"
lsof -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1 \
  && echo "  [OK] Notion-сервер  : http://localhost:8766/mcp" \
  || echo "  [--] Notion-сервер  : не поднялся -> $LOG_DIR/mcp-server.log"
pgrep -f "cloudflared.*run" >/dev/null 2>&1 \
  && echo "  [OK] Cloudflare     : mcp.kobuleti-holiday.com" \
  || echo "  [!!] Cloudflare     : не поднялся -> $LOG_DIR/cloudflared.log"
echo "======================================================"
echo ""
echo "Серверная часть запущена."
echo "Веб-чат-мост (proxy 3006) теперь в репозитории PM-MCP-SuperAssistant."
echo "Окно можно закрыть — сервисы работают в фоне."
echo "Остановить всё: двойной клик по pm-bridge-stop.command"
echo ""
