#!/bin/bash
# Обёртка для автозапуска при входе в систему.
# Кладётся в ~/.local/bin/pm-bridge.sh
# Ждёт, пока примонтируется диск DATA, затем запускает мост.
PROJ="/home/paul/pm_developer/pm-filesystem-mcp"
for i in $(seq 1 60); do [ -d "$PROJ/bridge_for_linux" ] && break; sleep 2; done
[ -d "$PROJ/bridge_for_linux" ] || exit 0
exec "$PROJ/bridge_for_linux/bridge-up.sh"
