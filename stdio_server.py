#!/usr/bin/env python3
"""
stdio_server.py — обёртка для MCP SuperAssistant proxy (веб-чаты, локально).

Зачем нужен отдельный файл:
- Основной server.py отдаёт доступ по HTTP (порт 8766) и требует Bearer-токен —
  это для Notion через Cloudflare.
- Посредник MCP SuperAssistant не умеет передавать заголовки/токен, зато умеет
  ЗАПУСКАТЬ MCP-сервер напрямую через stdio (локальный канал, токен не нужен).
- Поэтому здесь мы переиспользуем те же 10 инструментов из server.py,
  но запускаем их в режиме stdio. Никакого порта, никакого токена, максимально быстро.

Ничего настраивать не нужно — посредник сам запускает этот файл
(см. superassistant-config.json).
"""

from __future__ import annotations

import os
import sys

# Чтобы 'import server' работал независимо от того, из какой папки нас запустили.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Сначала грузим .env рядом с этим файлом — чтобы FS_ROOT был верным на любой машине.
try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"), override=True)
except Exception:
    pass
# Запасной корень, только если .env совсем не подхватился.
os.environ.setdefault("FS_ROOT", os.path.expanduser("~/pm_developer"))
# stdio — это локальный канал между посредником и сервером, токен не нужен.
os.environ["FS_AUTH_TOKEN"] = ""
# Режим чтения-записи (как и для Notion).
os.environ.setdefault("FS_READ_ONLY", "0")

# Переиспользуем уже настроенный MCP-сервер со всеми инструментами.
from server import mcp  # noqa: E402

if __name__ == "__main__":
    # transport="stdio" — общение через стандартный ввод/вывод, как ждёт посредник.
    mcp.run(transport="stdio")
