#!/bin/bash
# =====================================================================
#  PM MCP Super Assistant (Linux) — останавливает сервер, туннель и веб-чат-мост.
# =====================================================================
echo "Останавливаю веб-чат-мост..."
pkill -9 -f "PMBRIDGE_PROXY_KEEPER" 2>/dev/null || true
pkill -9 -f "mcp-superassistant-proxy" 2>/dev/null || true
pkill -9 -f "stdio_server.py" 2>/dev/null || true
fuser -k 3006/tcp 2>/dev/null || true

echo "Останавливаю MCP-сервер..."
pkill -9 -f "server.py" 2>/dev/null || true
fuser -k 8766/tcp 2>/dev/null || true

echo "Останавливаю Cloudflare-туннель..."
pkill -9 -f "cloudflared" 2>/dev/null || true

echo "Остановлено."
