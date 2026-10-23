import os
import struct
import tempfile
import unittest

from dnsd import parser
from dnsd.blocklist import Blocklist, BlocklistError
from dnsd.cache import Cache
from dnsd.parser import AAAA, NOERROR, NXDOMAIN, A
from dnsd.resolver import BLOCKED, LOCAL, Resolver
from dnsd.zone import Zone

MX = parser.TYPES["MX"]


def query(name, qtype=A, ident=0x1234):
    wire = b"".join(bytes([len(label)]) + label.encode() for label in name.rstrip(".").split("."))
    return struct.pack("!HHHHHH", ident, 0x0100, 1, 0, 0, 0) + wire + b"\x00" + struct.pack("!HH", qtype, 1)


def blocklist_file(text):
    f = tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8")
    with f:
        f.write(text)
    return f.name


class LoadTest(unittest.TestCase):
    def load(self, text):
        path = blocklist_file(text)
        self.addCleanup(os.unlink, path)
        return Blocklist.from_file(path)

    def test_comments_blank_lines_case_and_dots(self):
        blocklist = self.load(
            "# ads\n\n   # indented comment\nAds.Example.COM\ntracker.net.\n  \t\nmetrics.io  \n"
        )
        self.assertEqual(blocklist.domains(), ["ads.example.com.", "metrics.io.", "tracker.net."])

    def test_two_fields_on_a_line(self):
        path = blocklist_file("ok.com\n0.0.0.0 ads.com\n")
        self.addCleanup(os.unlink, path)
        with self.assertRaisesRegex(BlocklistError, r":2: expected one domain"):
            Blocklist.from_file(path)

    def test_invalid_name_reports_line(self):
        path = blocklist_file("ok.com\n\n" + "a" * 64 + ".com\n")
        self.addCleanup(os.unlink, path)
        with self.assertRaisesRegex(BlocklistError, r":3: invalid name"):
            Blocklist.from_file(path)

    def test_missing_file(self):
        with self.assertRaises(OSError):
            Blocklist.from_file("/nonexistent/blocklist.txt")


class MatchTest(unittest.TestCase):
    def setUp(self):
        self.blocklist = Blocklist()
        self.blocklist.add("ads.example.com")

    def test_exact_and_subdomains(self):
        self.assertTrue(self.blocklist.blocks("ads.example.com."))
        self.assertTrue(self.blocklist.blocks("ads.example.com"))
        self.assertTrue(self.blocklist.blocks("x.ads.example.com."))
        self.assertTrue(self.blocklist.blocks("a.b.ads.example.com."))

    def test_whole_labels_only(self):
        self.assertFalse(self.blocklist.blocks("xads.example.com."))
        self.assertFalse(self.blocklist.blocks("example.com."))
        self.assertFalse(self.blocklist.blocks("ads.example.com.evil."))
        self.assertFalse(self.blocklist.blocks("."))

    def test_case_insensitive(self):
        self.assertTrue(self.blocklist.blocks("X.ADS.Example.Com."))

    def test_empty_blocklist(self):
        self.assertFalse(Blocklist().blocks("ads.example.com."))


class ChangeTest(unittest.TestCase):
    def test_add_is_idempotent(self):
        blocklist = Blocklist()
        self.assertEqual(blocklist.add("Ads.Example.com"), "ads.example.com.")
        blocklist.add("ads.example.com.")
        self.assertEqual(blocklist.domains(), ["ads.example.com."])

    def test_add_rejects_bad_input(self):
        blocklist = Blocklist()
        for bad in (None, 42, ["ads.com"], "", ".", "a..com", "a" * 64 + ".com"):
            with self.assertRaises(BlocklistError, msg=repr(bad)):
                blocklist.add(bad)
        self.assertEqual(blocklist.domains(), [])

    def test_delete(self):
        blocklist = Blocklist()
        blocklist.add("ads.example.com")
        self.assertFalse(blocklist.delete("x.ads.example.com"))
        self.assertFalse(blocklist.delete("other.com"))
        self.assertTrue(blocklist.blocks("x.ads.example.com."))
        self.assertTrue(blocklist.delete("ADS.example.com"))
        self.assertFalse(blocklist.blocks("ads.example.com."))
        self.assertFalse(blocklist.delete("ads.example.com."))
        self.assertEqual(blocklist.domains(), [])


class NoUpstream:
    def __init__(self):
        self.calls = 0

    def forward(self, query):
        self.calls += 1
        return None


class ResolverTest(unittest.TestCase):
    def setUp(self):
        zone = Zone()
        zone.add("ads.home.lan.", "A", 300, "192.168.1.20")
        self.blocklist = Blocklist()
        self.blocklist.add("ads.example.com")
        self.blocklist.add("ads.home.lan")
        self.forwarder = NoUpstream()
        self.events = []
        self.resolver = Resolver(zone, Cache(), self.forwarder, self.blocklist, [self.events.append])

    def ask(self, name, qtype=A):
        return parser.parse_message(self.resolver.handle(query(name, qtype), "127.0.0.1", 512))

    def test_blocked_a(self):
        reply = self.ask("X.Ads.Example.com", A)
        self.assertEqual(reply.rcode, NOERROR)
        self.assertFalse(reply.aa)
        self.assertTrue(reply.ra)
        self.assertEqual(reply.question.name, "X.Ads.Example.com.")
        self.assertEqual([(rr.value, rr.ttl) for rr in reply.answers], [("0.0.0.0", 60)])
        self.assertEqual(self.events[-1].result, BLOCKED)
        self.assertEqual(self.forwarder.calls, 0)

    def test_blocked_aaaa(self):
        reply = self.ask("ads.example.com", AAAA)
        self.assertEqual(reply.rcode, NOERROR)
        self.assertEqual([(rr.value, rr.ttl) for rr in reply.answers], [("::", 60)])

    def test_blocked_other_type(self):
        reply = self.ask("ads.example.com", MX)
        self.assertEqual(reply.rcode, NXDOMAIN)
        self.assertFalse(reply.aa)
        self.assertEqual(reply.answers, [])
        self.assertEqual(self.events[-1].result, BLOCKED)

    def test_local_zone_wins(self):
        reply = self.ask("ads.home.lan", A)
        self.assertTrue(reply.aa)
        self.assertEqual([rr.value for rr in reply.answers], ["192.168.1.20"])
        self.assertEqual(self.events[-1].result, LOCAL)

    def test_deleted_entry_is_forwarded(self):
        self.blocklist.delete("ads.example.com")
        self.ask("ads.example.com", A)
        self.assertEqual(self.forwarder.calls, 1)


if __name__ == "__main__":
    unittest.main()
