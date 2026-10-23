# Prompt log

Owner: Daniel. Everyone adds entries.

Add an entry for every prompt whose output got committed, and for every prompt
that failed in an interesting way. A two-line entry written now beats a
detailed one written in week two from memory. Mark entries worth using in the
report with ★ so sections 3.2 and 3.3 can be pulled straight from here.

IDs run V-001, V-002, ... Put the ID in
the commit trailer (`Prompt: V-014`).

When a prompt is a retry of an earlier one, link it with `Refines:`. A chain
like V-007 → V-009 → V-012 is a ready-made row for the iteration log table (3.3).

---

## Template

### V-000 ★
- **Module:** cache
- **Who / tool / model:** Daniel / Cursor / Claude Sonnet
- **Date:**
- **Refines:** (earlier prompt ID, if any)
- **Prompt:**
  ```
  exact text
  ```
- **Why this prompt:** what I was trying to get and why I phrased it this way
- **Expected:**
- **Got:** what the AI actually produced
- **Verdict:** worked | partly | failed
- **Failure mode:** (wrong logic, ignored spec, hallucinated API, missed edge case, ...)
- **Fixed by:** next prompt ID, manual edit, or spec change

---

## Entries

### V-001
- **Module:** listener
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-08
- **Refines:**
- **Prompt:**
  ```
  Create a Python package called dnsd with a __main__.py so it runs with python -m dnsd. Parse these flags with argparse: --listen (default 127.0.0.1:5353), --admin (default 127.0.0.1:8080), --zone, --blocklist, --upstream (default 1.1.1.1:53). For now just print the parsed config and exit. Standard library only.
  ```
- **Why this prompt:** get a runnable skeleton that accepts the command line from the README before any module exists
- **Expected:** `python -m dnsd` prints the five config values and exits
- **Got:** `dnsd/__init__.py` (empty) and `dnsd/__main__.py` with `parse_args()` and `main()`; prints one `key: value` line per flag. `--zone` and `--blocklist` print `None` when omitted; addresses are kept as unvalidated `host:port` strings.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-002
- **Module:** zone
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-08
- **Refines:**
- **Prompt:**
  ```
  build the local zone module in dnsd/zone.py
  ```
- **Why this prompt:** looked for parts of the project that I could build without the other team members 
- **Expected:** zone.py file that works according to the contract
- **Got:** `dnsd/zone.py` with a thread-safe `Zone` class: `from_file()`/`load()` for the zone file, `lookup(name, qtype)` returning `(ANSWER | NODATA | NXDOMAIN | NOT_LOCAL, records)`, and `add()`/`delete()`/`records()` using the `{"name", "type", "ttl", "value"}` shape from the admin API. Follows CNAMEs inside the zone with loop protection, matches names case-insensitively, validates names, TTLs and addresses. Decided on its own, since the contract does not say: the "local zone suffix" is the parent of each record name (`nas.home.lan.` makes `home.lan.` local); a bad zone file line raises `ZoneError` with the line number; CNAME cannot share a name with other types. Not wired into `main()`. The prompt was typed in the same session as an earlier plan-mode question about what could be built first, so the model had more context than this one line.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-003
- **Module:** cache
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-08
- **Refines:**
- **Prompt:**
  ```
  build the cache module in dnsd/cache.py and insert with TTL 300 and a fake clock, advance it, confirm the remaining TTL
    drops and the entry expires; check the counters, to test that it works
  ```
- **Why this prompt:** cache is the second module I can build without Johnny's parser or Adam's API. I put the test steps in the prompt so the result would be checked right away instead of trusting the code on sight.
- **Expected:** `cache.py` that stores answers with a TTL, counts hits and misses for `/stats`, and a run showing the TTL counting down from 300 and the entry expiring.
- **Got:** `dnsd/cache.py` with a thread-safe `Cache(max_size=None, clock=time.monotonic)`: `put(name, qtype, value, ttl)`, `get(name, qtype)` returning `(value, remaining_ttl)` or `None`, `hits`/`misses` counters and `stats()` in the `/stats` key names. Keys are case-insensitive on name and type; the value is opaque. Ran the requested check in a throwaway script (not committed): TTL 300 read back as 300, 200 after 100 s, 1 after 299 s, gone at 300 s, counters 4 hits / 3 misses. Decided on its own: size limit is optional and evicts expired entries first, then least recently used; TTL 0 is not stored; remaining TTL is rounded up so a live entry never reports 0; imports `canonical` from `dnsd/zone.py`. Not wired into `main()`. Same session as V-002, so the model had the earlier planning context. Observations: (1) the prompt asked to test the cache, and the model ran the check as a throwaway script but did not save it as a test file, so the repo has no record of it beyond this entry; (2) the prompt said nothing about a size limit, rounding or TTL 0, and the model decided all three without asking.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-004 ★
- **Module:** forwarder
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-08
- **Refines:**
- **Prompt:**
  ```
  Create the forwarder moudule
  ```
