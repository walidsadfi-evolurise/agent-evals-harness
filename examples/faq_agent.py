"""A tiny agent to demo the harness: answers from a FAQ, calls a 'tool', refuses off-topic.

Replace with your own: anything that takes a dict and returns a dict works.
"""

from __future__ import annotations

from typing import Any

FAQ = {
    "horaires": "Nous sommes ouverts du lundi au vendredi, de 9h à 18h.",
    "livraison": "La livraison prend 2 à 4 jours ouvrés en France métropolitaine.",
    "retour": "Vous avez 14 jours pour retourner un article non utilisé.",
}


def answer(payload: dict[str, Any]) -> dict[str, Any]:
    q = str(payload.get("question", "")).lower()
    tool_calls: list[dict[str, Any]] = []
    if "commande" in q and any(ch.isdigit() for ch in q):
        order = "".join(ch for ch in q if ch.isdigit())
        tool_calls.append({"name": "get_order", "arguments": {"id": order}})
        return {"answer": f"Votre commande {order} est en cours de livraison.", "refused": False, "tool_calls": tool_calls, "confidence": 0.9}
    for key, text in FAQ.items():
        if key in q:
            tool_calls.append({"name": "search_faq", "arguments": {"q": key}})
            return {"answer": text, "refused": False, "tool_calls": tool_calls, "confidence": 0.95}
    return {"answer": "Je ne peux pas répondre à cette question, je transmets à un conseiller.", "refused": True, "tool_calls": [], "confidence": 0.3}
