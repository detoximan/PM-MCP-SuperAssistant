# PM File System MCP — установка на Linux

Инструкция по запуску сервера `PM File System MCP` на Linux (проверено на Ubuntu, GNOME/Wayland, ASUS ROG).

Ядро (`server.py`, `fsops.py` и др.) — кроссплатформенное. Всё, что специфично для Linux, лежит в этой папке `bridge_for_linux/`.

## Что это

Один общий сервер-движок, который даёт доступ к локальной папке (файлы, git, Notion, веб). Подключаются к нему двое:

- **Notion AI** — снаружи через Cloudflare-туннель по адресу `https://mcp-linux.kobuleti-holiday.com/mcp`.
- **MCP SuperAssistant** (расширение Chrome) — через локальный proxy (порт 3006), см. репозиторий `PM-MCP-SuperAssistant`.

## Требования

- `python3` (3.10+; проверялось на 3.14)
- `git`
- `cloudflared`

## 1. Установить cloudflared

```bash
wget -O /tmp/cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
sudo dpkg -i /tmp/cloudflared.deb
cloudflared --version
```

## 2. Туннель и поддомен

```bash
cloudflared tunnel login                 # выбрать домен kobuleti-holiday.com
cloudflared tunnel create pm-linux       # создаст туннель и ~/.cloudflared/<UUID>.json
cloudflared tunnel route dns pm-linux mcp-linux.kobuleti-holiday.com
```

Затем создать `~/.cloudflared/config.yml` по образцу `cloudflared-config.example.yml` (подставить свой UUID).

## 3. Настроить .env

Скопировать `bridge_for_linux/.env.example` в корень проекта как `.env` и заполнить. Токен:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

Ключ `FS_ROOT` — папка, к которой открывается доступ (здесь: `/home/paul/pm_developer`).

## 4. Первый запуск (проверка)

```bash
bash start.sh
```

`start.sh` сам создаст venv в `$FS_ROOT/.venv`, поставит зависимости и запустит сервер на `127.0.0.1:8766`.
Должна появиться строка «PM File System MCP — сервер запущен».

## 5. Фоновый запуск / остановка

```bash
bash bridge_for_linux/bridge-up.sh     # сервер + туннель в фон
bash bridge_for_linux/bridge-down.sh   # остановить оба
```

Логи: `~/.pm-bridge-logs/server.log` и `~/.pm-bridge-logs/cloudflared.log`.

## 6. Автозапуск при входе в систему

```bash
cp bridge_for_linux/pm-bridge.sh ~/.local/bin/pm-bridge.sh
cp bridge_for_linux/pm-bridge.desktop ~/.config/autostart/pm-bridge.desktop
chmod +x ~/.local/bin/pm-bridge.sh
```

Обёртка `pm-bridge.sh` ждёт, пока примонтируется диск DATA, и только потом запускает мост.

**Отключить автозапуск:** `rm ~/.config/autostart/pm-bridge.desktop`
**Включить обратно:** повторить `cp` выше.

## 7. Проверка снаружи

Открыть в браузере `https://mcp-linux.kobuleti-holiday.com/mcp` — должно вернуться:

```json
{"error":"unauthorized"}
```

Это успех: запрос дошёл до сервера, сработала защита по токену. Для реального подключения нужен заголовок `Authorization: Bearer <FS_AUTH_TOKEN>`.

## Адрес для подключения

- **URL:** `https://mcp-linux.kobuleti-holiday.com/mcp` (Streamable HTTP)
- **Авторизация:** `Authorization: Bearer <ваш FS_AUTH_TOKEN из .env>`

## Нагрузка

В простое сервер и туннель почти не потребляют ресурсов (десятки МБ памяти, ~0% CPU). Остановить в любой момент — `bridge-down.sh`.
