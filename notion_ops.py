"""
notion_ops.py — работа с Notion API для PM File System MCP.

Не зависит от библиотеки mcp — только стандартная библиотека Python (urllib).
Использует официальный Notion API (https://api.notion.com).

Доступ:
- Токен интеграции берётся из переменной окружения NOTION_TOKEN.
- Запись разрешена только при NOTION_WRITE_ENABLED=1.
- Интеграция видит только те страницы/базы, к которым ей дали доступ в Notion (Share → добавить integration).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"
HTTP_TIMEOUT = 30


class NotionError(Exception):
    """Ошибка работы с Notion (показывается агенту как текст)."""


class NotionOps:
    """Обёртка над Notion API с режимом read-only по умолчанию."""

    def __init__(self, token: str, write_enabled: bool = False):
        self.token = (token or "").strip()
        self.write_enabled = write_enabled

    # --- Низкоуровневый запрос ---

    def _require_token(self) -> None:
        if not self.token:
            raise NotionError(
                "NOTION_TOKEN не задан. Добавьте токен интеграции Notion в .env."
            )

    def _require_write(self) -> None:
        if not self.write_enabled:
            raise NotionError(
                "Запись в Notion выключена. Включите NOTION_WRITE_ENABLED=1 в .env."
            )

    def _request(self, method: str, path: str, payload: dict | None = None):
        self._require_token()
        url = f"{NOTION_API}{path}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Notion-Version", NOTION_VERSION)
        req.add_header("Content-Type", "application/json")
        try:
            with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT) as resp:  # noqa: S310 - personal local MCP tool
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")
            raise NotionError(f"Notion API ошибка {e.code}: {detail}")
        except urllib.error.URLError as e:
            raise NotionError(f"Не удалось соединиться с Notion: {e.reason}")
        return json.loads(body) if body else {}

    # --- Вспомогательные преобразования ---

    @staticmethod
    def _rich_text_to_plain(rich) -> str:
        if not rich:
            return ""
        return "".join(part.get("plain_text", "") for part in rich)

    @staticmethod
    def _title_of(obj) -> str:
        props = obj.get("properties", {})
        for prop in props.values():
            if prop.get("type") == "title":
                return NotionOps._rich_text_to_plain(prop.get("title", []))
        # базы данных хранят имя на верхнем уровне
        if obj.get("title"):
            return NotionOps._rich_text_to_plain(obj.get("title", []))
        return ""

    @staticmethod
    def _prop_to_value(prop) -> object:
        ptype = prop.get("type")
        value = prop.get(ptype)
        if ptype in ("title", "rich_text"):
            return NotionOps._rich_text_to_plain(value)
        if ptype == "select":
            return value.get("name") if value else None
        if ptype == "status":
            return value.get("name") if value else None
        if ptype == "multi_select":
            return [v.get("name") for v in (value or [])]
        if ptype == "checkbox":
            return bool(value)
        if ptype == "number":
            return value
        if ptype in ("url", "email", "phone_number"):
            return value
        if ptype == "date":
            if not value:
                return None
            return {"start": value.get("start"), "end": value.get("end")}
        if ptype == "people":
            return [v.get("name") or v.get("id") for v in (value or [])]
        if ptype == "relation":
            return [v.get("id") for v in (value or [])]
        if ptype in ("created_time", "last_edited_time"):
            return value
        if ptype == "formula":
            return value.get(value.get("type")) if value else None
        return NotionOps._rich_text_to_plain(value) if isinstance(value, list) else value

    @classmethod
    def _row_to_dict(cls, page) -> dict:
        result = {"id": page.get("id"), "url": page.get("url")}
        props = {}
        for name, prop in page.get("properties", {}).items():
            try:
                props[name] = cls._prop_to_value(prop)
            except Exception:  # noqa: BLE001
                props[name] = None
        result["properties"] = props
        return result

    @classmethod
    def _block_to_text(cls, block) -> str:
        btype = block.get("type", "")
        data = block.get(btype, {})
        text = cls._rich_text_to_plain(data.get("rich_text", [])) if isinstance(data, dict) else ""
        prefix_map = {
            "heading_1": "# ",
            "heading_2": "## ",
            "heading_3": "### ",
            "bulleted_list_item": "- ",
            "numbered_list_item": "1. ",
            "to_do": "[ ] ",
            "quote": "> ",
            "code": "",
        }
        if btype == "to_do" and isinstance(data, dict) and data.get("checked"):
            return f"[x] {text}"
        if btype == "code":
            return f"```\n{text}\n```"
        prefix = prefix_map.get(btype, "")
        if text:
            return f"{prefix}{text}"
        return f"[{btype}]"

    # --- Чтение ---

    def search(self, query: str = "", page_size: int = 10) -> str:
        page_size = max(1, min(int(page_size), 50))
        payload = {"query": query, "page_size": page_size}
        data = self._request("POST", "/search", payload)
        results = []
        for obj in data.get("results", []):
            results.append({
                "id": obj.get("id"),
                "object": obj.get("object"),
                "title": self._title_of(obj),
                "url": obj.get("url"),
                "last_edited_time": obj.get("last_edited_time"),
            })
        return json.dumps({"query": query, "results": results}, ensure_ascii=False, indent=2)

    def read_page(self, page_id: str, max_blocks: int = 100) -> str:
        page = self._request("GET", f"/pages/{page_id}")
        blocks_text = self._read_block_children_text(page_id, max_blocks)
        return json.dumps({
            "id": page.get("id"),
            "url": page.get("url"),
            "title": self._title_of(page),
            "properties": self._row_to_dict(page).get("properties", {}),
            "content": blocks_text,
        }, ensure_ascii=False, indent=2)

    def _read_block_children_text(self, block_id: str, max_blocks: int) -> str:
        max_blocks = max(1, min(int(max_blocks), 300))
        lines = []
        cursor = None
        fetched = 0
        while fetched < max_blocks:
            path = f"/blocks/{block_id}/children?page_size=100"
            if cursor:
                path += f"&start_cursor={cursor}"
            data = self._request("GET", path)
            for block in data.get("results", []):
                lines.append(self._block_to_text(block))
                fetched += 1
                if fetched >= max_blocks:
                    break
            if not data.get("has_more") or not data.get("next_cursor"):
                break
            cursor = data.get("next_cursor")
        return "\n".join(lines)

    def read_database(self, database_id: str) -> str:
        db = self._request("GET", f"/databases/{database_id}")
        schema = {}
        for name, prop in db.get("properties", {}).items():
            schema[name] = prop.get("type")
        return json.dumps({
            "id": db.get("id"),
            "url": db.get("url"),
            "title": self._rich_text_to_plain(db.get("title", [])),
            "schema": schema,
        }, ensure_ascii=False, indent=2)

    def query_database(self, database_id: str, page_size: int = 25, sort_by: str = "", direction: str = "descending") -> str:
        page_size = max(1, min(int(page_size), 100))
        payload = {"page_size": page_size}
        if sort_by:
            dir_norm = "ascending" if str(direction).lower().startswith("asc") else "descending"
            payload["sorts"] = [{"property": sort_by, "direction": dir_norm}]
        data = self._request("POST", f"/databases/{database_id}/query", payload)
        rows = [self._row_to_dict(p) for p in data.get("results", [])]
        return json.dumps({
            "database_id": database_id,
            "count": len(rows),
            "has_more": data.get("has_more", False),
            "rows": rows,
        }, ensure_ascii=False, indent=2)

    # --- Запись ---

    @staticmethod
    def _text_to_blocks(text: str) -> list:
        blocks = []
        for raw_line in (text or "").split("\n"):
            line = raw_line.rstrip()
            if not line:
                blocks.append({
                    "object": "block",
                    "type": "paragraph",
                    "paragraph": {"rich_text": []},
                })
                continue
            btype = "paragraph"
            content = line
            if line.startswith("### "):
                btype, content = "heading_3", line[4:]
            elif line.startswith("## "):
                btype, content = "heading_2", line[3:]
            elif line.startswith("# "):
                btype, content = "heading_1", line[2:]
            elif line.startswith("- "):
                btype, content = "bulleted_list_item", line[2:]
            blocks.append({
                "object": "block",
                "type": btype,
                btype: {"rich_text": [{"type": "text", "text": {"content": content}}]},
            })
        return blocks

    def create_page(self, parent_id: str, title: str, content: str = "", parent_type: str = "page") -> str:
        self._require_write()
        if parent_type == "database":
            parent = {"database_id": parent_id}
            properties = {"title": {"title": [{"type": "text", "text": {"content": title}}]}}
        else:
            parent = {"page_id": parent_id}
            properties = {"title": {"title": [{"type": "text", "text": {"content": title}}]}}
        payload = {"parent": parent, "properties": properties}
        if content:
            payload["children"] = self._text_to_blocks(content)
        page = self._request("POST", "/pages", payload)
        return json.dumps({
            "created": True,
            "id": page.get("id"),
            "url": page.get("url"),
            "title": title,
        }, ensure_ascii=False, indent=2)

    def append_to_page(self, page_id: str, text: str) -> str:
        self._require_write()
        if not text:
            raise NotionError("Нечего добавлять: пустой текст.")
        payload = {"children": self._text_to_blocks(text)}
        self._request("PATCH", f"/blocks/{page_id}/children", payload)
        return json.dumps({"appended": True, "page_id": page_id}, ensure_ascii=False, indent=2)

    # --- Колонки (свойства) ---

    def add_column(self, database_id: str, name: str, col_type: str = "text", options: str = "") -> str:
        """Добавить колонку в базу. col_type: text, number, checkbox, select."""
        self._require_write()
        if not name:
            raise NotionError("Не задано имя колонки.")
        t = (col_type or "text").strip().lower()
        if t in ("text", "rich_text", "текст", "строка"):
            spec = {"rich_text": {}}
            t = "text"
        elif t in ("number", "число", "num"):
            spec = {"number": {"format": "number"}}
            t = "number"
        elif t in ("checkbox", "галочка", "bool", "boolean"):
            spec = {"checkbox": {}}
            t = "checkbox"
        elif t in ("select", "выбор"):
            opts = [{"name": o.strip()} for o in (options or "").split(",") if o.strip()]
            spec = {"select": {"options": opts}}
            t = "select"
        else:
            raise NotionError(
                f"Неизвестный тип колонки: {col_type}. Используйте text, number, checkbox или select."
            )
        payload = {"properties": {name: spec}}
        self._request("PATCH", f"/databases/{database_id}", payload)
        return json.dumps({"added_column": name, "type": t}, ensure_ascii=False, indent=2)

    @staticmethod
    def _coerce_value(ptype: str, value):
        if ptype == "number":
            if value in (None, "", []):
                return {"number": None}
            return {"number": float(value)}
        if ptype == "checkbox":
            truthy = str(value).strip().lower() in ("true", "1", "yes", "да", "x", "on")
            return {"checkbox": truthy}
        if ptype == "select":
            if value in (None, ""):
                return {"select": None}
            return {"select": {"name": str(value)}}
        if ptype == "multi_select":
            items = [{"name": v.strip()} for v in str(value).split(",") if v.strip()]
            return {"multi_select": items}
        if ptype == "title":
            return {"title": [{"type": "text", "text": {"content": str(value)}}]}
        if ptype == "url":
            return {"url": str(value) or None}
        if ptype in ("email", "phone_number"):
            return {ptype: str(value) or None}
        if ptype == "date":
            return {"date": {"start": str(value)} if value else None}
        return {"rich_text": [{"type": "text", "text": {"content": str(value)}}]}

    def set_property(self, page_id: str, name: str, value: str = "") -> str:
        """Записать значение в колонку у строки. Тип колонки определяется автоматически."""
        self._require_write()
        if not name:
            raise NotionError("Не задано имя колонки.")
        page = self._request("GET", f"/pages/{page_id}")
        props = page.get("properties", {})
        if name not in props:
            available = ", ".join(props.keys())
            raise NotionError(f"Колонка '{name}' не найдена. Есть: {available}")
        ptype = props[name].get("type")
        payload = {"properties": {name: self._coerce_value(ptype, value)}}
        self._request("PATCH", f"/pages/{page_id}", payload)
        return json.dumps({
            "updated": True,
            "page_id": page_id,
            "column": name,
            "type": ptype,
            "value": value,
        }, ensure_ascii=False, indent=2)
