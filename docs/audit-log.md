# Code audit log

Owner: Daniel. Everyone adds entries when a review or test catches something in AI output.

| ID | Module | Found by | Category | Issue | Resolution | Prompt / commit |
|---|---|---|---|---|---|---|
| VA-001 | api | review | security | The admin API accepts state-changing POST/DELETE requests with no `Content-Type`, `Origin` or `Host` check. Any web page the operator opens can add records or unblock domains with a `text/plain` POST that needs no preflight (CSRF), and with DNS rebinding it can also read `/log` and `/records`. Reproduced: a `text/plain` POST with `Origin: http://evil.example` returned 201, after which `bank.com` resolved to `6.6.6.6` and `other.com` got NXDOMAIN, because `com.` had become a local suffix. Also noted in V-013. | open | V-012 / `2d92e5d` |
| VA-002 | listener | review | security | TCP replies have no size limit. A reply over 65535 bytes makes `struct.pack("!H", len(reply))` raise `struct.error`, which the handler does not catch (it only catches `OSError`), so the client gets no answer. Reproduced: with 4200 A records for `big.lan`, `dig +tcp` got "end of file". | open | V-009 / `f8b7211` |
| VA-003 | zone | review | logic | `check_name` only checks label lengths, so it accepts names the wire encoder rejects (non-ASCII, a trailing backslash). The API returns 201 for a record that fails on every later query. Reproduced: a CNAME `host.lan` → `café.lan` returned 201, and every query for `host.lan` then gets SERVFAIL. | open | V-002 / `6aeec9e` |
| VA-004 | listener | review | compliance | `_from_upstream` does not copy RD (or CD) from the current query, so a cached reply carries the flags of the first client that caused it to be cached. A later client that sends RD=0 gets RD=1 back, which breaks RFC 1035 4.1.1 (RD is copied into the response). Found by reading `dnsd/resolver.py:136`; not run. | open | V-009 / `f8b7211` |
| VA-005 | forwarder | review | logic | `parse_address` splits on the last `:`, so a bare IPv6 address is parsed wrongly: `2606:4700::1111` → host `2606:4700:`, port 1111, and `::1` → host `:`, port 1. Only the bracketed form `[::1]:53` works. This affects `--listen`, `--admin` and `--upstream`. | open | V-004 / `519b736` |
| VA-006 | listener | review | logic | Some startup errors are not handled cleanly. `--upstream 1.1.1.1:dns` ends in a raw `ValueError` traceback, because only `OSError`/`ZoneError`/`BlocklistError` are caught around `Forwarder()`. A missing `dnsd/ui.html` is reported as "cannot listen on …". | open | V-010 / `851d069`, V-012 / `2d92e5d` |
| VA-007 | listener | review | security | `ThreadingUDPServer` starts one thread per datagram, and each forwarded query can block for up to 2 s. A burst of queries while the upstream is slow creates threads without limit until memory or thread limits run out. Found by reading the code; not run. | open | V-009 / `f8b7211` |
| VA-008 | zone | review | performance | `_is_local` rebuilds the set of record suffixes on every lookup, holding the zone lock. That is O(zone size) on the hot path of every forwarded, blocked and cached query. Found by reading the code; not run. | open | V-002 / `6aeec9e` |
| VA-009 | cache | review | performance | Once the cache is full, every `put()` scans all entries for expired ones before evicting one LRU entry, so each insert is O(max size) under the cache lock. Found by reading the code; not run. | open | V-003 / `a7e7935` |
| VA-010 | forwarder | review | maintainability | `forwarder.py` has its own `HEADER_SIZE`, its own name walker (`question_end`, which rejects compression pointers) and a read-exactly helper. These duplicate `parser.HEADER_SIZE`, `parser.read_labels` (which follows pointers) and `listener._read_exactly`, so there are two wire-name parsers with different rules. | open | V-004 / `519b736` |
| VA-011 | listener | linter: ruff | maintainability | LOG015: `logging.info` is called on the root logger in `__main__.py:54-55` instead of a module logger. | open | V-009 / `f8b7211` |
| VA-012 | listener | linter: ruff | maintainability | I001: the import block in `resolver.py:1-8` is not sorted. | open | V-009 / `f8b7211` |
| VA-013 | listener | linter: bandit | security | B104 "possible binding to all interfaces" at `resolver.py:13`. Not a flaw: `0.0.0.0` and `::` are the blocked answers that contract.md requires (lines 81-82), and nothing binds to them. | not a flaw | V-009 / `f8b7211` |

Category guide:
- **security**: predictable transaction IDs, fixed source port, accepting responses with the wrong ID, crash on malformed input
- **logic**: NXDOMAIN vs NODATA mixed up, TTL not decremented, CNAME not followed, wrong AA/RA flags
- **compliance**: anything that breaks an RFC 1035 rule or `contract.md`
- **performance**: work that grows with zone, cache or load size on the query path
- **maintainability**: duplicated code, linter style findings

Verification of `vibe-final` on 2026-10-31: see `docs/verification/README.md`.
