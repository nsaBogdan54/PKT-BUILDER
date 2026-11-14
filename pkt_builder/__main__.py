"""``python -m pkt_builder`` -- run the command line interface."""

import sys

from pkt_builder.cli import main

if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        sys.exit(130)
