#!/bin/bash
# PM Bridge (Linux) — останавливает веб-чат-мост (proxy 3006).
echo "Останавливаю хранитель и proxy..."
pkill -f "PMBRIDGE_PROXY_KEEPER"
pkill -f "mcp-superassistant-proxy"
echo "Остановлено."
