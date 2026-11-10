#!/bin/bash
# =====================================================================
#  PM Bridge — остановка всех сервисов.
#  Универсальная версия (Linux / macOS).
# =====================================================================
set -u

echo "======================================================"
echo "  PM Bridge — остановка"
echo "======================================================"

# 1) Хранитель веб-чат-моста
echo "[1/4] Останавливаю хранитель веб-чат-моста..."
pkill -f "PMBRIDGE_PROXY_KEEPER" 2>/dev/null && echo "      остановлен." || echo "      не был запущен."

# 2) Веб-чат-мост (proxy)
echo "[2/4] Останавливаю веб-чат-мост (proxy)..."
pkill -f "mcp-superassistant-proxy" 2>/dev/null && echo "      остановлен." || echo "      не был запущен."
pkill -f "stdio_server.py" 2>/dev/null

# 3) MCP-сервер
echo "[3/4] Останавливаю MCP-сервер..."
pkill -f "server.py" 2>/dev/null && echo "      остановлен." || echo "      не был запущен."

# 4) Cloudflare-туннель
echo "[4/4] Останавливаю Cloudflare-туннель..."
pkill -f "cloudflared tunnel run" 2>/dev/null && echo "      остановлен." || echo "      не был запущен."

# 5) Scheduler
pkill -f "scheduler.py" 2>/dev/null

sleep 1
echo ""
echo "Готово. Все сервисы остановлены."
echo ""
