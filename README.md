# PM MCP Super Assistant

Расширение для Google Chrome + локальный MCP-сервер, соединяющий веб-чаты (ChatGPT, Claude, Qwen, Perplexity, Gemini, DeepSeek и др.) и внешние сервисы с вашей локальной файловой системой на компьютере.

---

## Возможности

1. **Chrome Extension (PM MCP Super Assistant)**:
   - Автоматически находит вызовы инструментов в интерфейсе веб-чатов.
   - Выполняет MCP-инструменты локально через быстрый протокол **Streamable HTTP**.
   - Поддерживает увеличенный таймаут (до **10 минут** / 600 секунд) для долгих операций (деплой, сборка проектов, установка пакетов).

2. **Локальный MCP-сервер (`stdio_server.py` / `server.py`)**:
   - 41 встроенный инструмент:
     - Файловые операции (`read_file`, `write_file`, `edit_file`, `list_directory`, `search_files`...)
     - Git операции (`git_status`, `git_commit`, `git_push`, `git_pull`, `git_log`...)
     - Выполнение Python-кода (`run_python`, `ipython`, `pip_install`, `ensure_venv`) с настраиваемым таймаутом до 600 сек.
     - Web-инструменты и интеграция с Notion.

---

## Быстрый старт

### 1. Загрузка расширения в Chrome
1. Откройте `chrome://extensions/`.
2. Включите **«Режим разработчика»** (вверху справа).
3. Нажмите **«Загрузить распакованное расширение»** (Load unpacked).
4. Выберите папку:
   ```text
   /Users/pavelmalyk/pm_developer/PM_MCP_SuperAssistant/extension/dist
   ```

### 2. Запуск сервисов моста

#### На macOS:
- Двойной клик по [`pm_bridge/pm-bridge.command`](file:///Users/pavelmalyk/pm_developer/PM_MCP_SuperAssistant/pm_bridge/pm-bridge.command)
- Или в терминале:
  ```bash
  bash /Users/pavelmalyk/pm_developer/PM_MCP_SuperAssistant/bridge-up.sh
  ```
- Для остановки:
  ```bash
  bash /Users/pavelmalyk/pm_developer/PM_MCP_SuperAssistant/bridge-down.sh
  ```

#### На Linux:
- Запуск:
  ```bash
  bash /Users/pavelmalyk/pm_developer/PM_MCP_SuperAssistant/bridge_for_linux/bridge-up.sh
  ```
- Остановка:
  ```bash
  bash /Users/pavelmalyk/pm_developer/PM_MCP_SuperAssistant/bridge_for_linux/bridge-down.sh
  ```

---

## Настройка в расширении Chrome

- **Connection Type**: `Streamable HTTP`
- **Server URI**: `http://localhost:3006/mcp`
