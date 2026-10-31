# Verification of `vibe-final`

Build: `vibe-final` = `bb5e600`. Shared suite: `Das_Name_Service` at `cfe9ef2`
(tests unchanged since `4d08cff`). Run on 2026-10-31 by Daniel, standing in for Adam.
Python 3.11.16, pytest 9.2.0, dnspython 2.9.1, ruff 0.17.3, bandit 1.9.4.

| Check | Command | Result | Output |
|---|---|---|---|
| Unit tests | `python -m unittest` | 94/94 pass | [unittest.txt](unittest.txt) |
| Shared suite | `pytest tests --impl=../Vibe_Name_Service` (run in `Das_Name_Service`) | 244/244 pass | [pytest.txt](pytest.txt), [results.xml](results.xml) |
| Fuzzer | `tests/test_fuzz.py` in the shared suite (seed 1035, 2000 packets) | pass | as above |
| ruff | `ruff check dnsd` (default rules) | 3 findings | [ruff.txt](ruff.txt) |
| bandit | `bandit -r dnsd` | 1 Medium finding, a false positive | [bandit.txt](bandit.txt) |
| Review | Claude Code `/code-review` at high effort over `dnsd/`, each finding checked by Daniel | 10 findings | `docs/audit-log.md` |

Every finding is in `docs/audit-log.md` as VA-001 to VA-013 (12 open, 1 not a flaw).
None was fixed. The numbers above describe the build exactly as tagged.

Every check passed, yet the review found flaws that no test covers. VA-001, VA-002,
VA-003, VA-005 and VA-006 were reproduced against a running `python -m dnsd`, including:
- a cross-origin POST changes the zone (VA-001)
- a TCP reply over 64 KiB gets no answer (VA-002)
- the API accepts a record that then always gives SERVFAIL (VA-003)
