"""
fsops.py — ядро файловых операций для PM File System MCP.

Этот модуль НЕ зависит от библиотеки mcp — только стандартная библиотека Python.
Благодаря этому всю логику (включая защиту от выхода за пределы корневой папки)
можно полностью протестировать без сети и без MCP.
"""

from __future__ import annotations

import base64
import json
import shutil
import time
from pathlib import Path


class FSError(Exception):
    """Ошибка файловой операции (показывается агенту как текст)."""


class FileSystemOps:
    """Все файловые операции, ограниченные одной корневой папкой."""

    def __init__(self, root: str, read_only: bool = False, max_read_bytes: int = 5_000_000, mounts: dict | None = None):
        self.root = Path(root).expanduser().resolve()
        self.read_only = read_only
        self.max_read_bytes = max_read_bytes
        self.root.mkdir(parents=True, exist_ok=True)
        # Доп. внешние папки вне корня: {имя: Path}. Обращение — по имени
        # как к папке верхнего уровня (напр. "_2026/файл.txt").
        self.mounts = {
            name: Path(p).expanduser().resolve()
            for name, p in (mounts or {}).items()
        }

    # --- Безопасность ---

    def _resolve(self, relative_path: str) -> Path:
        """Превращает относительный путь в абсолютный и гарантирует, что он внутри root.

        Защищает от path traversal (../../), абсолютных путей и символических ссылок.
        """
        relative_path = (relative_path or "").strip()
        # Нормализуем Windows-разделители в форвард-слэши, чтобы traversal ловился на любой ОС
        relative_path = relative_path.replace("\\", "/")
        # Все пути трактуются как относительные к root; ведущий / просто срезается
        clean = relative_path.lstrip("/")
        # Доп. примонтированные папки (mounts): если путь начинается с имени mount,
        # разрешаем его внутри соответствующей внешней папки.
        if clean:
            first = clean.split("/", 1)[0]
            if first in self.mounts:
                mount_root = self.mounts[first]
                rest = clean[len(first):].lstrip("/")
                m_candidate = (mount_root / rest) if rest else mount_root
                m_resolved = m_candidate.resolve()
                try:
                    m_resolved.relative_to(mount_root)
                except ValueError:
                    raise FSError(
                        f"Доступ запрещён: путь '{relative_path}' выходит за пределы примонтированной папки '{first}'."
                    )
                return m_resolved
        candidate = (self.root / clean)
        # resolve() разворачивает .. и симлинки; strict=False — файл может ещё не существовать
        resolved = candidate.resolve()
        # Проверяем вложенность надёжно через relative_to (не через startswith)
        try:
            resolved.relative_to(self.root)
        except ValueError:
            raise FSError(
                f"Доступ запрещён: путь '{relative_path}' выходит за пределы корневой папки."
            )
        return resolved

    def _rel(self, path: Path) -> str:
        resolved = path.resolve()
        for name, mount_root in self.mounts.items():
            try:
                sub = str(resolved.relative_to(mount_root))
                return name if sub == "." else f"{name}/{sub}"
            except ValueError:
                continue
        try:
            return str(resolved.relative_to(self.root)) or "."
        except ValueError:
            return str(resolved)

    def _ensure_writable(self) -> None:
        if self.read_only:
            raise FSError("Сервер запущен в режиме read-only. Запись запрещена.")

    @staticmethod
    def _human(n: float) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    # --- Операции ---

    def list_directory(self, path: str = "") -> str:
        target = self._resolve(path)
        if not target.exists():
            raise FSError(f"Папка не найдена: {path}")
        if not target.is_dir():
            raise FSError(f"Это не папка: {path}")
        items = []
        for entry in sorted(target.iterdir(), key=lambda e: (e.is_file(), e.name.lower())):
            is_dir = entry.is_dir()
            items.append({
                "name": entry.name,
                "type": "directory" if is_dir else "file",
                "size": (entry.stat().st_size if entry.is_file() else None),
                "path": self._rel(entry),
            })
        # На верхнем уровне корня показываем примонтированные внешние папки как виртуальные.
        if target.resolve() == self.root:
            existing = {i["name"] for i in items}
            for name in self.mounts:
                if name not in existing:
                    items.append({"name": name, "type": "directory", "size": None, "path": name})
        return json.dumps({"path": self._rel(target), "items": items}, ensure_ascii=False, indent=2)

    def read_file(self, path: str, encoding: str = "utf-8") -> str:
        target = self._resolve(path)
        if not target.exists():
            raise FSError(f"Файл не найден: {path}")
        if not target.is_file():
            raise FSError(f"Это не файл: {path}")
        size = target.stat().st_size
        if size > self.max_read_bytes:
            raise FSError(
                f"Файл слишком большой ({self._human(size)}). Лимит: {self._human(self.max_read_bytes)}."
            )
        try:
            return target.read_text(encoding=encoding)
        except UnicodeDecodeError:
            raise FSError(f"[Бинарный файл, {self._human(size)}. Чтение как текста невозможно.]")

    def read_multiple_files(self, paths: list[str]) -> str:
        results = {}
        for p in paths:
            try:
                results[p] = self.read_file(p)
            except FSError as e:
                results[p] = f"[ошибка: {e}]"
        return json.dumps(results, ensure_ascii=False, indent=2)

    def write_file(self, path: str, content: str = "", encoding: str = "utf-8", content_base64: str = "") -> str:
        self._ensure_writable()
        if content_base64:
            try:
                content = base64.b64decode(content_base64).decode(encoding)
            except Exception as e:
                raise FSError(f"Ошибка декодирования base64: {e}")
        target = self._resolve(path)
        existed = target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)
        verb = "Перезаписан" if existed else "Создан"
        return f"{verb} файл: {self._rel(target)} ({len(content)} символов)"

    def edit_file(self, path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        self._ensure_writable()
        target = self._resolve(path)
        if not target.exists() or not target.is_file():
            raise FSError(f"Файл не найден: {path}")
        content = target.read_text(encoding="utf-8")
        count = content.count(old_text)
        if count == 0:
            raise FSError(f"Фрагмент не найден в файле: {path}")
        if count > 1 and not replace_all:
            raise FSError(
                f"Фрагмент встречается {count} раз. Уточните контекст или включите replace_all=true."
            )
        new_content = content.replace(old_text, new_text) if replace_all else content.replace(old_text, new_text, 1)
        target.write_text(new_content, encoding="utf-8")
        n = count if replace_all else 1
        return f"Заменено вхождений: {n} в файле {self._rel(target)}"

    def create_directory(self, path: str) -> str:
        self._ensure_writable()
        target = self._resolve(path)
        target.mkdir(parents=True, exist_ok=True)
        return f"Папка готова: {self._rel(target)}"

    def move_file(self, src: str, dst: str) -> str:
        self._ensure_writable()
        src_path = self._resolve(src)
        dst_path = self._resolve(dst)
        if not src_path.exists():
            raise FSError(f"Не найдено: {src}")
        dst_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src_path), str(dst_path))
        return f"Перемещено: {self._rel(src_path)} -> {self._rel(dst_path)}"

    def delete_file(self, path: str) -> str:
        self._ensure_writable()
        target = self._resolve(path)
        if not target.exists():
            raise FSError(f"Не найдено: {path}")
        if target.resolve() == self.root:
            raise FSError("Нельзя удалить корневую папку.")
        if target.is_dir():
            shutil.rmtree(target)
            return f"Папка удалена: {self._rel(target)}"
        target.unlink()
        return f"Файл удалён: {self._rel(target)}"

    def search_files(self, pattern: str, path: str = "") -> str:
        search_root = self._resolve(path)
        if not search_root.exists():
            raise FSError(f"Папка не найдена: {path}")
        matches = []
        for p in sorted(search_root.glob(pattern)):
            matches.append({
                "path": self._rel(p),
                "type": "directory" if p.is_dir() else "file",
                "size": (p.stat().st_size if p.is_file() else None),
            })
        return json.dumps({"pattern": pattern, "count": len(matches), "results": matches}, ensure_ascii=False, indent=2)

    def get_file_info(self, path: str) -> str:
        target = self._resolve(path)
        if not target.exists():
            raise FSError(f"Не найдено: {path}")
        st = target.stat()
        return json.dumps({
            "path": self._rel(target),
            "type": "directory" if target.is_dir() else "file",
            "size": st.st_size,
            "size_human": self._human(st.st_size),
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "created": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_ctime)),
        }, ensure_ascii=False, indent=2)