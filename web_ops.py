"""
web_ops.py — Модуль для веб-поиска и парсинга.

Предоставляет интеграцию с Tavily API для структурированного поиска
и Jina Reader для глубокого чтения веб-страниц с возвратом чистого Markdown.
"""

from __future__ import annotations

import json
import urllib.parse
import urllib.request
from urllib.error import HTTPError, URLError

from chunking import chunk_by_tokens, estimate_tokens


class WebOpsError(Exception):
    """Ошибка веб-операции."""


class WebOps:
    """Операции для веб-поиска и парсинга."""

    def __init__(self, tavily_api_key: str = ""):
        self.tavily_api_key = tavily_api_key

    def tavily_search(
        self,
        query: str,
        max_results: int = 5,
        search_depth: str = "basic",
        include_answer: bool = True,
    ) -> dict:
        """
        Поиск через Tavily API.
        
        Args:
            query: Поисковый запрос
            max_results: Максимальное количество результатов (до 20)
            search_depth: Глубина поиска ('basic' или 'advanced')
            include_answer: Включить ли AI-ответ в результаты
            
        Returns:
            Структурированный результат поиска
        """
        if not self.tavily_api_key:
            raise WebOpsError("TAVILY_API_KEY не установлен в .env")
        
        max_results = max(1, min(int(max_results), 20))
        
        payload = {
            "api_key": self.tavily_api_key,
            "query": query,
            "max_results": max_results,
            "search_depth": search_depth,
            "include_answer": include_answer,
        }
        
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            "https://api.tavily.com/search",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode("utf-8"))
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise WebOpsError(f"Tavily API error {e.code}: {error_body}")
        except URLError as e:
            raise WebOpsError(f"Ошибка сети при обращении к Tavily: {e}")
        except Exception as e:
            raise WebOpsError(f"Непредвиденная ошибка Tavily: {e}")
        
        # Форматируем ответ
        formatted = {
            "query": query,
            "answer": result.get("answer", ""),
            "results": [],
        }
        
        for item in result.get("results", []):
            formatted["results"].append({
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "content": item.get("content", ""),
                "score": item.get("score", 0),
            })
        
        return formatted

    def jina_fetch(self, url: str, max_tokens: int = 2000) -> dict:
        """
        Получить содержимое веб-страницы через Jina Reader API.
        
        Args:
            url: URL страницы
            max_tokens: Максимальное количество токенов в ответе (автоматическая разбивка)
            
        Returns:
            Словарь с контентом в формате Markdown
        """
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        
        jina_url = f"https://r.jina.ai/{url}"
        
        req = urllib.request.Request(
            jina_url,
            headers={
                "Accept": "text/plain",
                "User-Agent": "PM File System MCP (via SuperAssistant)",
            },
        )
        
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise WebOpsError(f"Jina Reader error {e.code}: {error_body}")
        except URLError as e:
            raise WebOpsError(f"Ошибка сети при обращении к Jina Reader: {e}")
        except Exception as e:
            raise WebOpsError(f"Непредвиденная ошибка Jina Reader: {e}")
        
        # Оцениваем количество токенов
        token_count = estimate_tokens(content)
        
        # Если текст слишком длинный, разбиваем на части
        if token_count > max_tokens:
            chunks = chunk_by_tokens(content, max_tokens=max_tokens, overlap_tokens=200)
            return {
                "url": url,
                "total_tokens": token_count,
                "chunks_count": len(chunks),
                "chunks": chunks,
                "is_chunked": True,
            }
        
        return {
            "url": url,
            "content": content,
            "tokens": token_count,
            "is_chunked": False,
        }
