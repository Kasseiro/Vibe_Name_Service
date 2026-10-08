import ipaddress
import threading

ANSWER = "ANSWER"
NODATA = "NODATA"
NXDOMAIN = "NXDOMAIN"
NOT_LOCAL = "NOT_LOCAL"

TYPES = ("A", "AAAA", "CNAME")
MAX_TTL = 2**31 - 1


class ZoneError(ValueError):
    pass


def canonical(name):
    name = name.strip().lower()
    if not name.endswith("."):
        name += "."
    return name


def check_name(name):
    name = canonical(name)
    labels = name[:-1].split(".")
    if len(name) > 254 or any(not 0 < len(label) <= 63 for label in labels):
        raise ZoneError(f"invalid name: {name!r}")
    return name


def check_ttl(ttl):
    try:
        ttl = int(ttl)
    except (TypeError, ValueError):
        raise ZoneError(f"invalid ttl: {ttl!r}") from None
    if not 0 <= ttl <= MAX_TTL:
        raise ZoneError(f"invalid ttl: {ttl!r}")
    return ttl


def check_value(rtype, value):
    try:
        if rtype == "A":
            return str(ipaddress.IPv4Address(value.strip()))
        if rtype == "AAAA":
            return str(ipaddress.IPv6Address(value.strip()))
    except (AttributeError, ValueError):
        raise ZoneError(f"invalid {rtype} value: {value!r}") from None
    if not isinstance(value, str):
        raise ZoneError(f"invalid {rtype} value: {value!r}")
    return check_name(value)


def suffix_of(name):
    parent = name.split(".", 1)[1]
    return parent or name


class Zone:
    def __init__(self):
        self._records = {}
        self._lock = threading.Lock()

    @classmethod
    def from_file(cls, path):
        zone = cls()
        zone.load(path)
        return zone

    def load(self, path):
        with open(path, encoding="utf-8") as f:
            for number, line in enumerate(f, 1):
                fields = line.split(";", 1)[0].split()
                if not fields:
                    continue
                if len(fields) != 5 or fields[2].upper() != "IN":
                    raise ZoneError(f"{path}:{number}: expected 'name ttl IN type value'")
                name, ttl, _, rtype, value = fields
                if not name.endswith("."):
                    raise ZoneError(f"{path}:{number}: name must end with a dot")
                try:
                    self.add(name, rtype, ttl, value)
                except ZoneError as e:
                    raise ZoneError(f"{path}:{number}: {e}") from None

    def add(self, name, rtype, ttl, value):
        if not isinstance(name, str) or not isinstance(rtype, str):
            raise ZoneError("name and type must be strings")
        rtype = rtype.upper()
        if rtype not in TYPES:
            raise ZoneError(f"unsupported type: {rtype!r}")
        name = check_name(name)
        ttl = check_ttl(ttl)
        value = check_value(rtype, value)
        with self._lock:
            rrsets = self._records.get(name, {})
            if any((other == "CNAME") != (rtype == "CNAME") for other in rrsets):
                raise ZoneError(f"{name} cannot have CNAME together with other types")
            values = rrsets.setdefault(rtype, {})
            if rtype == "CNAME":
                values.clear()
            values[value] = ttl
            self._records[name] = rrsets
        return {"name": name, "type": rtype, "ttl": ttl, "value": value}

    def delete(self, name, rtype):
        name = canonical(name)
        rtype = rtype.upper()
        with self._lock:
            rrsets = self._records.get(name, {})
            if rtype not in rrsets:
                return False
            del rrsets[rtype]
            if not rrsets:
                del self._records[name]
            return True

    def records(self):
        with self._lock:
            return [
                record
                for name, rrsets in self._records.items()
                for rtype in rrsets
                for record in self._rrset(name, rtype)
            ]

    def lookup(self, name, qtype):
        name = canonical(name)
        qtype = qtype.upper()
        with self._lock:
            if name not in self._records:
                if not self._is_local(name):
                    return NOT_LOCAL, []
                if self._has_descendants(name):
                    return NODATA, []
                return NXDOMAIN, []
            answer = []
            seen = set()
            while True:
                rrsets = self._records.get(name, {})
                if qtype in rrsets:
                    answer += self._rrset(name, qtype)
                    break
                if "CNAME" not in rrsets or name in seen:
                    break
                seen.add(name)
                answer += self._rrset(name, "CNAME")
                name = answer[-1]["value"]
            return (ANSWER if answer else NODATA), answer

    def _rrset(self, name, rtype):
        return [
            {"name": name, "type": rtype, "ttl": ttl, "value": value}
            for value, ttl in self._records[name][rtype].items()
        ]

    def _is_local(self, name):
        suffixes = {suffix_of(owner) for owner in self._records}
        return any(name == s or name.endswith("." + s) for s in suffixes)

    def _has_descendants(self, name):
        return any(owner.endswith("." + name) for owner in self._records)
