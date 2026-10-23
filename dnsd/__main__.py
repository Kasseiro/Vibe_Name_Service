import argparse
import logging
import sys

from dnsd.api import AdminServer
from dnsd.blocklist import Blocklist, BlocklistError
from dnsd.cache import Cache
from dnsd.forwarder import Forwarder
from dnsd.listener import Listener
from dnsd.querylog import QueryLog
from dnsd.resolver import Resolver
from dnsd.stats import Stats
from dnsd.zone import Zone, ZoneError

CACHE_SIZE = 10000


def parse_args(argv=None):
    parser = argparse.ArgumentParser(prog="dnsd")
    parser.add_argument("--listen", default="127.0.0.1:5353")
    parser.add_argument("--admin", default="127.0.0.1:8080")
    parser.add_argument("--zone")
    parser.add_argument("--blocklist")
    parser.add_argument("--upstream", default="1.1.1.1:53")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="dnsd: %(levelname)s %(message)s")
    try:
        zone = Zone.from_file(args.zone) if args.zone else Zone()
        blocklist = Blocklist.from_file(args.blocklist) if args.blocklist else Blocklist()
        forwarder = Forwarder(args.upstream)
    except (OSError, ZoneError, BlocklistError) as e:
        sys.exit(f"dnsd: {e}")
    cache = Cache(max_size=CACHE_SIZE)

    stats = Stats()
    querylog = QueryLog()

    resolver = Resolver(zone, cache, forwarder, blocklist, [stats, querylog])

    try:
        listener = Listener(args.listen, resolver)
    except (OSError, ValueError) as e:
        sys.exit(f"dnsd: cannot listen on {args.listen}: {e}")
    try:
        admin = AdminServer(args.admin, zone, blocklist, cache, stats, querylog)
    except (OSError, ValueError) as e:
        listener.close()
        sys.exit(f"dnsd: cannot listen on {args.admin}: {e}")
    admin.start()
    logging.info("listening on %s (UDP and TCP), upstream %s", args.listen, args.upstream)
    logging.info("admin API on %s", args.admin)
    try:
        listener.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        admin.close()
        listener.close()


if __name__ == "__main__":
    main()
