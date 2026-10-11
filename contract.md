# External behaviour contract

This is the only shared definition between the two builds. It fixes what the
test suite can observe from outside: flags, file formats, ports, the admin API
and the blocking response. It says nothing about how anything is implemented.

This file is duplicated in Vibe_Name_Service and Das_Name_Service. It is frozen; any change goes into both repos the same day.

Where this file says something is **unspecified**, a build may do anything that
does not crash, and the test suite does not check it.

## Scope

Tier 1: local zone (A, AAAA, CNAME) answered authoritatively, everything else forwarded.
Tier 2: TTL-respecting cache, blocklist, query log, admin API.
Not in scope: iterative resolution from the root, DNSSEC, EDNS, DoT/DoH, dashboard UI.

Both builds write their own wire-format parser. DNS libraries (dnspython, dnslib)
are allowed in tests only.

## Command line

```
python -m dnsd --listen 127.0.0.1:5353 --admin 127.0.0.1:8080 \
    --zone zone.txt --blocklist blocklist.txt --upstream 1.1.1.1:53
```

The server listens on UDP and TCP on the same `--listen` address.

The server runs on Python 3.11 from the repo root using the standard library
only; nothing is installed for it.

The zone and blocklist files are read once at startup and are never written.
Changes made through the admin API live in memory and are lost on restart.

## Zone file

A subset of the RFC 1035 master file format, one record per line:

```
nas.home.lan.     300 IN A     192.168.1.10
nas.home.lan.     300 IN AAAA  fd00::10
files.home.lan.   300 IN CNAME nas.home.lan.
```

Lines starting with `;` are comments. Names are absolute (trailing dot).

- Fields are separated by any amount of whitespace. Blank lines are ignored.
- Only the types A, AAAA and CNAME occur.
- Several records may share a name and type. All of them are returned, in
  unspecified order.
- Names compare case-insensitively (RFC 4343).
- **Local zone suffix**: the file has no origin line, so the suffixes are derived
  from the records. Every record name with its first label removed is a local
  zone suffix (`nas.home.lan.` makes `home.lan.` a suffix). Suffixes follow the
  current record set, including changes made through the admin API. A query
  for the suffix name itself, when it has no records, is unspecified.
- **CNAME**: a query for a name that has a CNAME record, with a type other than
  CNAME, is answered with the CNAME record followed by the records of the
  requested type at the target, if the target is in the local zone. If the
  target is not in the local zone, the answer is the CNAME record alone.

## Blocklist file

One domain per line, `#` for comments. A listed domain also blocks its subdomains.

- A line whose first non-blank character is `#` is a comment. Blank lines are
  ignored. A `#` later in a line is unspecified.
- Entries may be written with or without a trailing dot and in any case; they
  match case-insensitively (RFC 4343).
- Matching is by whole labels: `ads.example.com` blocks `ads.example.com` and
  `x.ads.example.com`, but neither `example.com` nor `xads.example.com`.

## Responses

| Case | RCODE | Answer | AA |
|---|---|---|---|
| Name in local zone, type exists | NOERROR | records | 1 |
| Name in local zone, type missing (NODATA) | NOERROR | empty | 1 |
| Name under a local zone suffix, not defined | NXDOMAIN | empty | 1 |
| Blocked domain, type A | NOERROR | 0.0.0.0, TTL 60 | 0 |
| Blocked domain, type AAAA | NOERROR | ::, TTL 60 | 0 |
| Blocked domain, other types | NXDOMAIN | empty | 0 |
| Anything else | as upstream | as upstream | 0 |

RA is set in every response. Responses over 512 bytes on UDP are truncated
with TC=1. Malformed queries get FORMERR when the header can be parsed, and are
dropped silently otherwise. The server must never crash on input.

The rows are tried from top to bottom and the first match applies, so a name
that is both in the local zone and blocked gets the local zone answer.
"Other types" means every type except A and AAAA, including ANY.

In every response the ID and the question section are copied from the query
unchanged, including the case of the name. QR is 1. In responses built by the
server itself (local zone, blocked, errors) the authority and additional
sections are unspecified.

### Forwarded queries

RCODE and the answer, authority and additional sections are those of the
upstream reply. An upstream reply counts only if its ID matches the query the
server sent; any other reply is ignored. If no matching reply arrives within
2 seconds the server answers SERVFAIL. What the server does when the upstream
reply has TC=1 is unspecified.

### Malformed and unusual queries

