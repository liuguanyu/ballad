"""
Skill search — mirrors Go: ~/devspace/deepx-code/skill/search.go

Searches Clawhub: GET /api/v1/search?q= → concurrent enrich details.
"""
from __future__ import annotations

import concurrent.futures
import json
import httpx
from typing import TYPE_CHECKING

from deepx.skill.source import (
    CLAWHUB_BASE,
    CLAWHUB_WEB,
    list_sources,
    SkillSource,
    RemoteSkillInfo,
)

if TYPE_CHECKING:
    pass

HTTP_TIMEOUT = 8.0  # seconds per source


def search_skills(query: str, source_id: str = "") -> list[RemoteSkillInfo]:
    """
    Search all enabled sources (or just source_id if non-empty).
    Each source has its own 8s timeout; failure of one does not affect others.
    Results sorted by downloads descending.
    """
    pool = []
    for src in list_sources():
        if not src.enabled:
            continue
        if source_id and src.id != source_id:
            continue
        pool.append(src)

    results: list[RemoteSkillInfo] = []

    def search_one(src: SkillSource) -> list[RemoteSkillInfo]:
        if src.type != "clawhub":
            return []
        try:
            return _clawhub_search(src, query)
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(pool)) as executor:
        futures = {executor.submit(search_one, src): src for src in pool}
        for fut in concurrent.futures.as_completed(futures):
            results.extend(fut.result())

    results.sort(key=lambda x: x.downloads, reverse=True)
    return results


def _clawhub_search(src: SkillSource, query: str) -> list[RemoteSkillInfo]:
    """Search Clawhub: list slugs then concurrent enrich."""
    base = src.url or CLAWHUB_BASE
    q = query.strip() or "skill"
    url = f"{base.rstrip('/')}/api/v1/search?q="

    with httpx.Client(timeout=HTTP_TIMEOUT) as client:
        resp = client.get(url, params={"q": q})
        resp.raise_for_status()
        data = resp.json()

    raw_results = data.get("results", [])
    infos: list[RemoteSkillInfo] = []
    for r in raw_results:
        version = r.get("version") or ""
        owner = r.get("ownerHandle", "")
        url_str = ""
        if owner:
            url_str = f"{CLAWHUB_WEB}/{owner}/{r['slug']}"
        infos.append(RemoteSkillInfo(
            name=r.get("displayName", ""),
            description=r.get("summary", ""),
            version=version,
            source_id=src.id,
            remote_ref=r.get("slug", ""),
            author=owner,
            url=url_str,
        ))

    # Concurrent enrich: fetch detail for each skill to get downloads/stars
    def enrich(info: RemoteSkillInfo) -> RemoteSkillInfo:
        if not info.remote_ref:
            return info
        detail_url = f"{base.rstrip('/')}/api/v1/skills/{info.remote_ref}"
        try:
            with httpx.Client(timeout=HTTP_TIMEOUT) as client:
                resp = client.get(detail_url)
                resp.raise_for_status()
                d = resp.json()
            skill_stats = d.get("skill", {}).get("stats", {})
            owner_data = d.get("owner", {})
            latest = d.get("latestVersion", {})
            if not info.version:
                info.version = latest.get("version", "")
            if owner_data.get("displayName"):
                info.author = owner_data["displayName"]
            info.downloads = skill_stats.get("downloads", 0)
            info.stars = skill_stats.get("stars", 0)
        except Exception:
            pass
        return info

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        infos = list(executor.map(enrich, infos))

    infos.sort(key=lambda x: x.downloads, reverse=True)
    return infos