# AI handoff — PM File System MCP / Qwen extension

Дата: 2026-06-20
Пользователь: Pavel / Kouleti Holiday
Рабочая папка: `/Users/pavelmalyk/pm_developer/pm_filesystem_mcp`

## Главные правила пользователя

- Отвечать по-русски.
- Пользователь не программист: объяснять коротко и простыми словами.
- Не грузить полотнами текста.
- Работать итерациями: 1–2 шага → пользователь делает → сообщает результат → следующий шаг.
- Строго одно действие/одна карточка/один вызов инструмента за сообщение. Не параллелить.
- Не останавливаться без необходимости.
- Сначала запускать/проверять текущее, потом переделывать.
- DeepSeek и другие сайты не ломать.

## Текущий проект

Проект: `PM File System MCP`.
Задача: локальный форк Chrome-расширения MCP SuperAssistant для Qwen.
Папка форка:

```text
pm_filesystem_mcp/qwen-fork
```

Форк основан на `srbhptl39/MCP-SuperAssistant`, версия около `0.6.0`.

## Git / GitHub

Репозиторий проекта:

```text
https://github.com/detoximan/pm-filesystem-mcp.git
```

Состояние было синхронизировано:

```text
main -> origin/main
commit: 031a789 feat: add patched Qwen MCP SuperAssistant fork
```

Что уже сделано:

- `qwen-fork` добавлен внутрь `pm_filesystem_mcp` как обычная папка, не вложенный git-репозиторий.
- Внутренняя `.git` у `qwen-fork` была удалена.
- `superassistant-config.json` убран из git tracking и добавлен в `.gitignore`, чтобы не утекали токены.
- Добавлен `superassistant-config.example.json`.
- Старый GitHub token засветился ранее — его лучше отозвать и заменить новым.

## Патч #169 — уже сделан

Файл:

```text
pm_filesystem_mcp/qwen-fork/pages/content/src/plugins/adapters/qwenchat.adapter.ts
```

Суть патча:

- В методе вставки результата в textarea Qwen прямое `element.value = ...` заменено на native setter `HTMLTextAreaElement.prototype.value`.
- Это нужно, чтобы controlled input Qwen увидел изменение и отправил результат инструмента обратно в чат.
- DeepSeek-адаптер не трогался.

Диагноз #169:

- Qwen не видел программную вставку результата.
- Из-за этого ответ инструмента не отправлялся.
- Карточка инструмента могла крутиться бесконечно.

## #148 — ещё НЕ исправлен

Диагноз по #148:

- В Qwen карточка вызова инструмента может быть пустой из-за CodeMirror/виртуализированной разметки.
- Общий рендер/parser ищет function call в DOM/code/pre, но Qwen может держать полный текст в скрытых `cm-hidden-pre-*`/CodeMirror структурах.
- Файлы для дальнейшего анализа:

```text
pm_filesystem_mcp/qwen-fork/pages/content/src/render_prescript/src/core/config.ts
pm_filesystem_mcp/qwen-fork/pages/content/src/render_prescript/src/parser/jsonFunctionParser.ts
pm_filesystem_mcp/qwen-fork/pages/content/src/render_prescript/src/parser/functionParser.ts
pm_filesystem_mcp/qwen-fork/pages/content/src/render_prescript/src/observer/stalledStreamHandler.ts
pm_filesystem_mcp/qwen-fork/chrome-extension/public/codemirror-accessor.js
```

Важно: сначала надо добиться, чтобы расширение подключилось к MCP server/proxy, потом тестировать #169/#148.

## Сборка расширения

Пользователь уже выполнил:

```bash
cd ~/pm_developer/pm_filesystem_mcp/qwen-fork
corepack enable
corepack prepare pnpm@9.15.1 --activate
pnpm install --frozen-lockfile
pnpm build
```

Сборка прошла успешно:

```text
Tasks: 12 successful, 12 total
```

Папка для загрузки в Chrome:

```text
/Users/pavelmalyk/pm_developer/pm_filesystem_mcp/qwen-fork/dist
```

Расширение загрузилось в Chrome без ошибок.

## Проблема с иконкой

При первой загрузке Chrome ругался:

```text
Could not load icon 'icon-16.png' specified in 'icons'
```

Причина: в `chrome-extension/public` есть:

```text
icon-34.png
icon-128.png
```

но нет `icon-16.png`.

Что было сделано:

- В `chrome-extension/manifest.ts` 16-я иконка была временно перенаправлена на существующую `icon-34.png`:

