"""Source-derived tag fixture plus explicitly synthetic robustness probes."""

import argparse
import json
import sys
import time


def messages(timestamp: int = 1770000000) -> list[bytes]:
    tag = (
        json.dumps(
            {
                "type": "tag",
                "station": 1,
                "timestamp": timestamp,
                "sequence": 2,
                "uid": "04A78319BCDE12",
                "callsign": "DD1SB",
                "rssi": -70,
            },
            separators=(",", ":"),
        )
        + "\n"
    ).encode()
    return [
        tag,
        tag,
        b'{"type":"future_probe","extra":true}\n',
        b'{"type":"tag",broken\n',
        b'{"type":"time_request","station":1,"meshSource":1,"sequence":3}\n',
        b'{"type":"time","status":"synchronized","timestamp":1770000000}\n',
        b'{"type":"sync","station":1,"timestamp":1770000000}\n',
    ]


def emit(count: int = 1, interval: float = 0) -> None:
    if count < 1 or interval < 0:
        raise ValueError("count must be positive and interval nonnegative")
    for cycle in range(count):
        for raw in messages(1770000000 + cycle):
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
            if interval:
                time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0)
    args = parser.parse_args()
    emit(args.count, args.interval)


if __name__ == "__main__":
    main()
