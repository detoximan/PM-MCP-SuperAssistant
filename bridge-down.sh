#!/bin/bash
# =====================================================================
#  PM MCP Super Assistant — полная остановка всех сервисов и освобождение портов.
# =====================================================================
set -u

echo "======================================================"
echo "  PM MCP Super Assistant — остановка всех сервисов"
echo "======================================================"

# 1. Останавливаем хранитель и прокси SuperAssistant
echo "[1/3] Завершаю веб-чат-мост (порт 3006)..."
pkill -9 -f "PMBRIDGE_PROXY_KEEPER" 2>/dev/null || true
pkill -9 -f "mcp-superassistant-proxy" 2>/dev/null || true
pkill -9 -f "stdio_server.py" 2>/dev/null || true
lsof -ti :3006 | xargs kill -9 2>/dev/null || true

# 2. Останавливаем MCP-сервер (порт 8766)
echo "[2/3] Завершаю MCP-сервер (порт 8766)..."
lsof -ti :8766 | xargs kill -9 2>/dev/null || true
pkill -9 -f "server.py" 2>/dev/null || true

# 3. Останавливаем Cloudflare-туннель
echo "[3/3] Завершаю Cloudflare-туннель..."
pkill -9 -f "cloudflared.*run" 2>/dev/null || true

sleep 1
echo ""
echo "======================================================"
echo "  Итог проверки портов:"
lsof -iTCP:3006 -sTCP:LISTEN >/dev/null 2>&1 \
  && echo "  [!!] Порт 3006 всё ещё занят" \
  || echo "  [OK] Порт 3006 полностью свободен"

lsof -iTCP:8766 -sTCP:LISTEN >/dev/null 2>&1 \
  && echo "  [!!] Порт 8766 всё ещё занят" \
  || echo "  [OK] Порт 8766 полностью свободен"
echo "======================================================"
echo "Все сервисы остановлены."
echo ""
