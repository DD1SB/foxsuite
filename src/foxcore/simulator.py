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
        f'{{"type":"time","status":"synchronized","timestamp":{timestamp}}}\n'.encode(),
        f'{{"type":"sync","station":1,"timestamp":{timestamp}}}\n'.encode(),
    ]


def emit(count: int = 1, interval: float = 0, timestamp: int | None = None) -> None:
    if count < 1 or interval < 0:
        raise ValueError("count must be positive and interval nonnegative")
    start = int(time.time()) if timestamp is None else timestamp
    for cycle in range(count):
        for raw in messages(start + cycle):
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
            if interval:
                time.sleep(interval)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--interval", type=float, default=0)
    parser.add_argument("--timestamp", type=int, help="Unix seconds; defaults to current PC time")
    args = parser.parse_args()
    emit(args.count, args.interval, args.timestamp)


if __name__ == "__main__":
    main()
