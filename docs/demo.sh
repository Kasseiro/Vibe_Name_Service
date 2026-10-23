#!/usr/bin/env bash
# Demo of the vibe build. Starts dnsd with a sample zone and blocklist, then
# walks through every case in contract.md with dig and curl.
#
#   docs/demo.sh              run straight through
#   STEP=1 docs/demo.sh       wait for Enter before each step
#
# Needs python3 (3.11+), dig and curl, and network access to the upstream.
# Overrides: PYTHON, DNS_PORT (5354), ADMIN_PORT (8081), UPSTREAM (1.1.1.1:53).
set -euo pipefail

PYTHON=${PYTHON:-python3}
DNS_PORT=${DNS_PORT:-5354}
ADMIN_PORT=${ADMIN_PORT:-8081}
UPSTREAM=${UPSTREAM:-1.1.1.1:53}
ADMIN=http://127.0.0.1:$ADMIN_PORT

cd "$(dirname "$0")/.."
for tool in "$PYTHON" dig curl; do
    command -v "$tool" >/dev/null || { echo "demo: $tool not found" >&2; exit 1; }
done

work=$(mktemp -d)
server=
cleanup() {
    if [ -n "$server" ]; then
        kill "$server" 2>/dev/null || true
        wait "$server" 2>/dev/null || true
    fi
    rm -rf "$work"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

cat > "$work/zone.txt" <<'EOF'
; sample local zone
nas.home.lan.      300 IN A     192.168.1.10
nas.home.lan.      300 IN AAAA  fd00::10
files.home.lan.    300 IN CNAME nas.home.lan.
printer.home.lan.  300 IN A     192.168.1.20
EOF
cat > "$work/blocklist.txt" <<'EOF'
# sample blocklist
ads.example.com
Tracker.Example.NET.
EOF

step() {
    printf '\n\033[1m== %s\033[0m\n' "$*"
    if [ "${STEP:-0}" = 1 ]; then read -r -p "(Enter) " _; fi
}

# dig, showing only the status line, the flags and the answer section.
ask() {
    printf '$ dig %s\n' "$*"
    dig @127.0.0.1 -p "$DNS_PORT" +noall +comments +answer "$@" \
        | grep -E '^;; ->>HEADER|^;; flags|^[^;]' || true
}

# curl against the admin API, printing the body and the status code.
api() {
    local method=$1 path=$2 body=${3:-}
    printf '$ curl -X %s %s%s\n' "$method" "$path" "${body:+ -d '$body'}"
    curl -s -X "$method" ${body:+-H 'Content-Type: application/json' -d "$body"} \
        -w ' [%{http_code}]\n' "$ADMIN$path"
}

if curl -s -o /dev/null "$ADMIN/" || dig @127.0.0.1 -p "$DNS_PORT" +time=1 +tries=1 . >/dev/null; then
    echo "demo: port $DNS_PORT or $ADMIN_PORT is already in use; set DNS_PORT and ADMIN_PORT" >&2
    exit 1
fi

step "Start dnsd"
echo "\$ $PYTHON -m dnsd --listen 127.0.0.1:$DNS_PORT --admin 127.0.0.1:$ADMIN_PORT --zone zone.txt --blocklist blocklist.txt --upstream $UPSTREAM"
"$PYTHON" -m dnsd --listen "127.0.0.1:$DNS_PORT" --admin "127.0.0.1:$ADMIN_PORT" \
    --zone "$work/zone.txt" --blocklist "$work/blocklist.txt" --upstream "$UPSTREAM" \
    > "$work/dnsd.log" 2>&1 &
server=$!
for _ in $(seq 50); do
    curl -s -o /dev/null "$ADMIN/stats" && break
    kill -0 "$server" 2>/dev/null || { cat "$work/dnsd.log" >&2; exit 1; }
    sleep 0.1
done
cat "$work/dnsd.log"
echo "dashboard: $ADMIN/ui"
echo "zone.txt:"; sed 's/^/    /' "$work/zone.txt"
echo "blocklist.txt:"; sed 's/^/    /' "$work/blocklist.txt"

step "Local zone: answered authoritatively (aa flag)"
ask nas.home.lan A
ask NAS.Home.Lan AAAA

step "CNAME: the CNAME record, followed by the target's records"
ask files.home.lan A

step "NODATA: the name exists, the type does not"
ask printer.home.lan AAAA

step "NXDOMAIN: under the local zone suffix home.lan., but not defined"
ask nope.home.lan A

step "Blocked: A -> 0.0.0.0, AAAA -> ::, other types -> NXDOMAIN, TTL 60, no aa"
ask ads.example.com A
ask x.ads.example.com AAAA
ask tracker.example.net MX

step "Blocking matches whole labels: xads.example.com is not blocked, so it is forwarded"
ask xads.example.com A

step "Forwarded to the upstream, then answered from the cache with the TTL counted down"
ask example.com A
sleep 2
ask example.com A

step "TCP (2-byte length prefix)"
ask example.com A +tcp

step "UDP replies over 512 bytes are truncated (tc flag); dig would retry over TCP"
ask google.com TXT +ignore

step "Malformed input: under 12 bytes gets no reply, QDCOUNT 0 gets FORMERR"
"$PYTHON" - "$DNS_PORT" <<'EOF'
import socket, struct, sys
port = int(sys.argv[1])
for label, packet in (("3 bytes", b"\x12\x34\x01"),
                      ("QDCOUNT=0", struct.pack("!HHHHHH", 0xBEEF, 0x0100, 0, 0, 0, 0))):
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(1)
        s.sendto(packet, ("127.0.0.1", port))
        try:
            reply = s.recv(512)
        except TimeoutError:
            print(f"{label}: no reply")
            continue
        ident, flags = struct.unpack("!HH", reply[:4])
        rcode = {1: "FORMERR", 4: "NOTIMP"}.get(flags & 0xF, flags & 0xF)
        print(f"{label}: {len(reply)}-byte reply, id {ident:#06x}, {rcode}")
EOF

step "Admin API: block a domain at runtime, no restart"
api GET /blocklist
ask www.example.org A
api POST /blocklist '{"domain": "Example.ORG"}'
ask www.example.org A
api DELETE /blocklist/example.org
ask www.example.org A

step "Admin API: add and delete a local record at runtime"
api POST /records '{"name": "tv.home.lan", "type": "A", "ttl": 60, "value": "192.168.1.50"}'
ask tv.home.lan A
api GET /records
api DELETE /records/tv.home.lan/A
ask tv.home.lan A

step "Admin API: counters and the query log"
api GET /stats
printf '$ curl %s\n' "/log?limit=5"
curl -s "$ADMIN/log?limit=5" | "$PYTHON" -m json.tool

step "Admin API: error codes"
api POST /records '{"name": "x.home.lan", "type": "MX", "ttl": 60, "value": "x"}'
api GET '/log?limit=-1'
api PUT /stats
api GET /nope

step "Done"
echo "dnsd stopped; the zone and blocklist files were temporary."