| Input | Reaction |
|---|---|
| Fewer than 12 bytes | no reply |
| QR=1 (the packet is a response) | no reply |
| Opcode other than 0 (QUERY) | NOTIMP |
| QDCOUNT other than 1 | FORMERR |
| Question cannot be parsed: packet ends early, label over 63 bytes, name over 255 bytes, compression pointer that loops or points outside the packet | FORMERR |

A FORMERR or NOTIMP reply is a bare 12-byte header: the query's ID, QR=1, RA=1,
the RCODE, and all four counts zero.

Records after the question in a query are ignored, which covers EDNS: an OPT
record has no effect, responses never carry one, and the 512-byte UDP limit
always applies. Bytes after the last counted section and classes other than IN
are unspecified.

### Truncation

A truncated UDP response is at most 512 bytes, has TC=1, keeps the question and
contains only whole records. Whether it carries some of the answer or none is
unspecified. TC is never set over TCP.

### TCP

Each message is preceded by a two-byte length in network byte order, in both
directions (RFC 1035 4.2.2). The same rules apply as over UDP; where UDP gives
no reply, the server closes the connection. The server answers the first query
on a connection. Whether it answers further queries on the same connection, and
how long it keeps an idle connection open, are unspecified.

## Admin API (JSON over HTTP)

| Method | Path | Body / result |
|---|---|---|
| GET | /stats | `{"queries": n, "blocked": n, "cache_hits": n, "cache_misses": n}` |
| GET | /blocklist | `["ads.example.com", ...]` |
| POST | /blocklist | `{"domain": "ads.example.com"}` → 201 |
| DELETE | /blocklist/{domain} | 204, or 404 if not listed |
| GET | /records | list of `{"name", "type", "ttl", "value"}` |
| POST | /records | one record object → 201 |
| DELETE | /records/{name}/{type} | 204, or 404 |
| GET | /log?limit=n | most recent queries: `{"time", "client", "name", "type", "result"}` |

Changes through the API take effect immediately, with no restart.

### Status codes

- A successful GET returns 200 with `Content-Type: application/json`.
- A request body that is not valid JSON, or that lacks a field or has a field
  of the wrong kind, returns 400.
- An unknown path returns 404. A known path with a method not in the table
  returns 405.
- The bodies of 201, 204 and error responses are unspecified.

### Names

The API accepts domain and record names with or without a trailing dot and in
any case, in bodies and in URLs. Names in results may be in either form;
clients compare them ignoring case and the trailing dot.

### /blocklist

- GET lists every blocked domain: those loaded from the file and those added
  through the API. Both kinds can be deleted.
- POST of a domain that is already listed returns 201 and leaves it listed once.
- DELETE matches listed entries only. A subdomain of a listed domain is blocked
  but not listed, so deleting it returns 404.

### /records

- GET lists every record: those loaded from the zone file and those added
  through the API. Both kinds can be deleted.
- `name` is the record name. `type` is `"A"`, `"AAAA"` or `"CNAME"`; any other
  type in a POST returns 400. `ttl` is a non-negative integer number of
  seconds. `value` is a string in zone file form: an IPv4 address, an IPv6
  address, or the CNAME target name.
- POST of a record whose name, type and value already exist returns 201,
  replaces its TTL and leaves it stored once.
- DELETE removes every record with that name and type. `{type}` is matched
  case-insensitively.

### /stats

All counters start at 0 when the server starts.

- `queries`: queries the server answered or forwarded, over UDP and TCP. Input
  that got no reply, FORMERR or NOTIMP is not counted.
- `blocked`: queries that got a blocking response.
- `cache_hits`: queries answered from the cache.
- `cache_misses`: queries sent to the upstream.

Queries answered from the local zone or the blocklist change neither cache counter.

### /log

- One entry per query counted in `queries`, newest first.
- `limit` is a non-negative integer and defaults to 100. Anything else returns
  400. If the log holds fewer entries than `limit`, all of them are returned.
- The server keeps at least the 1000 most recent entries.
- `time`: number, seconds since the Unix epoch, when the query arrived.
- `client`: string, the client's IP address without the port.
- `name`: string, the queried name.
- `type`: string, the type mnemonic (`"A"`, `"MX"`, ...), or `"TYPEn"` for a
  type the server has no name for.
- `result`: one of `"local"` (answered from the local zone), `"blocked"`,
  `"cached"` (answered from the cache), `"forwarded"` (answered by the
  upstream) and `"error"` (SERVFAIL).

## Open decisions (settle before the vibe phase starts)

- [x] Python version: 3.11, standard library only
- [ ] Whether both builds share one pyproject.toml setup
- [ ] Which AI agent/IDE each person uses (affects agent rules files and Spec Kit init)
- [ ] Cache size limit, if any
