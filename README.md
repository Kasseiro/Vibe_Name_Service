# Do Not Suck (DNS) – vibe-coded build

Team E. Local DNS resolver with Pi-hole style blocking, built by vibe coding.
The spec-driven build of the same system lives in `Das_Name_Service`, which also holds
the black-box test suite that is run against both.

| Person | Role | Modules |
|---|---|---|
| Johnny Löfman | Protocol Core Developer, Lead Spec Writer | wire parser, UDP/TCP listener |
| Daniel Kass | Resolution Logic Developer, Prompt Engineer | local zone, forwarder, cache, blocklist, query log, admin API |
| Adam Beijar | Testing & Verification Lead | verification after `vibe-final` |

Daniel took over the blocklist, query log and admin API so the vibe build could be
finished sooner. To keep the work even, Adam works more in the spec-driven build in
`Das_Name_Service` after `vibe-final` is tagged, and Daniel does not work on it.

## Ground rules for this repo

- Inputs allowed: `contract.md` and whatever you type into the chat. No specs, no
  plans, no peeking at `Das_Name_Service` or its tests.
- This build is finished first. When it is done, tag the last commit `vibe-final`;
  the test results in the report refer to that tag, and spec work in
  `Das_Name_Service` does not start before it.
- Commit directly to main. There is no review during development. After `vibe-final`
  is tagged, the build is verified with the shared test suite, the fuzzer, ruff and
  bandit, and one review pass. Every flaw found goes in `docs/audit-log.md`.
- Every prompt whose output gets committed goes in `docs/prompt-log.md`, written
  when it happens.

## Layout

```
contract.md         external behaviour (shared with Das_Name_Service, frozen)
docs/prompt-log.md  prompts, IDs V-001, V-002, ...
docs/audit-log.md   flaws found in review, IDs VA-001, ...
dnsd/__main__.py    entry point, command line flags
dnsd/zone.py        local zone: zone file, lookup, add/delete records
dnsd/cache.py       TTL cache with hit and miss counters
dnsd/forwarder.py   forwards queries to the upstream resolver over UDP/TCP
dnsd/parser.py      DNS wire format: parse queries and replies, build responses
dnsd/resolver.py    answers one query: zone, blocklist, cache, upstream, in that order
dnsd/listener.py    UDP and TCP servers on the --listen address
dnsd/blocklist.py   blocklist file, label-wise matching, add/delete domains
dnsd/stats.py       queries and blocked counters for /stats
dnsd/querylog.py    the most recent 1000 queries for /log
dnsd/api.py         admin API (JSON over HTTP) on the --admin address
dnsd/ui.html        web dashboard, served by the admin API at /ui
tests/              unit tests: python -m unittest
```

## Commit messages

```
<type>(<module>): <what changed>

Prompt: V-014
```

`type`: feat, fix, test, docs, refactor, chore.
`module`: parser, listener, zone, forwarder, cache, blocklist, log, api, report.

`git log --grep "Prompt: V-"` lists every AI-generated change.

## Running

```
python -m dnsd --listen 127.0.0.1:5353 --admin 127.0.0.1:8080 \
  --zone zone.txt --blocklist blocklist.txt --upstream 1.1.1.1:53
```

The dashboard is then at http://127.0.0.1:8080/ui. `docs/demo.sh` walks through
every case in `contract.md` with dig and curl.
