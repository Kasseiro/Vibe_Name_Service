import logging
import struct
import time
from dataclasses import dataclass, replace

from dnsd import parser
from dnsd import zone as zones
from dnsd.parser import A, AAAA, NOERROR, NXDOMAIN, OPT, SERVFAIL, SOA, ResourceRecord

log = logging.getLogger(__name__)

BLOCK_TTL = 60
BLOCK_VALUES = {A: "0.0.0.0", AAAA: "::"}

LOCAL = "local"
BLOCKED = "blocked"
CACHED = "cached"
FORWARDED = "forwarded"
ERROR = "error"


@dataclass(frozen=True)
class QueryEvent:
    """One query counted in /stats, in the shape of a /log entry."""

    time: float
    client: str
    name: str
    type: str
    result: str


def cache_ttl(message):
    """How long an upstream reply may be cached; 0 means not at all."""
    if message.rcode == NOERROR and message.answers:
        return min(rr.ttl for rr in message.answers)
    if message.rcode in (NOERROR, NXDOMAIN):
        ttls = [
            min(rr.ttl, rr.soa_minimum)
            for rr in message.authority
            if rr.rtype == SOA and rr.soa_minimum is not None
        ]
        if ttls:
            return min(ttls)
    return 0


class Resolver:
    """Turns one query packet into one response packet.

    blocklist is any object with blocks(name) -> bool, or None while there is
    no blocklist module. Each observer is called with a QueryEvent for every
    query counted in /stats; the stats counters and the query log hook in
    there. cache_hits and cache_misses come from cache.stats().
    """

    def __init__(self, zone, cache, forwarder, blocklist=None, observers=()):
        self.zone = zone
        self.cache = cache
        self.forwarder = forwarder
        self.blocklist = blocklist
        self.observers = list(observers)

    def handle(self, data, client, max_size=None):
        """Return the response bytes, or None when the input gets no reply."""
        received = time.time()
        try:
            query = parser.parse_query(data)
        except parser.DropQuery:
            return None
        except parser.QueryError as e:
            return parser.error_response(e.query_id, e.rcode)
        try:
            response, result = self._answer(query)
            wire = response.to_wire(max_size)
        except Exception:
            log.exception("failed to answer %s", query.question)
            result = ERROR
            wire = query.reply(SERVFAIL).to_wire(max_size)
        question = query.question
        self._notify(QueryEvent(received, client, question.name, question.type_name, result))
        return wire

    def _answer(self, query):
        question = query.question
        status, records = self.zone.lookup(question.name, question.type_name)
        if status != zones.NOT_LOCAL:
            response = query.reply(NXDOMAIN if status == zones.NXDOMAIN else NOERROR, aa=True)
            response.answers = [
                ResourceRecord.from_text(r["name"], r["type"], r["ttl"], r["value"])
                for r in records
            ]
            return response, LOCAL

        if self.blocklist is not None and self.blocklist.blocks(question.name):
            return self._blocked(query), BLOCKED

        cached = self.cache.get(question.name, question.type_name)
        if cached is not None:
            upstream, age = cached
            return self._from_upstream(query, upstream.with_ttls_reduced(age)), CACHED

        upstream = self._forward(query)
        if upstream is None:
            return query.reply(SERVFAIL), ERROR
        ttl = cache_ttl(upstream)
        if ttl > 0:
            self.cache.put(question.name, question.type_name, upstream, ttl)
        result = ERROR if upstream.rcode == SERVFAIL else FORWARDED
        return self._from_upstream(query, upstream), result

    def _blocked(self, query):
        question = query.question
        value = BLOCK_VALUES.get(question.qtype)
        if value is None:
            return query.reply(NXDOMAIN)
        response = query.reply(NOERROR)
        response.answers.append(
            ResourceRecord.from_text(question.name, question.qtype, BLOCK_TTL, value)
        )
        return response

    def _forward(self, query):
        # Re-encoding sends only the header and the question, with no
        # compression pointer for the forwarder to trip over.
        reply = self.forwarder.forward(query.to_wire())
        if reply is None:
            return None
        try:
            return parser.parse_message(reply)
        except (ValueError, struct.error):
            log.warning("unparsable upstream reply for %s", query.question)
            return None

    @staticmethod
    def _from_upstream(query, upstream):
        return replace(
            upstream,
            id=query.id,
            qr=True,
            aa=False,
            tc=False,
            ra=True,
            questions=list(query.questions),
            additional=[rr for rr in upstream.additional if rr.rtype != OPT],
        )

    def _notify(self, event):
        for observer in self.observers:
            try:
                observer(event)
            except Exception:
                log.exception("query observer %r failed", observer)
