"""
Web search augmentation for chat.

Uses the configured search engine (default SerpAPI) and returns compact
text snippets for grounding model responses.
"""
from __future__ import annotations

from typing import Any, Dict, List, Tuple
from urllib.parse import parse_qs, unquote, urlparse

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("ai.websearch")

VIDEO_QUERY_HINTS = (
    "video", "youtube", "watch", "tutorial", "how to", "guide", "demo",
    "reels", "shorts", "trailer", "review video",
)

WEATHER_QUERY_HINTS = (
    "weather", "forecast", "temper", "temp ", "temperature", "मौसम", "तापमान",
    "mausam", "moosam", "kitna garam", "kitna thanda", "kitni garmi", "raining",
    "rain", "barish", "humidity", "wind", "aaj ka mausam", "आज का मौसम",
)

# Words never part of a city name — stripped when extracting the location.
_WEATHER_STOPWORDS = {
    "what", "is", "the", "current", "weather", "forecast", "temperature", "temp",
    "today", "now", "in", "at", "of", "for", "like", "please", "give", "tell",
    "me", "short", "answer", "kitna", "kitni", "hai", "ka", "ki", "ke", "mein",
    "main", "aaj", "mausam", "moosam", "temperature", "degree", "celsius",
    "मौसम", "तापमान", "आज", "का", "की", "के", "है", "में", "कितना", "कितनी",
    "गर्म", "ठंड", "rain", "raining", "humidity", "wind", "weather", "outside",
}


