#!/usr/bin/env python3
"""
server.py — PM File System MCP сервер.

Тонкая MCP-обёртка над fsops.FileSystemOps.
Даёт Notion AI доступ к одной локальной папке через Streamable HTTP.

Запуск:
    python server.py

Настройка — через переменные окружения (см. .env.example).
"""

from __future__ import annotations

import html
import json
import os
import re
import struct
import sys
import tempfile
import subprocess
import signal
import threading
import pathlib
import urllib.parse
import urllib.request
from html.parser import HTMLParser

import uvicorn
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from mcp.server.fastmcp import FastMCP

from fsops import FileSystemOps, FSError
from notion_ops import NotionOps, NotionError
from web_ops import WebOps, WebOpsError

try:
    from dotenv import load_dotenv
    dotenv_path = os.path.join(os.path.dirname(__file__), ".env")
    load_dotenv(dotenv_path)
except ImportError:
    pass  # python-dotenv необязателен

# --- Конфигурация ---
ROOT = os.environ.get("FS_ROOT", os.path.expanduser("~/pm_developer"))
AUTH_TOKEN = os.environ.get("FS_AUTH_TOKEN", "").strip()
PORT = int(os.environ.get("FS_PORT", "8765"))
HOST = os.environ.get("FS_HOST", "0.0.0.0")
READ_ONLY = os.environ.get("FS_READ_ONLY", "0") == "1"


def _parse_mounts(raw: str) -> dict:
    """FS_MOUNTS='имя=/абс/путь, имя2=/другой/путь' -> {'имя': '/абс/путь', ...}."""
    mounts = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, path = part.split("=", 1)
        name = name.strip().strip("/")
        path = os.path.expanduser(path.strip())
        if name and path:
            mounts[name] = path
    return mounts


MOUNTS = _parse_mounts(os.environ.get("FS_MOUNTS", ""))

fs = FileSystemOps(root=ROOT, read_only=READ_ONLY, mounts=MOUNTS)

# Notion: токен из NOTION_TOKEN, запись разрешена только при NOTION_WRITE_ENABLED=1
notion = NotionOps(
    token=os.environ.get("NOTION_TOKEN", "").strip(),
    write_enabled=os.environ.get("NOTION_WRITE_ENABLED", "0") == "1",
)

# WebOps: Tavily API для структурированного поиска
web = WebOps(
    tavily_api_key=os.environ.get("TAVILY_API_KEY", "").strip(),
)

# --- MCP-сервер ---
mcp = FastMCP(
    "PM File System MCP",
    host=HOST,
    port=PORT,
    stateless_http=True,
    json_response=True,
    instructions=(
        f"Доступ к локальной файловой системе. Корневая папка: {ROOT}. "
        f"Режим: {'read-only' if READ_ONLY else 'read-write'}. "
        "Все пути — относительно корневой папки. Выход за её пределы невозможен."
        + (
            " Дополнительно примонтированы внешние папки (обращайся по имени как к папке верхнего уровня): "
            + ", ".join(f"{n} -> {p}" for n, p in MOUNTS.items()) + "."
            if MOUNTS else ""
        )
    ),
)


def _wrap(fn, *args, **kwargs):
    """Единый обработчик ошибок: FSError -> понятный текст для агента."""
    try:
        return fn(*args, **kwargs)
    except (FSError, NotionError, WebOpsError) as e:
        return f"Ошибка: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Непредвиденная ошибка: {type(e).__name__}: {e}"


@mcp.tool()
def list_directory(path: str = ""):
    """Список файлов и папок. path — относительно корня (пусто = корень)."""
    return _wrap(fs.list_directory, path)


@mcp.tool()
def read_file(path: str, encoding: str = "utf-8"):
    """Прочитать содержимое текстового файла."""
    return _wrap(fs.read_file, path, encoding)


@mcp.tool()
def read_multiple_files(paths: list[str]):
    """Прочитать несколько файлов за один вызов."""
    return _wrap(fs.read_multiple_files, paths)


@mcp.tool()
def write_file(path: str, content: str = "", encoding: str = "utf-8", content_base64: str = ""):
    """Создать или перезаписать файл. Родительские папки создаются автоматически. content_base64 можно использовать вместо content для передачи кода с спецсимволами."""
    return _wrap(fs.write_file, path, content, encoding, content_base64)


