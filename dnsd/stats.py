import threading

from dnsd.resolver import BLOCKED


class Stats:
    def __init__(self):
        self.queries = 0
        self.blocked = 0
        self._lock = threading.Lock()

    def __call__(self, event):
        with self._lock:
            self.queries += 1
            if event.result == BLOCKED:
                self.blocked += 1

    def snapshot(self):
        with self._lock:
            return {"queries": self.queries, "blocked": self.blocked}
