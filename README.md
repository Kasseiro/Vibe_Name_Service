# Do Not Suck (DNS) – vibe-coded build

Team E. Local DNS resolver with Pi-hole style blocking, built by vibe coding.
The spec-driven build of the same system lives in `Das_Name_Service`, which also holds
the black-box test suite that is run against both.

| Person | Role | Modules |
|---|---|---|
| Johnny Löfman | Protocol Core Developer, Lead Spec Writer | wire parser, UDP/TCP listener |
| Daniel Kass | Resolution Logic Developer, Prompt Engineer | local zone, forwarder, cache |
| Adam Beijar | Admin API Developer, Testing & Verification Lead | blocklist, query log, admin API |

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
```

## Commit messages

```
<type>(<module>): <what changed>

Prompt: V-014
```

`type`: feat, fix, test, docs, refactor, chore.
`module`: parser, listener, zone, forwarder, cache, blocklist, api, report.

`git log --grep "Prompt: V-"` lists every AI-generated change.

## Running

```
python -m dnsd --listen 127.0.0.1:5353 --admin 127.0.0.1:8080 \
  --zone zone.txt --blocklist blocklist.txt --upstream 1.1.1.1:53
```