@mcp.tool()
def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False):
    """Найти и заменить фрагмент в файле. Без replace_all фрагмент должен быть уникален."""
    return _wrap(fs.edit_file, path, old_text, new_text, replace_all)


@mcp.tool()
def create_directory(path: str):
    """Создать папку (включая родительские)."""
    return _wrap(fs.create_directory, path)


@mcp.tool()
def move_file(src: str, dst: str):
    """Переместить или переименовать файл/папку."""
    return _wrap(fs.move_file, src, dst)


@mcp.tool()
def delete_file(path: str):
    """Удалить файл или папку."""
    return _wrap(fs.delete_file, path)


@mcp.tool()
def search_files(pattern: str, path: str = ""):
    """Поиск файлов по glob-паттерну (например '*.py' или '**/*.md')."""
    return _wrap(fs.search_files, pattern, path)


@mcp.tool()
def get_file_info(path: str):
    """Метаданные файла/папки: размер, даты."""
    return _wrap(fs.get_file_info, path)


# --- Git-команды ---
# Работают только внутри корневой папки и только в папках, где есть .git.
# GIT_TERMINAL_PROMPT=0 не даёт git "зависнуть", если он вдруг запросит логин/пароль.
GIT_TIMEOUT = 600


def _resolve_repo(repo: str):
    """Вернуть абсолютный путь к git-репозиторию внутри корня или бросить FSError."""
    base = os.path.realpath(fs.root)
    target = os.path.realpath(os.path.join(base, repo)) if repo else base
    if target != base and not target.startswith(base + os.sep):
        raise FSError("Путь вне корневой папки запрещён.")
    if not os.path.isdir(target):
        raise FSError(f"Папка не найдена: {repo}")
    if not os.path.isdir(os.path.join(target, ".git")):
        raise FSError(f"В папке '{repo}' нет git-репозитория (.git не найден).")
    return target


