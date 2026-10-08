# External behaviour contract

This is the only shared definition between the two builds. It fixes what the
test suite can observe from outside: flags, file formats, ports, the admin API
and the blocking response. It says nothing about how anything is implemented.

This file is duplicated in Vibe_Name_Service and Das_Name_Service. It is frozen; any change goes into both repos the same day.

## Scope

Tier 1: local zone (A, AAAA, CNAME) answered authoritatively, everything else forwarded.
Tier 2: TTL-respecting cache, blocklist, query log, admin API.
Not in scope: iterative resolution from the root, DNSSEC, DoT/DoH, dashboard UI.

Both builds write their own wire-format parser. DNS libraries (miekg/dns, dnspython)
are allowed in tests only.

## Command line

```
dnsd -listen 127.0.0.1:5353 -admin 127.0.0.1:8080 \
     -zone zone.txt -blocklist blocklist.txt -upstream 1.1.1.1:53
```

The server listens on UDP and TCP on the same `-listen` address.

## Zone file

A subset of the RFC 1035 master file format, one record per line:

```
nas.home.lan.     300 IN A     192.168.1.10
nas.home.lan.     300 IN AAAA  fd00::10
files.home.lan.   300 IN CNAME nas.home.lan.
```

Lines starting with `;` are comments. Names are absolute (trailing dot).

## Blocklist file

One domain per line, `#` for comments. A listed domain also blocks its subdomains.

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

## Open decisions (settle before the vibe phase starts)

- [ ] Go version and whether both builds share one go.mod setup
- [ ] Which AI agent/IDE each person uses (affects agent rules files and Spec Kit init)
- [ ] Cache size limit, if any
