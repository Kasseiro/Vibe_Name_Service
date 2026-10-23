import http.client
import json
import unittest

from dnsd import parser
from dnsd.api import AdminServer
from dnsd.blocklist import Blocklist
from dnsd.cache import Cache
from dnsd.parser import NOERROR, A
from dnsd.querylog import QueryLog
from dnsd.resolver import Resolver
from dnsd.stats import Stats
from dnsd.zone import Zone
from tests.test_stats import FakeUpstream, query


class ApiTest(unittest.TestCase):
    def setUp(self):
        self.zone = Zone()
        self.zone.add("nas.home.lan.", "A", 300, "192.168.1.10")
        self.zone.add("nas.home.lan.", "AAAA", 300, "fd00::10")
        self.blocklist = Blocklist()
        self.blocklist.add("ads.example.com")
        self.cache = Cache()
        self.stats = Stats()
        self.log = QueryLog()
        self.resolver = Resolver(
            self.zone, self.cache, FakeUpstream(), self.blocklist, [self.stats, self.log]
        )
        self.admin = AdminServer(
            "127.0.0.1:0", self.zone, self.blocklist, self.cache, self.stats, self.log
        )
        self.admin.start()
        self.addCleanup(self.admin.close)

    def request(self, method, path, body=None, raw=None, headers=None):
        conn = http.client.HTTPConnection(*self.admin.address[:2], timeout=5)
        self.addCleanup(conn.close)
        if body is not None:
            raw = json.dumps(body)
        conn.request(method, path, body=raw, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        return response, (json.loads(data) if data else None)

    def status(self, method, path, body=None, raw=None):
        return self.request(method, path, body, raw)[0].status

    def ask(self, name, qtype=A):
        return parser.parse_message(self.resolver.handle(query(name, qtype), "10.0.0.7", 512))

    def records(self):
        _, body = self.request("GET", "/records")
        return sorted((r["name"], r["type"], r["ttl"], r["value"]) for r in body)

    # GET

    def test_get_stats(self):
        response, body = self.request("GET", "/stats")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual(body, {"queries": 0, "blocked": 0, "cache_hits": 0, "cache_misses": 0})

    def test_stats_follow_queries(self):
        for name in ("nas.home.lan", "ads.example.com", "example.org", "example.org"):
            self.ask(name)
        _, body = self.request("GET", "/stats")
        self.assertEqual(body, {"queries": 4, "blocked": 1, "cache_hits": 1, "cache_misses": 1})

    def test_get_blocklist(self):
        response, body = self.request("GET", "/blocklist")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual(body, ["ads.example.com."])

    def test_get_records(self):
        response, _ = self.request("GET", "/records")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual(self.records(), [
            ("nas.home.lan.", "A", 300, "192.168.1.10"),
            ("nas.home.lan.", "AAAA", 300, "fd00::10"),
        ])

    def test_get_log(self):
        for name in ("nas.home.lan", "ads.example.com", "example.org"):
            self.ask(name)
        response, body = self.request("GET", "/log")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.getheader("Content-Type"), "application/json")
        self.assertEqual([e["result"] for e in body], ["forwarded", "blocked", "local"])
        self.assertEqual(set(body[0]), {"time", "client", "name", "type", "result"})
        self.assertEqual((body[0]["client"], body[0]["type"]), ("10.0.0.7", "A"))
        _, body = self.request("GET", "/log?limit=2")
        self.assertEqual(len(body), 2)
        _, body = self.request("GET", "/log?limit=0")
        self.assertEqual(body, [])
        _, body = self.request("GET", "/log?limit=1000")
        self.assertEqual(len(body), 3)

    def test_log_limit_errors(self):
        for limit in ("abc", "-1", "1.5", "+5", "", "%D9%A3", "1&limit=2"):
            self.assertEqual(self.status("GET", f"/log?limit={limit}"), 400, limit)

    # /blocklist

    def test_post_blocklist_blocks_immediately(self):
        self.assertEqual(self.ask("tracker.net").rcode, NOERROR)  # forwarded
        self.assertEqual(self.status("POST", "/blocklist", {"domain": "Tracker.NET"}), 201)
        reply = self.ask("x.tracker.net")
        self.assertEqual([rr.value for rr in reply.answers], ["0.0.0.0"])
        self.assertEqual(self.stats.snapshot()["blocked"], 1)

    def test_post_blocklist_twice_lists_once(self):
        self.assertEqual(self.status("POST", "/blocklist", {"domain": "ads.example.com."}), 201)
        self.assertEqual(self.status("POST", "/blocklist", {"domain": "ADS.example.com"}), 201)
        self.assertEqual(self.request("GET", "/blocklist")[1], ["ads.example.com."])

    def test_post_blocklist_bad_body(self):
        for raw in ("not json", "[1, 2]", '"ads.com"', "{}", '{"domain": 5}',
                    '{"domain": null}', '{"domain": ""}', '{"domain": "a..com"}', "[" * 10000):
            self.assertEqual(self.status("POST", "/blocklist", raw=raw), 400, raw[:20])
        self.assertEqual(self.request("GET", "/blocklist")[1], ["ads.example.com."])

    def test_post_without_body(self):
        self.assertEqual(self.status("POST", "/blocklist"), 400)

    def test_delete_blocklist(self):
        self.assertEqual(self.status("DELETE", "/blocklist/x.ads.example.com"), 404)
        self.assertEqual(self.status("DELETE", "/blocklist/ADS.Example.com."), 204)
        self.assertEqual(self.request("GET", "/blocklist")[1], [])
        self.assertEqual(self.status("DELETE", "/blocklist/ads.example.com"), 404)
        self.assertEqual(self.ask("ads.example.com").answers[0].value, "192.0.2.1")  # forwarded

    def test_delete_blocklist_percent_encoded(self):
        self.assertEqual(self.status("DELETE", "/blocklist/ads%2Eexample%2Ecom"), 204)

    # /records

    def test_post_record_answers_immediately(self):
        record = {"name": "Printer.Home.Lan", "type": "A", "ttl": 60, "value": "192.168.1.30"}
        response, body = self.request("POST", "/records", record)
        self.assertEqual(response.status, 201)
        reply = self.ask("printer.home.lan")
        self.assertTrue(reply.aa)
        self.assertEqual([(rr.value, rr.ttl) for rr in reply.answers], [("192.168.1.30", 60)])

    def test_post_record_twice_replaces_ttl(self):
        record = {"name": "nas.home.lan.", "type": "A", "ttl": 30, "value": "192.168.1.10"}
        self.assertEqual(self.status("POST", "/records", record), 201)
        self.assertEqual(self.status("POST", "/records", record), 201)
        self.assertIn(("nas.home.lan.", "A", 30, "192.168.1.10"), self.records())
        self.assertEqual(len(self.records()), 2)

    def test_post_cname(self):
        record = {"name": "files.home.lan", "type": "CNAME", "ttl": 300, "value": "NAS.home.lan"}
        self.assertEqual(self.status("POST", "/records", record), 201)
        reply = self.ask("files.home.lan")
        self.assertEqual([rr.value for rr in reply.answers], ["nas.home.lan.", "192.168.1.10"])

    def test_post_record_bad_body(self):
        good = {"name": "x.home.lan", "type": "A", "ttl": 60, "value": "192.168.1.40"}
        bad = [
            {k: v for k, v in good.items() if k != missing} for missing in good
        ] + [
            {**good, "type": "MX"},
            {**good, "type": 1},
            {**good, "ttl": -1},
            {**good, "ttl": "60"},
            {**good, "ttl": True},
            {**good, "ttl": 60.0},
            {**good, "ttl": 2**31},
            {**good, "value": "999.1.1.1"},
            {**good, "type": "AAAA"},  # IPv4 value
            {**good, "name": 5},
            {**good, "name": "a..home.lan"},
        ]
        for body in bad:
            self.assertEqual(self.status("POST", "/records", body), 400, body)
        self.assertEqual(self.status("POST", "/records", raw="{"), 400)
        self.assertEqual(len(self.records()), 2)

    def test_delete_record(self):
        self.assertEqual(self.status("DELETE", "/records/NAS.home.lan/aaaa"), 204)
        self.assertEqual(self.records(), [("nas.home.lan.", "A", 300, "192.168.1.10")])
        self.assertEqual(self.status("DELETE", "/records/nas.home.lan./AAAA"), 404)
        self.assertEqual(self.status("DELETE", "/records/nas.home.lan/MX"), 404)
        self.assertEqual(self.status("DELETE", "/records/other.home.lan/A"), 404)
        self.assertEqual(self.ask("nas.home.lan", parser.AAAA).answers, [])  # NODATA

    # Paths and methods

    def test_unknown_paths(self):
        for path in ("/", "/nope", "/stats/", "/blocklist/", "/records/a", "/records/a/b/c",
                     "/records//A", "/Stats"):
            self.assertEqual(self.status("GET", path), 404, path)
            self.assertEqual(self.status("DELETE", path), 404, path)
        self.assertEqual(self.status("PUT", "/nope"), 404)

    def test_wrong_method(self):
        cases = {
            "/stats": ("POST", "DELETE", "PUT", "PATCH", "HEAD", "BREW"),
            "/blocklist": ("DELETE", "PUT"),
            "/blocklist/ads.example.com": ("GET", "POST"),
            "/records": ("DELETE", "PATCH"),
            "/records/nas.home.lan/A": ("GET", "POST"),
            "/log": ("POST",),
        }
        for path, methods in cases.items():
            for method in methods:
                response, _ = self.request(method, path)
                self.assertEqual(response.status, 405, f"{method} {path}")
                self.assertTrue(response.getheader("Allow"), f"{method} {path}")

    def test_unknown_query_parameters_ignored(self):
        self.assertEqual(self.status("GET", "/stats?x=1"), 200)


if __name__ == "__main__":
    unittest.main()
