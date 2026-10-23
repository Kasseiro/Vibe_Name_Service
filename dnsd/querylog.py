import threading
from collections import deque
from dataclasses import asdict

LOG_SIZE = 1000
DEFAULT_LIMIT = 100


class QueryLog:
    def __init__(self, size=LOG_SIZE):
        self._entries = deque(maxlen=size)
        self._lock = threading.Lock()

    def __call__(self, event):
        with self._lock:
            self._entries.append(event)

    def entries(self, limit=DEFAULT_LIMIT):
        # Events arrive when a query is answered, so a slow forwarded query can
        # land after later ones; newest first goes by arrival time.
        with self._lock:
            events = list(self._entries)
        events.sort(key=lambda event: event.time, reverse=True)
        return [asdict(event) for event in events[:max(limit, 0)]]

    def __len__(self):
        with self._lock:
            return len(self._entries)