```ts
icons: {
  128: 'icon-128.png',
  34: 'icon-34.png',
  16: 'icon-34.png',
}
```

- Также была убрана ссылка на `icon-16.png` из `web_accessible_resources`.

Пользователь справедливо заметил, что проще было скопировать/переименовать `icon-34.png` в `icon-16.png`. Но на момент handoff расширение уже загрузилось.

## Текущая проблема подключения MCP SuperAssistant

В UI расширения было:

- Connection Type: сначала `Server-Sent Events (SSE)`
- Server URI: `http://localhost:3006/sse`
- Ошибка: `SSE error: Non-200 status code (404)`

Потом пользователь переключил:

- Connection Type: `Streamable HTTP`
- Server URI: `http://localhost:3006/mcp`

Но UI всё ещё показывал disconnect/старую ошибку.

Проверка терминалом:

```bash
curl -i http://localhost:3006/mcp
```

Ответ:

```text
HTTP/1.1 405 Method Not Allowed
X-Powered-By: Express
Access-Control-Allow-Origin: *
Content-Type: application/json; charset=utf-8

{"jsonrpc":"2.0","error":{"code":-32000,"message":"Method not allowed in stateless mode"},"id":null}
```

Вывод: `localhost:3006/mcp` живой. 405 для обычного GET — нормально/ожидаемо, потому что Streamable HTTP MCP endpoint ждёт MCP POST/протокол, а не браузерный GET.

Следующий разумный шаг в новом чате:

1. Не менять код сразу.
2. Проверить, запущен ли именно proxy MCP SuperAssistant на `3006` с transport `streamableHttp`.
3. Проверить в UI расширения, сохранён ли transport `Streamable HTTP` и URI `/mcp`.
4. Нажать refresh/reconnect в расширении.
5. Если всё равно disconnect — смотреть console/errors расширения и/или network request к `/mcp`.

## Важное про SSE vs Streamable HTTP

Пользователь спрашивал, планировалось ли делать Qwen на SSE.

Уточнение:

- Qwen-патч #169 — это НЕ про SSE. Это про вставку результата инструмента обратно в textarea Qwen.
- SSE/Streamable HTTP — это транспорт между Chrome-расширением и локальным MCP SuperAssistant Proxy на `localhost:3006`.
- Рабочий endpoint проекта ранее считался:

```text
http://localhost:3006/mcp
```

- SSE endpoint `/sse` даёт 404, значит текущий proxy не обслуживает `/sse` или запущен не в SSE mode.

## Что НЕ делать сразу

- Не переписывать дефолты расширения до проверки текущего подключения.
- Не трогать DeepSeek без отдельного диагноза.
- Не делать большие пачки правок.
- Не отправлять несколько файлов/патчей в одном сообщении.

## Короткий план нового чата

1. Проверить состояние proxy на `localhost:3006`.
2. Проверить настройки расширения: `Streamable HTTP` + `http://localhost:3006/mcp`.
3. Если расширение не подключается — снять верхнюю строку ошибки из Chrome extension errors/console/network.
4. После подключения протестировать Qwen простым MCP-вызовом.
5. Если #169 работает — переходить к #148 (пустая карточка/CodeMirror).
6. После каждого изменения: build → reload unpacked extension → test.
7. После успешных правок: git status → commit → push.

## Пример теста Qwen

В Qwen написать:

```text
Через MCP прочитай список файлов в корне проекта.
```

Ожидание:

- карточка MCP не пустая;
- tool call виден;
- результат приходит;
- результат вставляется обратно в Qwen;
- Qwen продолжает ответ;
- спиннер не висит бесконечно.

## Пример теста DeepSeek

Открыть DeepSeek и сделать аналогичный MCP-вызов. DeepSeek должен работать в том же расширении, отдельный адаптер DeepSeek не трогался.

## Последний пользовательский результат

Пользователь прислал:

```bash
curl -i http://localhost:3006/mcp
```

Получил 405 Method Not Allowed с JSON-RPC ошибкой `Method not allowed in stateless mode`.

Это подтверждает, что сервер отвечает на `/mcp`, но GET не является правильным MCP-запросом.

## Стиль ответа в новом чате

Начать с короткого признания:

- Контекст подхвачен.
- 405 на `/mcp` — сервер живой, это не 404 и не connection refused.
- Дальше делаем один шаг: проверить/reconnect в расширении или посмотреть конкретный network/console error.

Давать пользователю максимум 1–2 действия за раз.
