# pplx_client.py
# Thin client for Perplexity Chat Completions API to discover URLs.

from __future__ import annotations
import os, re, json, time
import typing as t
import requests

def _extract_urls(text: str) -> list[str]:
    urls = re.findall(r'https?://[^\s)>\]"}]+', text, flags=re.I)
    out, seen = [], set()
    for u in urls:
        u = u.rstrip('.,);:')
        if u not in seen:
            seen.add(u); out.append(u)
    return out

def pplx_search_sources(player: str, *, max_urls: int = 12, api_key: str | None = None, model: str = "sonar-pro") -> dict:
    """
    Returns: {"prompt": <str>, "answer": <str>, "citations": [url,...], "urls": [url,...]}
    """
    key = api_key or os.getenv("PERPLEXITY_API_KEY")
    assert key, "Missing PERPLEXITY_API_KEY (env var). In Colab, set it from Secrets."

    base = "https://api.perplexity.ai/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    system = (
        "You are a research assistant. Return reputable URLs that directly reference "
        "specific soccer trading cards (set, year, variant, grade/serial where possible). "
        "Prefer official marketplaces (eBay item pages, PWCC, Goldin), manufacturer pages, "
        "and credible hobby references. Include recent/active listings where possible."
    )
    user = (
        f"Player: {player}\n"
        "Task: Find specific active or recent listings and authoritative references for this player's cards. "
        "Return direct item or reference URLs (not just homepages). Include a mix of marketplaces and credible sources."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.2,
        "top_p": 0.9
    }
    r = requests.post(base, headers=headers, data=json.dumps(payload), timeout=30)
    r.raise_for_status()
    data = r.json()

    answer = ""
    try:
        answer = data["choices"][0]["message"]["content"]
    except Exception:
        answer = json.dumps(data)[:2000]

    citations = []
    try:
        citations = data.get("citations") or data["choices"][0]["message"].get("citations") or []
    except Exception:
        citations = []

    urls = list(dict.fromkeys((citations or []) + _extract_urls(answer)))[:max_urls]
    return {"prompt": user, "answer": answer, "citations": citations, "urls": urls}
