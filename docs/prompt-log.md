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
