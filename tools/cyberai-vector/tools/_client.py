"""Тонкий HTTP-клиент к CyberAI Vector (Arkady_Cyber/src/cyberai_vector/api.py).

Вся тяжёлая логика (эмбеддинг BGE-M3, гибридный поиск в Qdrant, реранк,
генерация ответа) остаётся на стороне api.py — плагин только форматирует
результат для LLM-ноды/агента Arkady.
"""
from __future__ import annotations

import requests


class CyberAIError(Exception):
    pass


def _auth_headers(token: str | None) -> dict[str, str]:
    # api.py пропускает проверку токена целиком, когда CYBERAI_API_TOKEN на
    # его стороне пуст (офлайн-дев-режим) — заголовок в этом случае неважен,
    # но если токен настроен, без Authorization отдаст 403.
    return {"Authorization": f"Bearer {token}"} if token else {}


def search(base_url: str, path: str, query: str, top_k: int, token: str | None = None) -> list[dict]:
    """POST на /retrieval или /bestpractices/retrieval → сырые записи с metadata."""
    try:
        resp = requests.post(
            f"{base_url}{path}",
            json={
                "knowledge_id": "cyberai-vector",
                "query": query,
                "retrieval_setting": {"top_k": top_k, "score_threshold": 0.0},
            },
            headers=_auth_headers(token),
            # 30с не хватало на холодный старт cyberai-vector (первый запрос
            # после рестарта контейнера грузит BGE-M3 в память) — до 180с.
            timeout=180,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise CyberAIError(f"CyberAI Vector недоступен ({base_url}{path}): {e}") from e
    return resp.json().get("records", [])


def fetch_answer_prompt(
    base_url: str, query: str, top_k: int, token: str | None = None
) -> tuple[str | None, str | None]:
    """POST на /answer/prompt → (prompt, short_circuit_answer).

    api.py делает только retrieve (BGE-M3/reranker/Qdrant) и собирает текст
    промпта — LLM НЕ вызывает сам. Если найдена норма — вернёт prompt (его
    надо отдать в session.model.llm.invoke() уже подключённой в Arkady
    моделью). Если норма не найдена — вернёт готовый short_circuit_answer,
    LLM звать не нужно вовсе.
    """
    try:
        resp = requests.post(
            f"{base_url}/answer/prompt",
            json={"query": query, "top_k": top_k},
            headers=_auth_headers(token),
            # 30с не хватало на холодный старт cyberai-vector (первый запрос
            # после рестарта контейнера грузит BGE-M3 в память) — до 180с.
            timeout=180,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise CyberAIError(f"CyberAI Vector недоступен ({base_url}/answer/prompt): {e}") from e
    data = resp.json()
    return data.get("prompt"), data.get("answer")


def format_records(records: list[dict]) -> str:
    """Сырые записи → читаемый текст для LLM, с ПОЛНОЙ метадатой (не только content —
    в отличие от Dify Knowledge Retrieval, тул не режет metadata до .content)."""
    blocks = []
    for i, r in enumerate(records, 1):
        m = r.get("metadata", {})
        tags = []
        for key, label in (("status", "статус"), ("obligation", "обязательность"),
                           ("legal_rank", "ранг"), ("gis_class", "ГИС"),
                           ("kii_category", "КИИ"), ("pdn_level", "ПДн")):
            v = m.get(key)
            if v not in (None, "", []):
                tags.append(f"{label}: {v}")
        if m.get("domains"):
            tags.append(f"домены: {', '.join(m['domains'])}")
        meta_line = f"\n({'; '.join(tags)})" if tags else ""
        blocks.append(
            f"[{i}] {r.get('title', '')} (score={r.get('score', 0):.3f}){meta_line}\n"
            f"{r.get('content', '')}"
        )
    return "\n\n".join(blocks)
