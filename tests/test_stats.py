import struct
import unittest

from dnsd import parser
from dnsd.blocklist import Blocklist
from dnsd.cache import Cache
from dnsd.parser import A, ResourceRecord
from dnsd.querylog import QueryLog
from dnsd.resolver import BLOCKED, CACHED, ERROR, FORWARDED, LOCAL, QueryEvent, Resolver
from dnsd.stats import Stats
from dnsd.zone import Zone


def query(name, qtype=A, ident=0x1234, flags=0x0100, qd=1):
    wire = b"".join(bytes([len(label)]) + label.encode() for label in name.rstrip(".").split("."))
    return struct.pack("!HHHHHH", ident, flags, qd, 0, 0, 0) + wire + b"\x00" + struct.pack("!HH", qtype, 1)


def event(time=0.0, result=FORWARDED, name="example.com."):
    return QueryEvent(time, "127.0.0.1", name, "A", result)


class FakeUpstream:
    """Answers every name with one A record, except names starting with fail."""

    def __init__(self):
        self.calls = 0

    def forward(self, packet):
        self.calls += 1
        message = parser.parse_message(packet)
        if message.question.name.startswith("fail."):
            return None
        reply = message.reply()
        reply.answers.append(ResourceRecord.from_text(message.question.name, A, 300, "192.0.2.1"))
        return reply.to_wire()


class StatsTest(unittest.TestCase):
    def test_starts_at_zero(self):
        self.assertEqual(Stats().snapshot(), {"queries": 0, "blocked": 0})

    def test_counts(self):
        stats = Stats()
        for result in (LOCAL, BLOCKED, CACHED, FORWARDED, ERROR, BLOCKED):
            stats(event(result=result))
        self.assertEqual(stats.snapshot(), {"queries": 6, "blocked": 2})


class QueryLogTest(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(QueryLog().entries(), [])

    def test_entry_shape(self):
        log = QueryLog()
        log(QueryEvent(1700000000.5, "192.168.1.5", "Nas.Home.Lan.", "TYPE65280", LOCAL))
        self.assertEqual(log.entries(), [{
            "time": 1700000000.5, "client": "192.168.1.5", "name": "Nas.Home.Lan.",
            "type": "TYPE65280", "result": "local",
        }])

    def test_newest_first_and_limit(self):
        log = QueryLog()
        for i in range(150):
            log(event(time=float(i)))
        self.assertEqual(len(log.entries()), 100)
        self.assertEqual([e["time"] for e in log.entries(3)], [149.0, 148.0, 147.0])
        self.assertEqual(log.entries(0), [])
        self.assertEqual(len(log.entries(1000)), 150)

    def test_ordered_by_arrival_time(self):
        log = QueryLog()
        log(event(time=2.0))
        log(event(time=1.0))  # slow forwarded query, answered last
        log(event(time=3.0))
        self.assertEqual([e["time"] for e in log.entries()], [3.0, 2.0, 1.0])

    def test_keeps_the_most_recent_1000(self):
        log = QueryLog()
        for i in range(1500):
            log(event(time=float(i)))
        entries = log.entries(5000)
        self.assertEqual(len(entries), 1000)
        self.assertEqual((entries[0]["time"], entries[-1]["time"]), (1499.0, 500.0))


class ResolverCountingTest(unittest.TestCase):
    def setUp(self):
        zone = Zone()
        zone.add("nas.home.lan.", "A", 300, "192.168.1.10")
        blocklist = Blocklist()
        blocklist.add("ads.example.com")
        self.cache = Cache()
        self.stats = Stats()
        self.log = QueryLog()
        self.resolver = Resolver(zone, self.cache, FakeUpstream(), blocklist, [self.stats, self.log])

    def handle(self, data):
        return self.resolver.handle(data, "10.0.0.7", 512)

    def results(self):
        return [e["result"] for e in reversed(self.log.entries())]

    def test_each_result_counted_once(self):
        for name in ("nas.home.lan", "ads.example.com", "example.org", "example.org", "fail.example"):
            self.handle(query(name))
        self.assertEqual(self.results(), [LOCAL, BLOCKED, FORWARDED, CACHED, ERROR])
        self.assertEqual(self.stats.snapshot(), {"queries": 5, "blocked": 1})
        # example.org: miss then hit; fail.example: miss. Local and blocked touch neither.
        self.assertEqual(self.cache.stats(), {"cache_hits": 1, "cache_misses": 2})

    def test_log_fields(self):
        self.handle(query("Nas.Home.LAN"))
        (entry,) = self.log.entries()
        self.assertEqual(entry["client"], "10.0.0.7")
        self.assertEqual(entry["name"], "Nas.Home.LAN.")
        self.assertEqual(entry["type"], "A")
        self.assertIsInstance(entry["time"], float)

    def test_uncounted_input(self):
        self.assertIsNone(self.handle(b"\x12\x34\x01"))  # too short: no reply
        self.assertIsNone(self.handle(query("x.com", flags=0x8100)))  # QR=1: no reply
        self.assertIsNotNone(self.handle(query("x.com", qd=2)))  # FORMERR
        self.assertIsNotNone(self.handle(query("x.com", flags=0x2100)))  # opcode 4: NOTIMP
        self.assertEqual(self.stats.snapshot(), {"queries": 0, "blocked": 0})
        self.assertEqual(self.log.entries(), [])
        self.assertEqual(self.cache.stats(), {"cache_hits": 0, "cache_misses": 0})


if __name__ == "__main__":
    unittest.main()