async def _open_meteo_weather(query: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Live current weather via Open-Meteo (free, keyless, JSON API).

    Extracts a best-effort location from the query, geocodes it, and returns
    current conditions as grounding context. Returns ("", []) when no location
    can be determined or the API is unreachable.
    """
    import re as _re

    words = _re.findall(r"[\w\u0900-\u097F]+", query.lower())
    location = " ".join(w for w in words if w not in _WEATHER_STOPWORDS and len(w) > 1)
    if not location:
        return "", []

    import httpx

    try:
        async with httpx.AsyncClient(timeout=6) as client:
            geo = await client.get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": location, "count": 1, "language": "en", "format": "json"},
            )
            geo.raise_for_status()
            geos = (geo.json() or {}).get("results") or []
            if not geos:
                return "", []
            top = geos[0]
            w = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": top["latitude"],
                    "longitude": top["longitude"],
                    "current": "temperature_2m,relative_humidity_2m,wind_speed_10m,weather_code",
                    "timezone": "auto",
                },
            )
            w.raise_for_status()
            cur = (w.json() or {}).get("current") or {}
            if not cur:
                return "", []
            name = top.get("name", location.title())
            admin = top.get("admin1")
            country = top.get("country")
            place = name + (f", {admin}" if admin and admin != name else "") + (f", {country}" if country else "")
            temp = cur.get("temperature_2m")
            humidity = cur.get("relative_humidity_2m")
            wind = cur.get("wind_speed_10m")
            code = cur.get("weather_code")
            context = (
                f"[1] (Live weather) Current conditions in {place} "
                f"({top.get('latitude')},{top.get('longitude')}): "
                + (f"temperature {temp}°C, " if temp is not None else "")
                + (f"humidity {humidity}%, " if humidity is not None else "")
                + (f"wind {wind} km/h, " if wind is not None else "")
                + (f"WMO weather code {code}" if code is not None else "")
                + ". (Live data from Open-Meteo)"
            )
            citation = [{
                "index": 1,
                "type": "web",
                "title": f"Open-Meteo live weather for {place}",
                "url": f"https://open-meteo.com/en/docs#latitude={top.get('latitude')}&longitude={top.get('longitude')}",
                "content": context,
            }]
            return context, citation
    except Exception as exc:  # noqa: BLE001
        logger.warning("Open-Meteo failed: %s", exc)
        return "", []


def _is_weather_query(query: str) -> bool:
    q = (query or "").lower()
    return any(hint in q for hint in WEATHER_QUERY_HINTS)


def _direct_url(href: str) -> str:
    """DuckDuckGo HTML wraps links in a redirect (//duckduckgo.com/l/?uddg=...).
    Unwrap it so citations open the real page directly in the browser."""
    if not href:
        return ""
    if href.startswith("//"):
        href = f"https:{href}"
    try:
        qs = parse_qs(urlparse(href).query)
    except ValueError:
        qs = {}
    if qs.get("uddg"):
        direct = unquote(qs["uddg"][0])
        if direct.startswith(("http://", "https://")):
            return direct
    return href


async def _search_duckduckgo_lite(query: str, max_results: int) -> List[Dict[str, str]]:
    """Search via the DuckDuckGo Lite endpoint.

    Lite is far more tolerant of datacenter IPs than html.duckduckgo.com
    (which Render/cloud IPs often get blocked on).
    """
    import httpx

    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://lite.duckduckgo.com/lite/",
            params={"q": query},
            headers={"User-Agent": "Mozilla/5.0 NovaAI/1.0"},
        )
        resp.raise_for_status()

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for link in soup.select("a.result-link")[:max_results]:
        row = link.find_parent("tr")
        snippet_el = None
        if row:
            # The snippet lives in the next table row's .result-snippet cell.
            next_row = row.find_next_sibling("tr")
            if next_row:
                snippet_el = next_row.select_one(".result-snippet")
        results.append(
            {
                "title": link.get_text(" ", strip=True),
                "url": _direct_url(link.get("href", "")),
                "snippet": snippet_el.get_text(" ", strip=True) if snippet_el else "",
            }
        )
    return results


async def _search_duckduckgo(query: str, max_results: int) -> List[Dict[str, str]]:
    import httpx

    async with httpx.AsyncClient(timeout=8) as client:
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
                    "url": _direct_url(link.get("href", "")),
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                }
            )
    return results


def _serpapi_video(item: Dict[str, Any]) -> Dict[str, str]:
    return {
        "title": item.get("title", ""),
        "url": item.get("link") or item.get("url") or "",
        "snippet": item.get("snippet", "") or item.get("description", ""),
        "source": item.get("source", "") or item.get("channel", ""),
        "type": "video",
    }


async def _search_serpapi(query: str, max_results: int) -> List[Dict[str, str]]:
    if not settings.SEARCH_API_KEY:
        return []

    import httpx
    async with httpx.AsyncClient(timeout=8) as client:
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
    seen: set = set()
    for item in data.get("organic_results", [])[:max_results]:
        url = item.get("link", "")
        if url in seen:
            continue
        seen.add(url)
        results.append(
            {
                "title": item.get("title", ""),
                "url": url,
                "snippet": item.get("snippet", ""),
                "type": "web",
            }
        )
    for item in data.get("video_results", [])[:max_results]:
        v = _serpapi_video(item)
        if v["url"] and v["url"] not in seen:
            seen.add(v["url"])
            results.append(v)
    for item in data.get("inline_videos", [])[:max_results]:
        v = _serpapi_video(item)
        if v["url"] and v["url"] not in seen:
            seen.add(v["url"])
            results.append(v)
    return results


async def _search_duckduckgo_youtube(query: str, max_results: int) -> List[Dict[str, str]]:
    """Search YouTube specifically via DuckDuckGo (site:youtube.com)."""
    import httpx

    async with httpx.AsyncClient(timeout=8) as client:
        resp = await client.get(
            "https://html.duckduckgo.com/html/",
            params={"q": f"site:youtube.com {query}"},
            headers={"User-Agent": "Mozilla/5.0 NovaAI/1.0"},
        )
        if resp.status_code != 200:
            return []

        from bs4 import BeautifulSoup

        soup = BeautifulSoup(resp.text, "html.parser")

    results = []
    for result in soup.select(".result")[:max_results]:
        link = result.select_one("a.result__a")
        snippet = result.select_one(".result__snippet")
        if not link:
            continue
        url = _direct_url(link.get("href", ""))
        if "youtube.com" in url or "youtu.be" in url:
            results.append(
                {
                    "title": link.get_text(" ", strip=True),
                    "url": url,
                    "snippet": snippet.get_text(" ", strip=True) if snippet else "",
                    "source": "YouTube",
                    "type": "video",
                }
            )
    return results


def _merge_dedupe(
    web_results: List[Dict[str, str]],
    video_results: List[Dict[str, str]],
    limit: int,
) -> List[Dict[str, str]]:
    by_url: Dict[str, Dict[str, str]] = {}
    for r in [*video_results, *web_results]:
        url = r.get("url", "")
        if not url:
            continue
        if url not in by_url:
            by_url[url] = r
    return list(by_url.values())[:limit]


async def web_search_augment(query: str) -> Tuple[str, List[Dict[str, Any]]]:
    """Run a live web search and return (context_text, citations).

    Runs web and video searches in parallel for speed. Video results are
    limited to 3 to avoid YouTube spam dominating the results.
    """
    import asyncio

    engine = settings.SEARCH_ENGINE.lower()
    max_results = settings.SEARCH_MAX_RESULTS

    # Weather questions are answered deterministically from Open-Meteo's live
    # JSON API — no scraping, no API key, and it works from datacenter IPs
    # where search engines often block requests.
    if _is_weather_query(query):
        context, citations = await _open_meteo_weather(query)
        if context:
            return context, citations

    try:
        if engine == "duckduckgo":
            # Prefer Lite (more tolerant of cloud IPs); fall back to the HTML
            # endpoint, and fetch video results in parallel for speed.
            video_task = asyncio.create_task(_search_duckduckgo_youtube(query, 2))
            results = await _search_duckduckgo_lite(query, max_results)
            if not results:
                results = await _search_duckduckgo(query, max_results)
            video_results = await video_task
        else:  # serpapi, google, bing
            results = await _search_serpapi(query, max_results)
            video_results = []
        results = _merge_dedupe(results, video_results, max_results)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Web search failed: %s", exc)
        return "", []

    if not results:
        return "", []

    context_lines = []
    citations: List[Dict[str, Any]] = []
    for i, r in enumerate(results, start=1):
        rtype = r.get("type", "web")
        label = "Video" if rtype == "video" else "URL"
        context_lines.append(
            f"[{i}] ({label}) {r['title']}\n{r.get('snippet', '')}\n{r['url']}"
        )
        citations.append(
            {
                "index": i,
                "type": rtype,
                "title": r["title"],
                "url": r["url"],
                "content": r.get("snippet", ""),
            }
        )

    return "\n\n".join(context_lines), citations