- **Why this prompt:** the forwarder is the last of my three modules that can be built before Johnny's parser exists. I kept the prompt to one line on purpose, to see what the model does with no requirements at all.
- **Expected:** `forwarder.py` that sends a query to the `--upstream` address and returns the answer.
- **Got:** `dnsd/forwarder.py` with `Forwarder(upstream, timeout=2.0, attempts=2)` and `forward(query_bytes)` returning the reply bytes or `None`. Works on raw bytes, no parser needed. Each attempt uses a new random transaction ID (`secrets`) and a new UDP socket, so the source port changes too; replies are accepted only from the upstream address with the matching ID, the QR bit set and the same question. A truncated UDP reply is retried over TCP; the client's original ID is restored before returning. Network errors and timeouts return `None` instead of raising. Tested with a throwaway script (not committed) against a fake local upstream and the real 1.1.1.1. Decided on its own: timeout 2 s and 2 attempts; the question-match check; returning the truncated reply when the TCP retry fails; `None` on total failure, leaving the SERVFAIL to the caller. Not wired into `main()`. Same session as V-002 and V-003, so the model had the earlier planning context. Observations: (1) the prompt named no requirements, yet the model added random transaction IDs, a fresh source port per query, and rejection of replies with the wrong ID or question. These are the "security" items in `docs/audit-log.md`; the earlier plan-mode conversation in the same session had listed them, so the one-line prompt was not the model's only input; (2) the timeout (2 s), the number of attempts (2) and returning `None` on failure were all chosen without asking; (3) as with V-003, the checks ran as a throwaway script and left no test file in the repo.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-005
- **Module:** zone
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-12
- **Refines:** V-002
- **Prompt:**
  ```
  The contract has been changed from when my modules where made, do they need to be updated to fit the new definition
  ```
- **Why this prompt:** the contract grew from 78 to 243 lines on 2026-10-11, after zone, cache and forwarder were built. Asked as a question instead of an instruction, to find out whether anything had to change at all.
- **Expected:** a list of where each module differs from the new contract, and fixes for those places.
- **Got:** Asked in plan mode; the model compared the three modules with the contract diff and proposed a plan, which I approved. One prompt produced V-005, V-006 and V-007. Four changes in `dnsd/zone.py`: (1) an undefined name under a local suffix is now always NXDOMAIN, where it used to be NODATA if it had records below it; (2) a second CNAME on a name is stored next to the first instead of replacing it; (3) CNAME and A/AAAA may share a name, and a query for another type then gets the CNAME followed by the target's records; (4) `add()` accepts only a real integer as TTL, so `"300"`, `3.7` and `true` are rejected, and `load()` converts the zone file text itself. Checked with a throwaway script (not committed). Decided on its own: a single-label record such as `localhost.` still makes itself the suffix and not the root, against the wording of the contract, because the literal reading would turn every forwarded name into NXDOMAIN. Observation: three of the four deviations were things V-002 had "decided on its own" and that the contract later settled the other way.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-006
- **Module:** cache
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-12
- **Refines:** V-003
- **Prompt:**
  ```
  The contract has been changed from when my modules where made, do they need to be updated to fit the new definition
  ```
- **Why this prompt:** same prompt as V-005.
- **Expected:** same as V-005.
- **Got:** No contract violation found in `dnsd/cache.py`. One interface change: `get()` now returns `(value, age)` with the whole seconds the entry has been stored, where it used to return the remaining lifetime. The contract wants every TTL in a cached answer reduced by the time in the cache, and the remaining lifetime is only right for the record with the lowest TTL. Checked with a fake clock in a throwaway script (not committed): age 0, 100 and 299, gone at 300 s, 3 hits / 1 miss. The model also pointed out that nothing yet decides what may be cached (SOA rule for negative answers, never SERVFAIL); that belongs to whoever calls `put()` and needs the wire parser.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-007
- **Module:** forwarder
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-12
- **Refines:** V-004
- **Prompt:**
  ```
  The contract has been changed from when my modules where made, do they need to be updated to fit the new definition
  ```
