"""Small in-process TTL cache.

Used for slow-changing lookup data (states, districts, NIC codes) so
dropdown/autocomplete requests don't hit Snowflake on every page load.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable


class TTLCache:
    def __init__(self, ttl_seconds: float):
        self.ttl = ttl_seconds
        self._lock = threading.Lock()
        self._store: dict[Any, tuple[Any, float]] = {}

    def get_or_set(self, key: Any, compute: Callable[[], Any]) -> Any:
        with self._lock:
            entry = self._store.get(key)
            if entry is not None:
                value, expires_at = entry
                if expires_at > time.time():
                    return value

        value = compute()

        with self._lock:
            self._store[key] = (value, time.time() + self.ttl)

        return value
