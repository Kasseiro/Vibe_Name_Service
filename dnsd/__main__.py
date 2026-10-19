import argparse
import logging
import sys

from dnsd.cache import Cache
from dnsd.forwarder import Forwarder
from dnsd.listener import Listener
from dnsd.resolver import Resolver
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
        forwarder = Forwarder(args.upstream)
    except (OSError, ZoneError) as e:
        sys.exit(f"dnsd: {e}")
    cache = Cache(max_size=CACHE_SIZE)

    # TODO(blocklist): load args.blocklist into an object with blocks(name) -> bool.
    blocklist = None
    # TODO(stats, log): append the stats counter and the query log; each gets a
    # resolver.QueryEvent for every query counted in /stats.
    observers = []

    resolver = Resolver(zone, cache, forwarder, blocklist, observers)

    try:
        listener = Listener(args.listen, resolver)
    except (OSError, ValueError) as e:
        sys.exit(f"dnsd: cannot listen on {args.listen}: {e}")
    # TODO(api): serve the admin API on args.admin from zone, blocklist,
    # cache.stats(), the stats counter and the query log.
    logging.info("listening on %s (UDP and TCP), upstream %s", args.listen, args.upstream)
    try:
        listener.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        listener.close()


if __name__ == "__main__":
    main()