- **Why this prompt:** same prompt as V-005.
- **Expected:** same as V-005.
- **Got:** Three changes in `dnsd/forwarder.py`: (1) one 2-second deadline covers the UDP query and the TCP retry, and the `attempts` parameter is gone, so a silent upstream gives `None` after 2 s instead of 4 s or more; (2) when the TCP retry after a truncated reply fails, `forward()` returns `None` instead of the truncated UDP reply; (3) only the header and question are sent upstream, with the other three counts set to 0, so a client's EDNS record never reaches the upstream and no OPT record comes back. Checked with a throwaway script (not committed) against a fake upstream (silent, TC=1 with and without a TCP listener, query with an OPT record) and the real 1.1.1.1. Decided on its own: a query whose question holds a compression pointer is sent unchanged, since the forwarder cannot find where the question ends. Observation: all three defaults that V-004 chose without asking (2 attempts, falling back to the truncated reply, forwarding the query untouched) ended up against the contract once it was written down.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-008
- **Module:** parser
- **Who / tool / model:** Johnny / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-17
- **Refines:**
- **Prompt:**
```
Read contract.md and the existing modules in dnsd/. Build the DNS wire-format parser in dnsd/parser.py, with tests in tests/. Don’t commit.
```
- **Why this prompt:** the parser is the base for the listener and the glue. Kept the prompt short, like Daniel's module prompts, to see how much the model takes from contract.md alone.
- **Expected:** a parser that decodes queries, builds responses and handles the malformed-query table, with tests.
- **Got:** `dnsd/parser.py` (470 lines) and `tests/test_parser.py` (45 tests, all pass), plus an empty `tests/__init__.py` so unittest finds them. `parse_query()` follows the contract's malformed table in order: `DropQuery` for under 12 bytes or QR=1, `QueryError(NOTIMP)` for opcode ≠ 0, `QueryError(FORMERR)` for QDCOUNT ≠ 1 or an unparsable question (early end, label > 63, name > 255, looping or out-of-range pointer); EDNS and trailing bytes are ignored. `error_response()` builds the bare 12-byte header. `parse_message()` parses full upstream replies and expands names in RDATA so records can move between messages. `Message.to_wire(max_size=512)` compresses names only on exact byte match, so the question keeps its case, and truncates at whole records with TC=1. Helpers: `Message.reply()`, `with_ttls_reduced(age)` (matches `cache.get()`), `ResourceRecord.from_text()`, `soa_minimum`, `type_name()` ("TYPEn" for unknown). Tests include every malformed-table row, exact limits, a compressed upstream reply, round trip, truncation and 40,000 random/corrupted packets. The model also caught and fixed a broken assertion in its own truncation test before running it. Decided on its own: (1) FORMERR/NOTIMP set only the contract's fields, not opcode or RD; (2) names stored as text with \. and \DDD escapes; (3) TTLs ≥ 2³¹ kept raw, not treated as 0 (RFC 2181); (4) `to_wire` doesn't drop OPT records, so the caller must keep them out of responses. ruff wasn't installed, so it couldn't lint. Observation: the short prompt was enough; it found the malformed table and truncation rules in contract.md without being told.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-009
- **Module:** listener
- **Who / tool / model:** Johnny / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-19
- **Refines:**
- **Prompt:**
```
Read contract.md and dnsd/. Build the UDP/TCP listener and wire zone, cache, forwarder and parser together so python -m dnsd answers queries. The blocklist, stats and log modules aren’t written yet; leave hooks for them. Don’t commit.
```
- **Why this prompt:** the listener and the glue between modules were the last things blocking an end-to-end server. Short prompt, same style as V-008, to see how much the model takes from contract.md and the existing modules alone.
- **Expected:** python -m dnsd answering queries over UDP and TCP using the existing modules, with hooks for Adam's blocklist, stats and log.
- **Got:** `dnsd/resolver.py`: `Resolver.handle(data, client, max_size)` applies the contract's response table in order (zone, blocklist, cache, upstream) and decides what is cached (positive answers for the lowest TTL, NXDOMAIN/NODATA only with an SOA for min(TTL, MINIMUM), never SERVFAIL). `dnsd/listener.py`: threaded UDP and TCP servers on the same address, UDP replies capped at 512 bytes. `__main__.py` now builds zone, cache, forwarder, resolver and listener, with one-line errors for a bad zone file or an unbindable port. README layout updated with parser, resolver and listener. Hooks for Adam: a blocklist object with `blocks(name) -> bool` (None = nothing blocked; the blocked A/AAAA/NXDOMAIN answers are already built in the resolver); an `observers` list of callables that each get a `QueryEvent(time, client, name, type, result)` for every query counted in /stats; `--admin` parsed but nothing listens on it yet (`TODO(api)` in `__main__.py`). The model tested by hand with dig and a throwaway raw-socket script against a test zone and 1.1.1.1. Decided on its own: (1) a SERVFAIL from the upstream is logged as "error", not "forwarded"; (2) an internal exception gives SERVFAIL instead of a dropped query; (3) the query is re-encoded before forwarding, so only header and question go upstream, which also covers the forwarder's pass-through of questions with compression pointers; (4) TCP connections stay open for further queries until 10 s idle; (5) the cache is capped at 10,000 entries; (6) with port 0, UDP binds the port the OS gave TCP. Hand-verified by Johnny with dig and tcpdump: all response-table rows, NODATA, NXDOMAIN, CNAME chain, AA only on local answers, question case preserved, cache hit with no upstream traffic and TTL reduced by the elapsed time, random upstream ID and source port, TC on a large UDP reply, TCP, immediate SERVFAIL on a refused upstream, survives random junk input; the 45 parser tests still pass. Port 5353 was taken by avahi-daemon (mDNS), so testing used 5354.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**
- **Observations:** (1) no unit tests for resolver or listener, only throwaway checks, the same pattern as V-003 and V-004; (2) the model did not write the prompt log entry itself, noting that entries are written by whoever sent the prompt.

