#!/bin/bash
# =====================================================================
#  PM MCP Super Assistant — запуск всех сервисов моста.
# =====================================================================
set -u

PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="$HOME/.bridge-logs"
mkdir -p "$LOG_DIR"
cd "$PROJ_DIR" || exit 1

echo "======================================================"
echo "  PM MCP Super Assistant — очистка старых процессов и запуск"
echo "======================================================"

# Принудительно освобождаем порты и завершаем старые зависшие процессы
lsof -ti :3006 | xargs kill -9 2>/dev/null || true
lsof -ti :8766 | xargs kill -9 2>/dev/null || true
pkill -9 -f "mcp-superassistant-proxy" 2>/dev/null || true
pkill -9 -f "PMBRIDGE_PROXY_KEEPER" 2>/dev/null || true
pkill -9 -f "stdio_server.py" 2>/dev/null || true
pkill -9 -f "$PROJ_DIR/server.py" 2>/dev/null || true
sleep 1

# Автоматически обновляем конфиг с актуальным путем для текущей машины
cat <<EOF > "$PROJ_DIR/superassistant-config.json"
{
  "mcpServers": {
    "pm-filesystem": {
      "command": "python3",
      "args": [
        "$PROJ_DIR/stdio_server.py"
      ]
    },
    "github": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-github"
      ],
      "env": {
        "GITHUB_PERSONAL_ACCESS_TOKEN": ""
      }
    }
  }
}
EOF

# 1) MCP-сервер (порт 8766)
if lsof -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1; then
  echo "[1/3] MCP-сервер (8766) уже работает — пропускаю."
else
  echo "[1/3] Запускаю MCP-сервер (8766)..."
  nohup bash "$PROJ_DIR/start.sh" > "$LOG_DIR/mcp-server.log" 2>&1 &
fi

# 2) Cloudflare-туннель (если настроен)
if pgrep -f "cloudflared.*run" >/dev/null 2>&1; then
  echo "[2/3] Cloudflare-туннель уже работает — пропускаю."
elif command -v cloudflared >/dev/null 2>&1 && [ -f "$PROJ_DIR/cloudflared-config.yml" ]; then
  echo "[2/3] Запускаю Cloudflare-туннель..."
  nohup cloudflared tunnel --config "$PROJ_DIR/cloudflared-config.yml" run > "$LOG_DIR/cloudflared.log" 2>&1 &
else
  echo "[2/3] cloudflared не настроен — пропускаю (локальный мост будет работать)."
fi

# 3) Веб-чат-мост с АВТО-ПЕРЕЗАПУСКОМ (Streamable HTTP, порт 3006)
if pgrep -f "PMBRIDGE_PROXY_KEEPER" >/dev/null 2>&1; then
  echo "[3/3] Веб-чат-мост (хранитель) уже работает — пропускаю."
elif command -v npx >/dev/null 2>&1; then
  echo "[3/3] Запускаю веб-чат-мост Streamable HTTP (с авто-перезапуском)..."
  nohup bash -c "
# PMBRIDGE_PROXY_KEEPER — метка для поиска/остановки цикла
while true; do
  npx -y @srbhptl39/mcp-superassistant-proxy@0.1.8 \\
    --config \"$PROJ_DIR/superassistant-config.json\" \\
    --port 3006 \\
    --outputTransport streamableHttp \\
    --stateful
  echo \"[keeper] посредник упал, перезапуск через 8с (\$(date))\"
  sleep 8
done
" > "$LOG_DIR/superassistant.log" 2>&1 &
else
  echo "[3/3] npx/Node.js не найден — пропускаю (веб-чат-мост не поднимется)."
  echo "      Установи Node.js: https://nodejs.org/en/download"
fi

sleep 4
echo ""
echo "======================================================"
echo "  Итог проверки:"
lsof -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1 \
  && echo "  [OK] Локальный MCP-сервер : http://localhost:8766/mcp" \
  || echo "  [--] Локальный MCP-сервер : не поднят -> $LOG_DIR/mcp-server.log"
lsof -iTCP:3006 -sTCP:LISTEN >/dev/null 2>&1 \
  && echo "  [OK] Веб-чат-мост (Proxy) : http://localhost:3006/mcp" \
  || echo "  [--] Веб-чат-мост (Proxy) : ещё поднимается -> $LOG_DIR/superassistant.log"
echo "======================================================"
echo ""
echo "Готово. В настройках расширения Chrome выбери:"
echo "  Connection Type: Streamable HTTP"
echo "  Server URI:      http://localhost:3006/mcp"
echo "Окно можно закрыть — сервисы работают в фоне."
echo "Остановить всё: bash $PROJ_DIR/bridge-down.sh"
echo ""
