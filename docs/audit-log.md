# Code audit log

Owner: Adam. Everyone adds entries when a review or test catches something in AI output.

| ID | Module | Found by | Category | Issue | Resolution | Prompt / commit |
|---|---|---|---|---|---|---|
| VA-001 | | review / test / linter | security / logic / compliance | | AI re-prompt / manual fix / spec change | |

Category guide:
- **security**: predictable transaction IDs, fixed source port, accepting responses with the wrong ID, crash on malformed input
- **logic**: NXDOMAIN vs NODATA mixed up, TTL not decremented, CNAME not followed, wrong AA/RA flags
- **compliance**: anything that breaks an RFC 1035 rule or `contract.md`