def _git(repo: str, *args: str):
    """Запустить git с аргументами в папке repo и вернуть вывод."""
    cwd = _resolve_repo(repo)
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    try:
        proc = subprocess.run(
            ["git", *[str(a) for a in args]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT,
            env=env,
        )
    except FileNotFoundError:
        return "Ошибка: git не установлен на этом компьютере."
    except subprocess.TimeoutExpired:
        return "Ошибка: git-команда выполнялась слишком долго и была прервана."
    out = ((proc.stdout or "") + (proc.stderr or "")).strip() or "(git ничего не вывел)"
    status = "OK" if proc.returncode == 0 else f"код возврата {proc.returncode}"
    return f"[git {' '.join(str(a) for a in args)}] {status}\n{out}"


@mcp.tool()
def git_status(repo: str):
    """Показать статус репозитория: ветка и изменённые файлы. repo — папка проекта относительно корня, напр. 'detoximan'."""
    return _wrap(_git, repo, "status", "--short", "--branch")


@mcp.tool()
def git_pull(repo: str):
    """Подтянуть последние изменения с GitHub (git pull). repo — папка проекта относительно корня."""
    return _wrap(_git, repo, "pull")


@mcp.tool()
def git_commit(repo: str, message: str, add_all: bool = True):
    """Зафиксировать изменения (git commit). По умолчанию добавляет все изменённые файлы. repo — папка проекта, message — текст коммита."""
    if add_all:
        added = _wrap(_git, repo, "add", "-A")
        committed = _wrap(_git, repo, "commit", "-m", message)
        return f"{added}\n\n{committed}"
    return _wrap(_git, repo, "commit", "-m", message)


@mcp.tool()
def git_push(repo: str):
    """Отправить зафиксированные коммиты на GitHub (git push). repo — папка проекта относительно корня."""
    return _wrap(_git, repo, "push")


@mcp.tool()
def git_log(repo: str, count: int = 10):
    """Показать последние коммиты (git log). repo — папка проекта, count — сколько коммитов показать."""
    return _wrap(_git, repo, "log", "--max-count", str(count), "--oneline", "--decorate")


# --- Web / загрузки / Python ---
# Эти инструменты специально сделаны на стандартной библиотеке Python, без новых зависимостей.
FETCH_TIMEOUT = 120
MAX_FETCH_BYTES = 3_000_000
MAX_DOWNLOAD_BYTES = 25_000_000
MAX_PYTHON_OUTPUT = 100_000
PYTHON_TIMEOUT_MAX = 900


class _TextExtractor(HTMLParser):
    """Очень простой HTML -> текст без внешних зависимостей."""

    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style", "noscript", "svg"}:
            self.skip_depth += 1
        if tag in {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript", "svg"} and self.skip_depth:
            self.skip_depth -= 1
        if tag in {"p", "div", "li", "tr", "h1", "h2", "h3", "h4"}:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self.skip_depth:
            text = data.strip()
            if text:
                self.parts.append(text + " ")

    def text(self):
        raw = "".join(self.parts)
        lines = [" ".join(line.split()) for line in raw.splitlines()]
        return "\n".join(line for line in lines if line).strip()


class _DuckDuckGoParser(HTMLParser):
    """Парсер результатов DuckDuckGo HTML."""

    def __init__(self):
        super().__init__()
        self.results = []
        self._current_href = None
        self._current_text = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        class_name = attrs_dict.get("class", "")
        if tag == "a" and "result__a" in class_name:
            self._current_href = attrs_dict.get("href", "")
            self._current_text = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._current_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._current_href is not None:
            title = html.unescape(" ".join("".join(self._current_text).split()))
            url = _clean_duckduckgo_url(self._current_href)
            if title and url:
                self.results.append({"title": title, "url": url})
            self._current_href = None
            self._current_text = []


class _LinkMetadataParser(HTMLParser):
    """Вытащить ссылки, картинки и основные metadata из HTML."""

    def __init__(self, base_url: str):
        super().__init__()
        self.base_url = base_url
        self.links = []
        self.images = []
        self.metadata = {}
        self._in_title = False
        self._title_parts = []

    def handle_starttag(self, tag, attrs):
        attrs_dict = dict(attrs)
        if tag == "title":
            self._in_title = True
        elif tag == "a" and attrs_dict.get("href"):
            href = urllib.parse.urljoin(self.base_url, attrs_dict.get("href", ""))
            self.links.append({"url": href, "text": ""})
        elif tag == "img" and attrs_dict.get("src"):
            src = urllib.parse.urljoin(self.base_url, attrs_dict.get("src", ""))
            self.images.append({
                "image_url": src,
                "alt": attrs_dict.get("alt", ""),
                "width": attrs_dict.get("width", ""),
                "height": attrs_dict.get("height", ""),
            })
        elif tag == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name")
            value = attrs_dict.get("content")
            if key and value:
                self.metadata[key.lower()] = html.unescape(value.strip())

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self._title_parts.append(data)

    def title(self):
        title = " ".join("".join(self._title_parts).split())
        return html.unescape(title)


def _clean_duckduckgo_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.path.startswith("/l/"):
        qs = urllib.parse.parse_qs(parsed.query)
        if qs.get("uddg"):
            return qs["uddg"][0]
    return urllib.parse.urljoin("https://duckduckgo.com", url)


def _http_get_bytes(url: str, max_bytes: int):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise FSError("Разрешены только http/https URL.")
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (PM File System MCP; +https://kobuleti-holiday.com)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT) as response:  # noqa: S310 - personal local MCP tool
        content_type = response.headers.get("content-type", "")
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FSError(f"Ответ слишком большой. Лимит: {max_bytes} байт.")
    return data, content_type


def _decode_bytes(data: bytes, content_type: str) -> str:
    charset = "utf-8"
    if "charset=" in content_type:
        charset = content_type.split("charset=", 1)[1].split(";", 1)[0].strip()
    try:
        return data.decode(charset, errors="replace")
    except LookupError:
        return data.decode("utf-8", errors="replace")


@mcp.tool()
def tools_help():
    """Короткая справка по реальным инструментам этого MCP-сервера, чтобы модели не галлюцинировали названия."""
    return json.dumps({
        "files": ["list_directory", "read_file", "read_multiple_files", "write_file", "edit_file", "create_directory", "move_file", "delete_file", "search_files", "get_file_info"],
        "git": ["git_status", "git_pull", "git_commit", "git_push", "git_log"],
        "web": ["web_search", "web_search_tavily", "fetch_url", "fetch_url_jina", "extract_links", "read_url_metadata", "image_search", "download_file"],
        "python": ["run_python", "pip_install", "ensure_venv"],
        "images": ["image_info"],
        "notion": ["notion_search", "notion_read_page", "notion_read_database", "notion_query_database", "notion_create_page", "notion_append_to_page", "notion_add_column", "notion_set_property"],
        "rules": [
            "Use exact tool names only.",
            "Use fetch_url, not web_open_url.",
            "Use download_file, not download_url.",
            "Use run_python, not ipython.",
            "Use image_search, not search_image_by_text.",
        ],
    }, ensure_ascii=False, indent=2)


@mcp.tool()
def fetch_url(url: str, extract_text: bool = True, max_chars: int = 20000):
    """Открыть URL и вернуть текст страницы. extract_text=true чистит HTML до обычного текста."""
    def _run():
        data, content_type = _http_get_bytes(url, MAX_FETCH_BYTES)
        text = _decode_bytes(data, content_type)
        if extract_text and "html" in content_type.lower():
            parser = _TextExtractor()
            parser.feed(text)
            text = parser.text()
        max_chars_safe = max(1000, min(int(max_chars), 100000))
        if len(text) > max_chars_safe:
            text = text[:max_chars_safe] + "\n\n[обрезано по лимиту max_chars]"
        return json.dumps({"url": url, "content_type": content_type, "text": text}, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def web_search_tavily(query: str, max_results: int = 5, search_depth: str = "basic", include_answer: bool = True):
    """Структурированный поиск через Tavily API. Возвращает AI-ответ и список источников с очищенным контентом. search_depth: 'basic' или 'advanced'."""
    def _run():
        result = web.tavily_search(query, max_results, search_depth, include_answer)
        return json.dumps(result, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def fetch_url_jina(url: str, max_tokens: int = 2000):
    """Глубокое чтение веб-страницы через Jina Reader API. Возвращает чистый Markdown. Автоматически разбивает длинные тексты на части."""
    def _run():
        result = web.jina_fetch(url, max_tokens)
        return json.dumps(result, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def web_search(query: str, count: int = 5):
    """Поиск в интернете через DuckDuckGo HTML. Возвращает список найденных страниц."""
    def _run():
        n = max(1, min(int(count), 10))
        search_url = "https://html.duckduckgo.com/html/?" + urllib.parse.urlencode({"q": query})
        data, content_type = _http_get_bytes(search_url, MAX_FETCH_BYTES)
        page = _decode_bytes(data, content_type)
        parser = _DuckDuckGoParser()
        parser.feed(page)
        return json.dumps({"query": query, "results": parser.results[:n]}, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def extract_links(url: str, count: int = 100):
    """Открыть HTML-страницу и вернуть ссылки и картинки, найденные на ней."""
    def _run():
        n = max(1, min(int(count), 500))
        data, content_type = _http_get_bytes(url, MAX_FETCH_BYTES)
        text = _decode_bytes(data, content_type)
        parser = _LinkMetadataParser(url)
        parser.feed(text)
        return json.dumps({
            "url": url,
            "content_type": content_type,
            "links": parser.links[:n],
            "images": parser.images[:n],
        }, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def read_url_metadata(url: str):
    """Открыть HTML-страницу и вернуть title, description, og:image и другие metadata."""
    def _run():
        data, content_type = _http_get_bytes(url, MAX_FETCH_BYTES)
        text = _decode_bytes(data, content_type)
        parser = _LinkMetadataParser(url)
        parser.feed(text)
        meta = dict(parser.metadata)
        for key in ("og:image", "twitter:image"):
            if meta.get(key):
                meta[key] = urllib.parse.urljoin(url, meta[key])
        return json.dumps({
            "url": url,
            "content_type": content_type,
            "title": parser.title(),
            "description": meta.get("description") or meta.get("og:description") or meta.get("twitter:description"),
            "image": meta.get("og:image") or meta.get("twitter:image"),
            "metadata": meta,
        }, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def image_search(query: str, count: int = 10):
    """Поиск картинок по тексту через Bing Images. Возвращает ссылки на изображения и страницы-источники."""
    def _run():
        n = max(1, min(int(count), 20))
        search_url = "https://www.bing.com/images/search?" + urllib.parse.urlencode({"q": query, "form": "HDRSC2"})
        data, content_type = _http_get_bytes(search_url, MAX_FETCH_BYTES)
        page = _decode_bytes(data, content_type)
        results = []
        seen = set()
        for match in re.finditer(r'murl&quot;:&quot;(.*?)&quot;.*?purl&quot;:&quot;(.*?)&quot;', page):
            image_url = html.unescape(match.group(1)).replace("\\/", "/")
            page_url = html.unescape(match.group(2)).replace("\\/", "/")
            if image_url and image_url not in seen:
                seen.add(image_url)
                results.append({"image_url": image_url, "page_url": page_url})
            if len(results) >= n:
                break
        if not results:
            for match in re.finditer(r'"murl":"(.*?)".*?"purl":"(.*?)"', page):
                image_url = html.unescape(match.group(1)).replace("\\/", "/")
                page_url = html.unescape(match.group(2)).replace("\\/", "/")
                if image_url and image_url not in seen:
                    seen.add(image_url)
                    results.append({"image_url": image_url, "page_url": page_url})
                if len(results) >= n:
                    break
        return json.dumps({"query": query, "results": results}, ensure_ascii=False, indent=2)
    return _wrap(_run)


@mcp.tool()
def download_file(url: str, path: str = ""):
    """Скачать файл/картинку/PDF по URL в рабочую папку. path — путь сохранения относительно корня."""
    def _run():
        fs._ensure_writable()
        data, content_type = _http_get_bytes(url, MAX_DOWNLOAD_BYTES)
        save_path = path.strip()
        if not save_path:
            name = os.path.basename(urllib.parse.urlparse(url).path) or "download.bin"
            save_path = f"downloads/{name}"
        target = fs._resolve(save_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        return json.dumps({
            "saved_to": fs._rel(target),
            "bytes": len(data),
            "content_type": content_type,
            "source_url": url,
        }, ensure_ascii=False, indent=2)
    return _wrap(_run)


def _image_size(data: bytes):
    """Определить формат и размер PNG/JPEG/GIF/WebP по заголовку файла."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        width, height = struct.unpack(">II", data[16:24])
        return "png", width, height
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        if len(data) >= 10:
            width, height = struct.unpack("<HH", data[6:10])
            return "gif", width, height
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP" and len(data) >= 30:
        if data[12:16] == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return "webp", width, height
    if data.startswith(b"\xff\xd8"):
        i = 2
        while i + 9 < len(data):
            if data[i] != 0xFF:
                i += 1
                continue
            marker = data[i + 1]
            i += 2
            if marker in {0xD8, 0xD9}:
                continue
            if i + 2 > len(data):
                break
            length = int.from_bytes(data[i:i + 2], "big")
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if i + 7 <= len(data):
                    height = int.from_bytes(data[i + 3:i + 5], "big")
                    width = int.from_bytes(data[i + 5:i + 7], "big")
                    return "jpeg", width, height
            i += length
    return "unknown", None, None


@mcp.tool()
def image_info(path: str):
    """Прочитать локальную картинку и вернуть формат, размер, ширину и высоту."""
    def _run():
        target = fs._resolve(path)
        if not target.exists() or not target.is_file():
            raise FSError(f"Файл не найден: {path}")
        data = target.read_bytes()[:512_000]
        fmt, width, height = _image_size(data)
        st = target.stat()
        return json.dumps({
            "path": fs._rel(target),
            "format": fmt,
            "width": width,
            "height": height,
            "size": st.st_size,
            "size_human": fs._human(st.st_size),
        }, ensure_ascii=False, indent=2)
    return _wrap(_run)


# --- Управление процессами и очередью выполнения Python ---
_active_processes: set[subprocess.Popen] = set()
_process_lock = threading.Lock()


def _cleanup_stale_processes():
    """Удалить завершённые процессы из списка активных."""
    with _process_lock:
        stale = [p for p in _active_processes if p.poll() is not None]
        for p in stale:
            _active_processes.discard(p)


def _kill_all_active_processes() -> int:
    """Принудительно завершить все запущенные подпроцессы и их группы."""
    with _process_lock:
        killed = 0
        for proc in list(_active_processes):
            if proc.poll() is None:
                try:
                    if hasattr(os, "killpg") and hasattr(proc, "pid"):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                    killed += 1
                except Exception:
                    try:
                        proc.kill()
                        killed += 1
                    except Exception:
                        pass
            _active_processes.discard(proc)
        return killed


@mcp.tool()
def clear_process_queue():
    """Принудительно остановить все зависшие фоновые Python-скрипты и очистить временные файлы."""
    def _run():
        killed = _kill_all_active_processes()
        temp_dir = pathlib.Path(tempfile.gettempdir()) / "pm_mcp_runs"
        cleaned_files = 0
        if temp_dir.exists():
            for f in temp_dir.glob("*.py"):
                try:
                    f.unlink()
                    cleaned_files += 1
                except Exception:
                    pass
        return f"Очередь очищена: принудительно остановлено процессов: {killed}, удалено временных файлов: {cleaned_files}."
    return _wrap(_run)


@mcp.tool()
def run_python(code: str = "", working_dir: str = "", timeout: int = 600, code_base64: str = "", kill_previous: bool = False):
    """Запустить Python-код локально. working_dir — папка внутри корня. Код выполняется без shell, с timeout (по умолчанию 600 сек / 10 мин, максимум 900 сек / 15 мин)."""
    def _run():
        cwd = fs._resolve(working_dir)
        if not cwd.exists() or not cwd.is_dir():
            raise FSError(f"Рабочая папка не найдена: {working_dir}")
        timeout_safe = max(1, min(int(timeout), PYTHON_TIMEOUT_MAX))
        actual_code = code
        if code_base64:
            import base64
            try:
                actual_code = base64.b64decode(code_base64).decode("utf-8")
            except Exception as e:
                raise FSError(f"Base64 decode error: {e}")

        if kill_previous:
            _kill_all_active_processes()
        else:
            _cleanup_stale_processes()

        # Выделенная временная папка для скриптов, чтобы не засорять корень проекта
        temp_runs_dir = pathlib.Path(tempfile.gettempdir()) / "pm_mcp_runs"
        temp_runs_dir.mkdir(parents=True, exist_ok=True)
        try:
            temp_runs_dir.chmod(0o700)
        except Exception:
            pass

        with tempfile.NamedTemporaryFile("w", suffix=".py", encoding="utf-8", delete=False, dir=str(temp_runs_dir)) as tmp:
            tmp.write(actual_code)
            tmp_path = tmp.name

        child_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        existing_pythonpath = child_env.get("PYTHONPATH", "")
        child_env["PYTHONPATH"] = f"{cwd}:{existing_pythonpath}" if existing_pythonpath else str(cwd)

        # Автоматическая поддержка DaVinci Resolve на Linux
        if sys.platform.startswith("linux"):
            dvr_modules = "/opt/resolve/Developer/Scripting/Modules"
            if os.path.exists(dvr_modules) and dvr_modules not in child_env["PYTHONPATH"]:
                child_env["PYTHONPATH"] = f"{dvr_modules}:{child_env['PYTHONPATH']}"
            if os.path.exists("/opt/resolve/Developer/Scripting"):
                child_env.setdefault("RESOLVE_SCRIPT_API", "/opt/resolve/Developer/Scripting")
            if os.path.exists("/opt/resolve/libs/Fusion/fusionscript.so"):
                child_env.setdefault("RESOLVE_SCRIPT_LIB", "/opt/resolve/libs/Fusion/fusionscript.so")

        proc = None
        try:
            # start_new_session=True изолирует процесс в отдельную группу (setsid),
            # что гарантирует полное завершение всех дочерних процессов при таймауте через killpg.
            proc = subprocess.Popen(
                [sys.executable, tmp_path],
                cwd=str(cwd),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
                env=child_env,
            )
            with _process_lock:
                _active_processes.add(proc)

            out, err = proc.communicate(timeout=timeout_safe)
        except subprocess.TimeoutExpired:
            if proc:
                try:
                    if hasattr(os, "killpg"):
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    else:
                        proc.kill()
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass
                proc.wait()
            return f"Ошибка: Python-код выполнялся дольше {timeout_safe} сек. и был принудительно остановлен."
        finally:
            if proc:
                with _process_lock:
                    _active_processes.discard(proc)
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        out = (out or "")
        err = (err or "")
        combined = f"[exit_code={proc.returncode}]\nSTDOUT:\n{out}\nSTDERR:\n{err}".strip()
        if len(combined) > MAX_PYTHON_OUTPUT:
            combined = combined[:MAX_PYTHON_OUTPUT] + "\n\n[вывод обрезан по лимиту]"
        return combined
    return _wrap(_run)


@mcp.tool()
def pip_install(packages: str, upgrade: bool = False):
    """
    Установить Python-пакеты через pip. packages — строка со списком пакетов через пробел (например 'requests beautifulsoup4').
    Если в корне проекта есть .venv, использует его. Иначе — системный pip.
    """
    def _run():
        fs._ensure_writable()
        pkg_list = packages.strip().split()
        if not pkg_list:
            return "Ошибка: не указаны пакеты для установки."

        # Ищем .venv в корне
        venv_path = fs._resolve(".venv")
        if venv_path.exists() and venv_path.is_dir():
            if sys.platform == "win32":
                pip_exe = venv_path / "Scripts" / "pip.exe"
            else:
                pip_exe = venv_path / "bin" / "pip"
            if not pip_exe.exists():
                pip_exe = None
        else:
            pip_exe = None

        # Если venv pip не найден — используем системный
        if pip_exe and pip_exe.exists():
            cmd = [str(pip_exe), "install"]
            env_marker = f"[venv: {fs._rel(venv_path)}]"
        else:
            cmd = [sys.executable, "-m", "pip", "install"]
            env_marker = "[system pip]"

        if upgrade:
            cmd.append("--upgrade")
        cmd.extend(pkg_list)

        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600,
                env={**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1"},
            )
        except subprocess.TimeoutExpired:
            return "Ошибка: pip install выполнялся дольше 600 сек. и был остановлен."
        except FileNotFoundError as e:
            return f"Ошибка: pip не найден ({e})."

        out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        status = "OK" if proc.returncode == 0 else f"код возврата {proc.returncode}"
        result = f"{env_marker} [pip install {' '.join(pkg_list)}] {status}\n{out}".strip()
        if len(result) > MAX_PYTHON_OUTPUT:
            result = result[:MAX_PYTHON_OUTPUT] + "\n\n[вывод обрезан]"
        return result
    return _wrap(_run)


@mcp.tool()
def ensure_venv():
    """
    Создать виртуальное окружение .venv в корне проекта, если его ещё нет.
    Возвращает путь к созданному/существующему .venv.
    """
    def _run():
        fs._ensure_writable()
        venv_path = fs._resolve(".venv")
        if venv_path.exists() and venv_path.is_dir():
            return f".venv уже существует: {fs._rel(venv_path)}"

        try:
            proc = subprocess.run(
                [sys.executable, "-m", "venv", str(venv_path)],
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            return "Ошибка: создание .venv заняло больше 300 сек."
        except FileNotFoundError as e:
            return f"Ошибка: python не найден ({e})."

        if proc.returncode != 0:
            return f"Ошибка создания .venv (код {proc.returncode}):\n{proc.stderr}"

        return f".venv успешно создан: {fs._rel(venv_path)}"
    return _wrap(_run)


# --- Алиасы для моделей, которые галлюцинируют привычные имена инструментов ---
# Эти функции ничего нового не делают: они просто прокидывают вызов в реальные tools выше.

@mcp.tool()
def web_open_url(url: str, extract_text: bool = True, max_chars: int = 20000):
    """Алиас для fetch_url. Открыть URL и вернуть текст страницы."""
    return fetch_url(url=url, extract_text=extract_text, max_chars=max_chars)


@mcp.tool()
def fetch(url: str, extract_text: bool = True, max_chars: int = 20000):
    """Алиас для fetch_url. Открыть URL и вернуть текст страницы."""
    return fetch_url(url=url, extract_text=extract_text, max_chars=max_chars)


@mcp.tool()
def download_url(url: str, path: str = ""):
    """Алиас для download_file. Скачать файл/картинку/PDF по URL."""
    return download_file(url=url, path=path)


@mcp.tool()
def search_image_by_text(query: str, count: int = 10):
    """Алиас для image_search. Найти картинки по текстовому запросу."""
    return image_search(query=query, count=count)


@mcp.tool()
def ipython(code: str, working_dir: str = "", timeout: int = 600, kill_previous: bool = False):
    """Алиас для run_python. Выполнить Python-код локально (по умолчанию 600 сек / 10 мин)."""
    return run_python(code=code, working_dir=working_dir, timeout=timeout, kill_previous=kill_previous)


# --- Notion ---
# Чтение работает всегда (нужен NOTION_TOKEN). Запись — только при NOTION_WRITE_ENABLED=1.

@mcp.tool()
def notion_search(query: str, page_size: int = 10):
    """Найти страницы и базы данных в Notion по тексту. Возвращает названия и ID."""
    return _wrap(notion.search, query, page_size)


@mcp.tool()
def notion_read_page(page_id: str, max_blocks: int = 200):
    """Прочитать содержимое страницы Notion по её ID: заголовок и текст блоков."""
    return _wrap(notion.read_page, page_id, max_blocks)


@mcp.tool()
def notion_read_database(database_id: str):
    """Прочитать описание базы данных Notion: название и колонки (свойства)."""
    return _wrap(notion.read_database, database_id)


@mcp.tool()
def notion_query_database(database_id: str, page_size: int = 25, sort_by: str = "", direction: str = "descending"):
    """Получить строки (записи) из базы данных Notion. sort_by — точное имя колонки для сортировки (напр. 'Просмотры'), direction — 'ascending' или 'descending'."""
    return _wrap(notion.query_database, database_id, page_size, sort_by, direction)


@mcp.tool()
def notion_create_page(parent_id: str, title: str, content: str = "", parent_type: str = "page"):
    """Создать новую страницу Notion. parent_type='page' (внутри страницы) или 'database' (строка в базе). Требует NOTION_WRITE_ENABLED=1."""
    return _wrap(notion.create_page, parent_id, title, content, parent_type)


@mcp.tool()
def notion_append_to_page(page_id: str, text: str):
    """Дописать текст в конец существующей страницы Notion. Требует NOTION_WRITE_ENABLED=1."""
    return _wrap(notion.append_to_page, page_id, text)


@mcp.tool()
def notion_add_column(database_id: str, name: str, col_type: str = "text", options: str = ""):
    """Добавить колонку в базу Notion. col_type: text, number, checkbox или select. Для select в options передайте варианты через запятую. Требует NOTION_WRITE_ENABLED=1."""
    return _wrap(notion.add_column, database_id, name, col_type, options)


@mcp.tool()
def notion_set_property(page_id: str, name: str, value: str = ""):
    """Записать значение в колонку у строки (page_id — ID строки). Тип колонки определяется автоматически. Требует NOTION_WRITE_ENABLED=1."""
    return _wrap(notion.set_property, page_id, name, value)


# --- Bearer-авторизация ---
class BearerAuthMiddleware(BaseHTTPMiddleware):
    """Проверяет заголовок Authorization: Bearer <token> на каждом запросе."""

    def __init__(self, app, token: str):
        super().__init__(app)
        self.token = token

    async def dispatch(self, request, call_next):
        if self.token:
            header = request.headers.get("authorization", "")
            if header != f"Bearer {self.token}":
                return JSONResponse({"error": "unauthorized"}, status_code=401)
        return await call_next(request)


def main() -> None:
    if not AUTH_TOKEN:
        print("⚠️  ВНИМАНИЕ: FS_AUTH_TOKEN не задан — сервер без авторизации!", file=sys.stderr)
        print("   Не выставляйте такой сервер в интернет!", file=sys.stderr)

    print("-" * 52)
    print("  PM File System MCP — сервер запущен")
    print("-" * 52)
    print(f"  Корневая папка : {fs.root}")
    print(f"  Режим         : {'read-only' if READ_ONLY else 'read-write'}")
    print(f"  Доп. папки     : {', '.join(f'{n} -> {p}' for n, p in MOUNTS.items()) or '(нет)'}")
    print(f"  Адрес         : {{http://{HOST}}}:{PORT}/mcp")
    print(f"  Авторизация   : {'включена' if AUTH_TOKEN else 'ВЫКЛЮЧЕНА'}")
    print("-" * 52)

    # Строим Starlette-приложение из FastMCP и добавляем авторизацию
    app = mcp.streamable_http_app()
    app.add_middleware(BearerAuthMiddleware, token=AUTH_TOKEN)
    uvicorn.run(app, host=HOST, port=PORT)


if __name__ == "__main__":
    main()