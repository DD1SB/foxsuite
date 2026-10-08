"""Small, transparent duplicate-review helpers; never merge identities."""

import re
from difflib import SequenceMatcher

from .models import Club, ClubData, Runner, RunnerData


def comparable(value: str) -> str:
    return " ".join(value.strip().casefold().split())


def club_matches(data: ClubData, clubs: list[Club]) -> dict[str, list[Club]]:
    code, name = comparable(data.code), comparable(data.display_name)
    exact, similar = [], []
    stop = {"darc", "ov", "radio", "club", "amateur", "der", "the"}
    words = set(re.findall(r"\w+", name)) - stop
    for club in clubs:
        other = comparable(club.display_name)
        if (code and code == comparable(club.code)) or (name and name == other):
            exact.append(club)
        elif name and (
            SequenceMatcher(None, name, other).ratio() >= 0.78
            or bool(words & (set(re.findall(r"\w+", other)) - stop))
        ):
            similar.append(club)
    return {"exact": exact, "similar": similar[:20]}


def runner_matches(data: RunnerData, runners: list[Runner]) -> list[Runner]:
    name = comparable(f"{data.first_name} {data.last_name}")
    return [
        r
        for r in runners
        if name
        and (
            comparable(f"{r.first_name} {r.last_name}") == name
            or (
                comparable(r.last_name) == comparable(data.last_name)
                and data.birth_year is not None
                and r.birth_year == data.birth_year
            )
        )
    ][:20]