### V-010
- **Module:** blocklist
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-23
- **Refines:**
- **Prompt:** (plan mode, three messages)
```
Okay go over the repo, what parts are unfinished
```
```
This needs to be finsihed asap, could I take Adams modules and then he works on the spec driven version
```
```
Yes do that
```
("that" = the model's offer to plan the blocklist first, because the admin API depends on it)
- **Why this prompt:** took over Adam's modules so `vibe-final` can be tagged sooner; started with a status review to see what was missing.
- **Expected:** a blocklist module plugged into the resolver hook that V-009 left.
- **Got:** `dnsd/blocklist.py`: `Blocklist` with `from_file`/`load`, `add`, `delete`, `domains`, and `blocks(name)`, which walks the name's parents label by label (whole-label match, case-insensitive, trailing dot optional). Reuses `canonical`/`check_name` from `zone.py`. Wired into `__main__.py`; a bad file gives a one-line error. `tests/test_blocklist.py` has 16 tests, including the first resolver tests (blocked A/AAAA/MX, local zone wins over the blocklist, a deleted entry is forwarded). 61/61 tests pass. Hand-checked with dig against 1.1.1.1 on port 5354. Decided on its own: (1) a line with more than one field, such as hosts-file style `0.0.0.0 ads.com`, is a startup error, not skipped; (2) a `#` later in a line is treated as a comment; (3) domains are checked with the zone module's name rules. When asked the first question, the model pointed out that Adam starting the spec build before `vibe-final` would break the README rule. The plan was changed so that Adam starts afterwards.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-011
- **Module:** log
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-23
- **Refines:**
- **Prompt:** (two messages, same session as V-010)
```
commit it, then plan stats and log
```
```
Next create the stats and querrylog
```
- **Why this prompt:** stats and the query log are the next pieces before the admin API, which reads from them. Asked for a plan first, then for the build.
- **Expected:** a stats counter and a query log plugged into the resolver's observer hook from V-009.
- **Got:** `dnsd/stats.py`: `Stats`, called with each `QueryEvent`, counts `queries` and `blocked`; `snapshot()` is merged with `cache.stats()` for /stats. `dnsd/querylog.py`: `QueryLog` keeps the last 1000 events in a deque; `entries(limit=100)` returns /log-shaped dicts, newest first. Both are hooked into the resolver in `__main__.py`. `tests/test_stats.py` has 10 tests, including resolver runs for local, blocked, forwarded, cached and error answers counted once, and dropped, FORMERR and NOTIMP input not counted at all. 71/71 tests pass. Live check against 1.1.1.1 with a scratch script (not committed), since the API isn't there yet: counters and log matched the dig queries, and a 3-byte junk packet wasn't counted. Decided on its own: (1) the log sorts by arrival time rather than insertion order, since a slow forwarded query (up to 2 s) is logged only after it is answered and would otherwise appear newer than it is; (2) checking that `limit` is a non-negative integer (400 otherwise) is left to the API; (3) put the stats and log tests in one file instead of the two it had planned.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-012
- **Module:** api
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-23
- **Refines:**
- **Prompt:** (two messages, same session as V-010 and V-011)
```
yes plan the admin API
```
```
yes build it
```
- **Why this prompt:** the admin API was the last module missing before `vibe-final`. Asked for a plan first, then for the build.
- **Expected:** all eight admin endpoints from contract.md on `--admin`, using the zone, blocklist, stats, cache and query log objects that already exist.
- **Got:** `dnsd/api.py`: `AdminServer` on `ThreadingHTTPServer` (standard library only), with a route table mapping path patterns to methods. It reuses `Zone.add/delete/records`, `Blocklist.add/delete/domains`, `Stats.snapshot()` + `Cache.stats()` and `QueryLog.entries()`; `ZoneError`/`BlocklistError` become 400. `__main__.py` starts it next to the DNS listener and closes both on exit; an unbindable admin port gives a one-line error. `tests/test_api.py` has 20 tests against a real server on a random port: every endpoint, POST idempotence, the 400 cases (bad JSON, missing field, `ttl` true or "60", type MX, bad IP, bad `limit`), 404/405, name forms and percent-encoding, and API changes taking effect on the next DNS query. 91/91 tests pass. Live check with `python -m dnsd`, curl and dig against 1.1.1.1: block/unblock and add/delete record took effect immediately, /stats and /log matched the queries. Decided on its own: (1) every HTTP method goes through one dispatcher, so methods `http.server` has no handler for (PUT, made-up ones) get 405/404 instead of 501; (2) a 201 returns the stored object and errors return `{"error": ...}`; (3) a missing or invalid Content-Length or a body over 64 KiB gives 400, and deeply nested JSON gives 400 rather than a crashed handler; (4) `ttl` is checked with `type() is int`, so `true` is rejected; (5) `limit` must be ASCII digits only; (6) any unexpected handler error gives 500 and is logged; (7) unknown query parameters are ignored and trailing slashes give 404. Observation: each API test takes about 0.5 s to tear down because `serve_forever` checks for shutdown every 0.5 s; left as is.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**

### V-013
- **Module:** api
- **Who / tool / model:** Daniel / Claude Code / Claude Opus 5.5
- **Date:** 2026-10-23
- **Refines:**
- **Prompt:** (two messages, same session as V-010 to V-012)
```
yes plan the vibe frontend
```
```
yes build it
```
- **Why this prompt:** the contract now includes a web dashboard at `/ui` (changed in both repos the same day, `14151fa` / `e0eae40`), and each build makes its own with its own method. The vibe one has to be done before `vibe-final`.
- **Expected:** a dashboard meeting the new `/ui` section of contract.md: self-contained, admin API only, with stats, blocklist, records and log, add/delete, and errors shown.
- **Got:** `dnsd/ui.html` (276 lines): one page with inline CSS and JS, light/dark from the system, refreshing every 2 s. Every value is put on the page with `textContent`, never as HTML, because log names come from any DNS client. `dnsd/api.py`: a `("ui",)` route; the page is read once at server start and served as `text/html; charset=utf-8`; `_send` sends a `bytes` body as HTML. 3 new tests in `tests/test_api.py` (status and content type; self-contained and no HTML insertion from data; 405/404). 94/94 unit tests and 244/244 tests in the shared suite (including the new `/ui` tests) pass on Python 3.11. Checked in headless Chrome with Playwright against a real `python -m dnsd`, using a throwaway script (not committed): 18 checks covering load, block/unblock, add/delete record checked with dig, a 400 error shown and the form kept, a hostile `<img onerror>` query name shown as text, auto-refresh, server down shown, no JS errors and no requests to other hosts; plus page widths 320 to 1200 px. Decided on its own: (1) latest 50 log entries; (2) refresh every 2 s; (3) the × on a record deletes every record of that name and type, as the API's DELETE does, and the tooltip says so; (4) tables sorted by name. Bugs it caught in its own work while testing: `_send` would have sent `null` as the body of a 204; phones got a horizontal scrollbar because the grid grew to fit the widest table; `form.name` could mean the form's own name, so fields are read through `form.elements`. Noted for review, not fixed: the admin API accepts a POST from any website (no `Content-Type` or `Origin` check), so a page in the browser could change the blocklist while the server runs; this was there before the dashboard.
- **Verdict:** worked
- **Failure mode:**
- **Fixed by:**
