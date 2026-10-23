import json
import logging
import re
import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from dnsd.blocklist import BlocklistError
from dnsd.forwarder import parse_address
from dnsd.querylog import DEFAULT_LIMIT
from dnsd.zone import ZoneError

log = logging.getLogger(__name__)

MAX_BODY = 64 * 1024
DIGITS = re.compile(r"[0-9]+")
UI_PAGE = Path(__file__).with_name("ui.html")

# Path pattern (None matches any one non-empty segment) -> method -> handler.
ROUTES = (
    (("stats",), {"GET": "get_stats"}),
    (("blocklist",), {"GET": "get_blocklist", "POST": "post_blocklist"}),
    (("blocklist", None), {"DELETE": "delete_blocklist"}),
    (("records",), {"GET": "get_records", "POST": "post_records"}),
    (("records", None, None), {"DELETE": "delete_record"}),
    (("log",), {"GET": "get_log"}),
    (("ui",), {"GET": "get_ui"}),
)


class ApiError(Exception):
    def __init__(self, status, message):
        super().__init__(message)
        self.status = status


def route(path):
    """Return (methods, path arguments) for a path, or (None, None)."""
    if not path.startswith("/"):
        return None, None
    parts = [unquote(part) for part in path[1:].split("/")]
    for pattern, methods in ROUTES:
        if len(pattern) == len(parts) and all(
            part if p is None else part == p for p, part in zip(pattern, parts)
        ):
            return methods, [part for p, part in zip(pattern, parts) if p is None]
    return None, None


def field(body, name, kind):
    value = body.get(name)
    # type() rather than isinstance(), so true is not taken as a TTL of 1.
    if type(value) is not kind:
        raise ApiError(400, f"{name!r} must be a {kind.__name__}")
    return value


class _Handler(BaseHTTPRequestHandler):
    timeout = 10

    def __getattr__(self, name):
        # http.server answers 501 to a method without a do_* handler; route
        # every method instead, so a known path gives 405 and an unknown one 404.
        if name.startswith("do_"):
            return self._dispatch
        raise AttributeError(name)

    def _dispatch(self):
        url = urlsplit(self.path)
        methods, args = route(url.path)
        try:
            if methods is None:
                raise ApiError(404, "unknown path")
            if self.command not in methods:
                self._send(405, {"error": "method not allowed"}, {"Allow": ", ".join(methods)})
                return
            status, body = getattr(self, methods[self.command])(*args, query=url.query)
        except ApiError as e:
            status, body = e.status, {"error": str(e)}
        except Exception:
            log.exception("admin request %s %s failed", self.command, self.path)
            status, body = 500, {"error": "internal error"}
        self._send(status, body)

    def _send(self, status, body=None, headers=None):
        # bytes is the /ui page; anything else but None is sent as JSON.
        if body is None:
            data, content_type = b"", None
        elif isinstance(body, bytes):
            data, content_type = body, "text/html; charset=utf-8"
        else:
            data, content_type = json.dumps(body).encode(), "application/json"
        self.send_response(status)
        if content_type:
            self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _body(self):
        length = self.headers.get("Content-Length", "").strip()
        if not DIGITS.fullmatch(length) or int(length) > MAX_BODY:
            raise ApiError(400, "missing or invalid Content-Length")
        try:
            body = json.loads(self.rfile.read(int(length)))
        except (ValueError, RecursionError):
            raise ApiError(400, "body is not valid JSON") from None
        if not isinstance(body, dict):
            raise ApiError(400, "body must be a JSON object")
        return body

    def log_message(self, format, *args):
        log.debug("%s %s", self.address_string(), format % args)

    @property
    def api(self):
        return self.server.api

    def get_stats(self, query):
        return 200, {**self.api.stats.snapshot(), **self.api.cache.stats()}

    def get_blocklist(self, query):
        return 200, self.api.blocklist.domains()

    def post_blocklist(self, query):
        domain = field(self._body(), "domain", str)
        try:
            return 201, {"domain": self.api.blocklist.add(domain)}
        except BlocklistError as e:
            raise ApiError(400, str(e)) from None

    def delete_blocklist(self, domain, query):
        if not self.api.blocklist.delete(domain):
            raise ApiError(404, "not listed")
        return 204, None

    def get_records(self, query):
        return 200, self.api.zone.records()

    def post_records(self, query):
        body = self._body()
        name = field(body, "name", str)
        rtype = field(body, "type", str)
        ttl = field(body, "ttl", int)
        value = field(body, "value", str)
        try:
            return 201, self.api.zone.add(name, rtype, ttl, value)
        except ZoneError as e:
            raise ApiError(400, str(e)) from None

    def delete_record(self, name, rtype, query):
        if not self.api.zone.delete(name, rtype):
            raise ApiError(404, "no such records")
        return 204, None

    def get_log(self, query):
        values = parse_qs(query, keep_blank_values=True).get("limit", [str(DEFAULT_LIMIT)])
        if len(values) != 1 or not DIGITS.fullmatch(values[0]):
            raise ApiError(400, "limit must be a non-negative integer")
        return 200, self.api.querylog.entries(int(values[0]))

    def get_ui(self, query):
        return 200, self.api.ui_page


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, family, address, api):
        self.address_family = family
        self.api = api
        super().__init__(address, _Handler)


class AdminServer:
    """Serves the admin API, JSON over HTTP, from the live zone, blocklist and counters."""

    def __init__(self, address, zone, blocklist, cache, stats, querylog):
        self.zone = zone
        self.blocklist = blocklist
        self.cache = cache
        self.stats = stats
        self.querylog = querylog
        self.ui_page = UI_PAGE.read_bytes()
        host, port = parse_address(address, default_port=80)
        family, _, _, _, sockaddr = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)[0]
        self.server = _Server(family, sockaddr, self)
        self._thread = None

    @property
    def address(self):
        return self.server.server_address

    def start(self):
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()

    def close(self):
        if self._thread:
            self.server.shutdown()
            self._thread = None
        self.server.server_close()
