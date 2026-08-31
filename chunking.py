"""
chunking.py — Утилиты для разбивки текста на части.

Используется при чтении длинных веб-страниц, чтобы не переполнять контекст модели.
"""

from __future__ import annotations


def chunk_text(text: str, max_chars: int = 10000, overlap: int = 500) -> list[str]:
    """
    Разбить текст на части с перекрытием.
    """
    if not text:
        return []
    
    if len(text) <= max_chars:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_chars
        
        if end < len(text):
            last_newline = text.rfind('\n', start, end)
            last_space = text.rfind(' ', start, end)
            
            break_point = max(last_newline, last_space)
            
            if break_point > start + max_chars // 2:
                end = break_point + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        start = end - overlap if end < len(text) else len(text)
    
    return chunks


def estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return len(text) // 3 + 1


def chunk_by_tokens(text: str, max_tokens: int = 2000, overlap_tokens: int = 200) -> list[str]:
    if not text:
        return []
    max_chars = max_tokens * 3
    overlap_chars = overlap_tokens * 3
    return chunk_text(text, max_chars=max_chars, overlap=overlap_chars)


def merge_chunks(chunks: list[str], separator: str = "\n\n---\n\n") -> str:
    if not chunks:
        return ""
    return separator.join(chunks)
