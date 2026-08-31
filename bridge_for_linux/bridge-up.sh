#!/bin/bash
# =====================================================================
#  PM MCP Super Assistant (Linux) — запуск сервисов.
# =====================================================================
set -u
PROJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$HOME/.bridge-logs"
mkdir -p "$LOG_DIR"
cd "$PROJ_DIR" || exit 1

echo "======================================================"
echo "  PM MCP Super Assistant (Linux) — запуск"
echo "======================================================"

# Принудительно освобождаем порты и завершаем старые зависшие процессы
fuser -k 3006/tcp 2>/dev/null || true
fuser -k 8766/tcp 2>/dev/null || true
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
if ss -ltn 2>/dev/null | grep -q '127.0.0.1:8766'; then
  echo "[1/3] MCP-сервер уже работает."
else
  echo "[1/3] Запускаю MCP-сервер..."
  nohup bash "$PROJ_DIR/start.sh" > "$LOG_DIR/mcp-server.log" 2>&1 &
fi

# 2) Cloudflare-туннель (если настроен)
if pgrep -f "cloudflared tunnel run" >/dev/null 2>&1; then
  echo "[2/3] Туннель уже работает."
elif command -v cloudflared >/dev/null 2>&1 && [ -f "$PROJ_DIR/cloudflared-config.yml" ]; then
  echo "[2/3] Запускаю Cloudflare-туннель..."
  nohup cloudflared tunnel --config "$PROJ_DIR/cloudflared-config.yml" run > "$LOG_DIR/cloudflared.log" 2>&1 &
else
  echo "[2/3] cloudflared не настроен — пропускаю."
fi

# 3) Web-чат-мост (Streamable HTTP, порт 3006)
if command -v npx >/dev/null 2>&1; then
  echo "[3/3] Запускаю веб-чат-мост (Streamable HTTP)..."
  nohup bash -c "
while true; do
  npx -y @srbhptl39/mcp-superassistant-proxy@0.1.8 \\
    --config \"$PROJ_DIR/superassistant-config.json\" \\
    --port 3006 \\
    --outputTransport streamableHttp \\
    --stateful
  echo \"[keeper] перезапуск через 8с (\$(date))\"
  sleep 8
done
" > "$LOG_DIR/superassistant.log" 2>&1 &
else
  echo "[3/3] npx не найден — установите Node.js для работы веб-чат-моста."
fi

sleep 4
echo ""
echo "======================================================"
echo "  Итог проверки (Linux):"
ss -ltn 2>/dev/null | grep -q '127.0.0.1:8766' \
  && echo "  [OK] Локальный MCP-сервер : http://localhost:8766/mcp" \
  || echo "  [--] Локальный MCP-сервер : не поднят -> $LOG_DIR/mcp-server.log"
ss -ltn 2>/dev/null | grep -q '127.0.0.1:3006' \
  && echo "  [OK] Веб-чат-мост (Proxy) : http://localhost:3006/mcp" \
  || echo "  [--] Веб-чат-мост (Proxy) : ещё поднимается -> $LOG_DIR/superassistant.log"
echo "======================================================"
echo ""
echo "Готово. Логи: $LOG_DIR"
echo "Остановить: bash $PROJ_DIR/bridge_for_linux/bridge-down.sh"
echo ""
