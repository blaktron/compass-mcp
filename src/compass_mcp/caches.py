"""Client-side caches for trades, users, and projects."""

from __future__ import annotations

import asyncio
import time
from typing import Any, Iterable

from .client import CompassClient
from .errors import CompassApiError


def _trade_code(trade: dict[str, Any]) -> str:
    return "".join(trade.get(f"division_{n}") or "" for n in range(1, 6))


class TradesCache:
    def __init__(self, client: CompassClient) -> None:
        self._client = client
        self._resolved: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    def _slim(self, trade: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": trade.get("id"),
            "name": trade.get("name"),
            "type": trade.get("type"),
            "level": trade.get("level"),
            "code": _trade_code(trade),
        }

    async def resolve(self, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = [str(i) for i in dict.fromkeys(ids)]
        async with self._lock:
            missing = [i for i in wanted if i not in self._resolved]
            if missing:
                resp = await self._client.request(
                    "POST", "/hub/trades/retrieval", json_body={"id": missing}
                )
                for trade in (resp or {}).get("data") or []:
                    if trade.get("id"):
                        self._resolved[str(trade["id"])] = self._slim(trade)
        return {
            i: self._resolved.get(i, {"id": i, "error": "not returned by /hub/trades/retrieval"})
            for i in wanted
        }


class UserCache:
    def __init__(self, client: CompassClient, max_concurrency: int = 5) -> None:
        self._client = client
        self._cache: dict[str, dict[str, Any]] = {}
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @staticmethod
    def _slim(user: dict[str, Any]) -> dict[str, Any]:
        first = (user.get("first_name") or "").strip()
        last = (user.get("last_name") or "").strip()
        return {
            "id": user.get("id"),
            "display_name": (f"{first} {last}").strip() or None,
            "title": user.get("title"),
            "email": user.get("email"),
            "legal_entity_id": user.get("legal_entity_id"),
        }

    async def resolve(self, ids: Iterable[str]) -> dict[str, dict[str, Any]]:
        wanted = [str(i) for i in dict.fromkeys(ids)]
        missing = [i for i in wanted if i not in self._cache]

        async def fetch(uid: str) -> None:
            async with self._semaphore:
                try:
                    user = await self._client.request("GET", f"/hub/users/{uid}")
                except CompassApiError as exc:
                    self._cache[uid] = {"id": uid, "error": f"HTTP {exc.status_code}"}
                    return
                self._cache[uid] = self._slim(user or {})

        if missing:
            await asyncio.gather(*(fetch(uid) for uid in missing))
        return {i: self._cache[i] for i in wanted}


class ProjectIndex:
    """Short-TTL index of projects by `id` and by `internal_id`."""

    def __init__(self, client: CompassClient, ttl_seconds: float = 300.0) -> None:
        self._client = client
        self._ttl = ttl_seconds
        self._by_id: dict[str, dict[str, Any]] = {}
        self._by_internal_id: dict[str, dict[str, Any]] = {}
        self._loaded_at: float = 0.0
        self._lock = asyncio.Lock()

    async def _ensure(self, force: bool = False) -> None:
        async with self._lock:
            if not force and self._by_id and (time.time() - self._loaded_at) < self._ttl:
                return
            result = await self._client.paginate(
                "/select/projects/poll", limit=250, max_pages=40
            )
            self._by_id = {}
            self._by_internal_id = {}
            for project in result["data"]:
                pid = project.get("id")
                if pid:
                    self._by_id[str(pid)] = project
                internal = project.get("internal_id")
                if internal:
                    self._by_internal_id[str(internal)] = project
            self._loaded_at = time.time()

    async def resolve(
        self,
        ids: Iterable[str] | None = None,
        internal_ids: Iterable[str] | None = None,
        force_refresh: bool = False,
    ) -> dict[str, Any]:
        await self._ensure(force=force_refresh)
        projects: dict[str, Any] = {}
        unresolved: list[str] = []
        for pid in dict.fromkeys(str(i) for i in (ids or [])):
            if pid in self._by_id:
                projects[pid] = self._by_id[pid]
            else:
                unresolved.append(pid)
        for internal in dict.fromkeys(str(i) for i in (internal_ids or [])):
            if internal in self._by_internal_id:
                projects[internal] = self._by_internal_id[internal]
            else:
                unresolved.append(internal)
        return {"projects": projects, "unresolved": unresolved}
