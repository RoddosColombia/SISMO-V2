"""
Audit Fetch — Paginate all journals from Alegra and cache locally.

Uses sync httpx for reliability (batch job, not request handler).
Paginates with start/limit params until all journals are retrieved.
Throttles requests aggressively to avoid Alegra 503 rate limiting.

Strategy:
  - 1 second between individual requests
  - Batch of 50 journals → pause 10 seconds → next batch
  - Resume from partial cache (don't re-fetch already-cached journals)
  - Progress display with percentage
"""
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

ALEGRA_BASE_URL = "https://api.alegra.com/api/v1"
CACHE_DIR = Path(__file__).parent / "cache"

# Batching constants
THROTTLE_BETWEEN_REQUESTS = 1.0   # 1s between every request
BATCH_SIZE = 50                    # journals per batch
BATCH_PAUSE = 10                   # 10s pause between batches
PAGE_LIMIT = 10                    # Alegra page size (small to avoid 503)


def _get_auth() -> tuple[str, str]:
    return (
        os.environ.get("ALEGRA_EMAIL", "contabilidad@roddos.com"),
        os.environ.get("ALEGRA_TOKEN", ""),
    )


def _get_with_retry(url: str, params: dict | None, auth: tuple, max_retries: int = 5) -> httpx.Response:
    """GET with retry on 429/503. Exponential backoff up to 60s."""
    for attempt in range(max_retries):
        try:
            resp = httpx.get(url, params=params, auth=auth, timeout=90.0)
            resp.raise_for_status()
            return resp
        except httpx.HTTPStatusError as e:
            if e.response.status_code in (429, 503) and attempt < max_retries - 1:
                wait = min(10 * (attempt + 1), 60)
                print(f"    Alegra {e.response.status_code}, retrying in {wait}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise
        except (httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            if attempt < max_retries - 1:
                wait = min(10 * (attempt + 1), 60)
                print(f"    Timeout, retrying in {wait}s... (attempt {attempt+1}/{max_retries})")
                time.sleep(wait)
                continue
            raise
    raise RuntimeError("Unreachable")


async def fetch_all_journals(
    use_cache: bool = True,
    cache_file: str | None = None,
) -> list[dict]:
    """
    Fetch ALL journals from Alegra via paginated GET /journals.
    Uses sync httpx internally for reliability.
    """
    return fetch_all_journals_sync(use_cache=use_cache, cache_file=cache_file)


def _load_partial_cache(cache_path: Path) -> list[dict]:
    """Load journals from partial cache if it exists."""
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            journals = cached.get("journals", [])
            if journals:
                return journals
        except (json.JSONDecodeError, KeyError):
            pass
    return []


def fetch_all_journals_sync(
    use_cache: bool = True,
    cache_file: str | None = None,
) -> list[dict]:
    """
    Sync version: Fetch ALL journals from Alegra.

    Strategy:
      1. Check if full cache is fresh (< 1 hour) → return immediately
      2. Load partial cache → skip already-fetched journal IDs
      3. Paginate remaining journals with aggressive throttling:
         - 1s between individual requests
         - Batch of 50 details → 10s pause → next batch
      4. Save cache incrementally every 50 journals
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cache_path = Path(cache_file) if cache_file else CACHE_DIR / "journals_all.json"

    # Check cache freshness — if fresh, return immediately
    if use_cache and cache_path.exists():
        age_seconds = time.time() - cache_path.stat().st_mtime
        if age_seconds < 3600:  # 1 hour
            with open(cache_path, "r", encoding="utf-8") as f:
                cached = json.load(f)
            journals = cached.get("journals", [])
            if journals:
                print(f"  Cache fresh ({int(age_seconds)}s old), {len(journals)} journals loaded.")
                return journals

    auth = _get_auth()

    # Step 1: Load partial cache to resume
    cached_journals = _load_partial_cache(cache_path) if use_cache else []
    cached_ids = {str(j.get("id")) for j in cached_journals if j.get("id")}
    if cached_journals:
        print(f"  Resuming from partial cache: {len(cached_journals)} journals already fetched.")

    # Step 2: Get full list of journal IDs via paginated listing
    print("  Discovering all journal IDs...")
    all_summary_ids = []
    start = 0
    total = None

    while True:
        params = {"start": start, "limit": PAGE_LIMIT, "metadata": "true", "order_direction": "ASC"}
        response = _get_with_retry(f"{ALEGRA_BASE_URL}/journals", params, auth)
        data = response.json()

        if isinstance(data, dict) and "data" in data:
            summaries = data["data"]
            if total is None:
                total = data.get("metadata", {}).get("total", 0)
                print(f"  Total journals in Alegra: {total}")
        elif isinstance(data, list):
            summaries = data
        else:
            break

        if not summaries:
            break

        for s in summaries:
            sid = str(s.get("id", ""))
            if sid:
                all_summary_ids.append(sid)

        start += PAGE_LIMIT
        if total and start >= total:
            break
        if len(summaries) < PAGE_LIMIT:
            break

        time.sleep(THROTTLE_BETWEEN_REQUESTS)

    print(f"  Discovered {len(all_summary_ids)} journal IDs.")

    # Step 3: Determine which IDs need fetching
    ids_to_fetch = [sid for sid in all_summary_ids if sid not in cached_ids]
    print(f"  Need to fetch details for {len(ids_to_fetch)} journals ({len(cached_ids)} already cached).")

    if not ids_to_fetch and cached_journals:
        _save_cache(cache_path, cached_journals)
        return cached_journals

    # Step 4: Fetch detail for each missing journal with batching
    all_journals = list(cached_journals)  # Start from cached
    batch_count = 0

    for i, jid in enumerate(ids_to_fetch):
        try:
            detail_resp = _get_with_retry(f"{ALEGRA_BASE_URL}/journals/{jid}", None, auth)
            all_journals.append(detail_resp.json())
        except Exception as e:
            print(f"    WARN: Failed to fetch journal {jid}: {e}")
            # Append a minimal placeholder so we don't lose track
            all_journals.append({"id": jid, "_fetch_error": str(e)})

        batch_count += 1
        fetched_new = i + 1
        total_have = len(all_journals)
        total_expected = total or len(all_summary_ids)
        pct = round(total_have / total_expected * 100, 1) if total_expected else 0

        # Progress display
        if fetched_new % 10 == 0 or fetched_new == len(ids_to_fetch):
            print(f"  Fetched {total_have}/{total_expected} ({pct}%) — {len(ids_to_fetch) - fetched_new} remaining")

        # Batch pause: every BATCH_SIZE detail fetches, pause BATCH_PAUSE seconds
        if batch_count >= BATCH_SIZE and fetched_new < len(ids_to_fetch):
            print(f"  Batch of {BATCH_SIZE} complete — pausing {BATCH_PAUSE}s to respect rate limits...")
            _save_cache(cache_path, all_journals)
            time.sleep(BATCH_PAUSE)
            batch_count = 0
        else:
            # Normal throttle between individual requests
            if fetched_new < len(ids_to_fetch):
                time.sleep(THROTTLE_BETWEEN_REQUESTS)

    # Final save
    _save_cache(cache_path, all_journals)
    print(f"  Done. {len(all_journals)} journals cached.")
    return all_journals


def _save_cache(cache_path: Path, journals: list[dict]) -> None:
    """Save journals to cache file (incremental save support)."""
    cache_data = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total": len(journals),
        "journals": journals,
    }
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(cache_data, f, ensure_ascii=False)
