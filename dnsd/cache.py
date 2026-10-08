import math
import threading
import time
from collections import OrderedDict

from dnsd.zone import canonical


class Cache:
    def __init__(self, max_size=None, clock=time.monotonic):
        self.hits = 0
        self.misses = 0
        self._max_size = max_size
        self._clock = clock
        self._entries = OrderedDict()
        self._lock = threading.Lock()

    def get(self, name, qtype):
        key = self._key(name, qtype)
        with self._lock:
            entry = self._entries.get(key)
            if entry is not None:
                value, expires = entry
                remaining = expires - self._clock()
                if remaining > 0:
                    self._entries.move_to_end(key)
                    self.hits += 1
                    return value, math.ceil(remaining)
                del self._entries[key]
            self.misses += 1
            return None

    def put(self, name, qtype, value, ttl):
        key = self._key(name, qtype)
        with self._lock:
            self._entries.pop(key, None)
            if ttl <= 0 or self._max_size == 0:
                return
            now = self._clock()
            if self._max_size is not None and len(self._entries) >= self._max_size:
                self._purge(now)
            while self._max_size is not None and len(self._entries) >= self._max_size:
                self._entries.popitem(last=False)
            self._entries[key] = (value, now + ttl)

    def purge(self):
        with self._lock:
            self._purge(self._clock())

    def clear(self):
        with self._lock:
            self._entries.clear()

    def stats(self):
        with self._lock:
            return {"cache_hits": self.hits, "cache_misses": self.misses}

    def __len__(self):
        with self._lock:
            return len(self._entries)

    def _purge(self, now):
        for key in [k for k, (_, expires) in self._entries.items() if expires <= now]:
            del self._entries[key]

    @staticmethod
    def _key(name, qtype):
        return canonical(name), str(qtype).upper()
