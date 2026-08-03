"""
Web search augmentation for chat.

Uses the configured search engine (default SerpAPI) and returns compact
text snippets for grounding model responses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.websearch")


async def _search_duckduckgo(query: str, max_results: int) -> List[Dict[str, str]]:
    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 NovaAI/1.0"},
        )
        resp.raise_for_status()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for result in soup.select(".result")[:max_results]:
        link = result.select_one("a.result__a")
        snippet = result.select_one(".result__snippet")
        if link:
            results.append(
                {
                    "title": link.get_text(" ", strip=True),
                    "url": link.get("href", ""),
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                }
            )
    return results


async def _search_serpapi(query: str, max_results: int) -> List[Dict[str, str]]:
    if not settings.SEARCH_API_KEY:
        return []

    import httpx

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            "https://serpapi.com/search",
            params={
                "engine": "google",
                "q": query,
                "api_key": settings.SEARCH_API_KEY,
                "num": max_results,
            },
        )
        resp.raise_for_status()
        data = resp.json()

    results = []
    for item in data.get("organic_results", [])[:max_results]:
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
        )
    return results


async def web_search_augment(query: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Run a live web search and return (context_text, citations)."""
    engine = settings.SEARCH_ENGINE.lower()
    max_results = settings.SEARCH_MAX_RESULTS

    try:
        if engine == "duckduckgo":
            results = await _search_duckduckgo(query, max_results)
        else:  # serpapi, google, bing
            results = await _search_serpapi(query, max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web search failed: %s", exc)
        return "", []

    if not results:
        return "", []

    context_lines = []
    citations: List[Dict[str, Any]] = []
    for i, r in enumerate(results, start=1):
        context_lines.append(f"[{i}] {r['title']}\n{r['snippet']}\nURL: {r['url']}")
        citations.append(
            {
                "index": i,
                "type": "web",
                "title": r["title"],
                "url": r["url"],
                "content": r["snippet"],
            }
        )

    return "\n\n".join(context_lines), citations
