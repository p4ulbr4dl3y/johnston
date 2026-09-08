"""Thread-safe bounded least-recently-used (LRU) cache."""

import threading
from collections import OrderedDict
from typing import Generic, Optional, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class LruCache(Generic[K, V]):
    """A thread-safe, size-bounded LRU cache backed by an ``OrderedDict``.

    ``get`` promotes the accessed entry to most-recently-used; ``put`` appends
    the entry and evicts the least-recently-used entry once the size exceeds
    ``maxsize`` (via ``popitem(last=False)``).
    """

    def __init__(self, maxsize: int = 128) -> None:
        if maxsize <= 0:
            raise ValueError("maxsize must be positive")
        self.maxsize = maxsize
        self._data: "OrderedDict[K, V]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: K, default: Optional[V] = None) -> Optional[V]:
        """Return the value for ``key`` (promoting it), or ``default`` if absent."""
        with self._lock:
            if key in self._data:
                value = self._data.pop(key)
                self._data[key] = value  # move to most-recently-used
                return value
            return default

    def put(self, key: K, value: V) -> None:
        """Insert/update ``key`` and evict the least-recently-used entry if over capacity."""
        with self._lock:
            if key in self._data:
                del self._data[key]
            self._data[key] = value
            while len(self._data) > self.maxsize:
                self._data.popitem(last=False)

    def __contains__(self, key: object) -> bool:
        with self._lock:
            return key in self._data

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)

    def __delitem__(self, key: K) -> None:
        with self._lock:
            del self._data[key]

    def __iter__(self):
        with self._lock:
            return iter(list(self._data.keys()))

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def values(self):
        with self._lock:
            return list(self._data.values())

    def items(self):
        with self._lock:
            return list(self._data.items())

    def clear(self) -> None:
        with self._lock:
            self._data.clear()
