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
