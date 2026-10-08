import argparse


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
    for key, value in vars(args).items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
