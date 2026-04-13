"""
Audit Fetch — Paginate all journals from Alegra and cache locally.

Uses AlegraClient.get() for read-only access.
Paginates with start/limit params until all journals are retrieved.
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ALEGRA_BASE_URL = "https://api.alegra.com/api/v1"
CACHE_DIR = Path(__file__).parent / "cache"


def _get_auth() -> tuple[str, str]:
    return (
        os.environ.get("ALEGRA_EMAIL", "contabilidad@roddos.com"),
        os.environ.get("ALEGRA_TOKEN", ""),
    )


async def fetch_all_journals(
    use_cache: bool = True,
    cache_file: str | None = None,
) -> list[dict]:
    """
    Fetch ALL journals from Alegra via paginated GET /journals.

    Args:
        use_cache: If True, return cached data if fresh (< 1 hour old).
        cache_file: Override cache file path.

    Returns:
        List of journal dicts with full entry details.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = Path(cache_file) if cache_file else CACHE_DIR / "journals_all.json"

    # Check cache freshness
    if use_cache and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < 3600:  # 1 hour
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            return cached.get("journals", [])

    # Fetch from Alegra with pagination
    auth = _get_auth()
    all_journals = []
    start = 0
    limit = 30  # Alegra default page size
    total = None

    async with httpx.AsyncClient(timeout=60.0) as http:
        while True:
            params = {"start": start, "limit": limit, "metadata": "true", "order_direction": "ASC"}

            # Retry up to 3 times on transient errors (429, 503)
            for attempt in range(3):
                try:
                    response = await http.get(
                        f"{ALEGRA_BASE_URL}/journals",
                        params=params,
                        auth=auth,
                    )
                    response.raise_for_status()
                    break
                except httpx.HTTPStatusError as e:
                    if e.response.status_code in (429, 503) and attempt < 2:
                        import asyncio
                        await asyncio.sleep(5 * (attempt + 1))
                        continue
                    raise

            data = response.json()

            # Handle metadata response format
            if isinstance(data, dict) and "data" in data:
                journals = data["data"]
                if total is None:
                    total = data.get("metadata", {}).get("total", 0)
            elif isinstance(data, list):
                journals = data
            else:
                break

            if not journals:
                break

            # For each journal, fetch full details (entries with account IDs)
            for idx, j_summary in enumerate(journals):
                jid = j_summary.get("id")
                if not jid:
                    continue

                for retry in range(3):
                    try:
                        detail_resp = await http.get(
                            f"{ALEGRA_BASE_URL}/journals/{jid}",
                            auth=auth,
                        )
                        if detail_resp.status_code == 200:
                            all_journals.append(detail_resp.json())
                        else:
                            all_journals.append(j_summary)
                        break
                    except (httpx.HTTPStatusError, httpx.ReadTimeout):
                        if retry < 2:
                            import asyncio as _aio
                            await _aio.sleep(3 * (retry + 1))
                        else:
                            all_journals.append(j_summary)

                # Throttle: 0.5s between detail fetches to avoid Alegra rate limits
                if idx < len(journals) - 1:
                    import asyncio as _aio
                    await _aio.sleep(0.5)

            start += limit
            if total and start >= total:
                break
            if len(journals) < limit:
                break

            # Rate limit: pause between pages to avoid Alegra 503
            import asyncio
            await asyncio.sleep(2)

    # Cache results
    cache_data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total": len(all_journals),
        "journals": all_journals,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False, indent=2)

    return all_journals


async def fetch_journal_by_id(journal_id: int | str) -> dict | None:
    """Fetch a single journal by ID."""
    auth = _get_auth()
    async with httpx.AsyncClient(timeout=30.0) as http:
        resp = await http.get(
            f"{ALEGRA_BASE_URL}/journals/{journal_id}",
            auth=auth,
        )
        if resp.status_code == 200:
            return resp.json()
    return None
