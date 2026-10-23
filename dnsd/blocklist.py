import threading

from dnsd.zone import ZoneError, canonical, check_name


class BlocklistError(ValueError):
    pass


class Blocklist:
    def __init__(self):
        self._domains = set()
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path):
        blocklist = cls()
        blocklist.load(path)
        return blocklist

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                fields = line.split("#", 1)[0].split()
                if not fields:
                    continue
                if len(fields) != 1:
                    raise BlocklistError(f"{path}:{number}: expected one domain")
                try:
                    self.add(fields[0])
                except ValueError as e:
                    raise BlocklistError(f"{path}:{number}: {e}") from None

    def add(self, domain):
        if not isinstance(domain, str):
            raise BlocklistError("domain must be a string")
        try:
            domain = check_name(domain)
        except ZoneError as e:
            raise BlocklistError(str(e)) from None
        with self._lock:
            self._domains.add(domain)
        return domain

    def delete(self, domain):
        domain = canonical(domain)
        with self._lock:
            if domain not in self._domains:
                return False
            self._domains.remove(domain)
            return True

    def domains(self):
        with self._lock:
            return sorted(self._domains)

    def blocks(self, name):
        name = canonical(name)
        with self._lock:
            while name:
                if name in self._domains:
                    return True
                name = name.split(".", 1)[1]
            return False
