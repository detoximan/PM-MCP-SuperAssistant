# Карта мостов (BRIDGE.md)

Этот репозиторий = **расширение MCP SuperAssistant** (для веб-чатов: Qwen, ChatGPT и т.д.) + **мост для чатов** (локальный proxy на порту 3006).

## Архитектура

Расширение в браузере → proxy 3006 (этот репозиторий) → общий сервер `PM File System MCP` (репозиторий `pm-filesystem-mcp`).

Сервер-движок живёт в `pm-filesystem-mcp`, не здесь. Этот proxy к нему подключается.

## Где что лежит

| Папка | Что это |
|---|---|
| `chrome-extension/`, `packages/`, `pages/` | Код самого расширения для Chrome (имена папок менять нельзя — завязана сборка) |
| `bridge_for_mac/` | Мост для **Mac**: proxy 3006 + пример config |
| `bridge_for_linux/` | Мост для **Linux**: proxy 3006 + пример config |

## Как запустить мост для чатов

Сначала должен работать сервер (из `pm-filesystem-mcp`), затем:

- **Linux:** `bash bridge_for_linux/proxy-up.sh` (остановить: `proxy-down.sh`)
- **Mac:** `bash bridge_for_mac/proxy-up.sh` (остановить: `proxy-down.sh`)

Перед первым запуском скопируй `superassistant-config.example.json` в `superassistant-config.json` рядом с сервером и проверь пути.

В расширении укажи: Connection Type = Streamable HTTP, Server URI = `http://localhost:3006/mcp`.
