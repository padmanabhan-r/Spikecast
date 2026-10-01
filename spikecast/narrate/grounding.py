"""The rule check: the first of two checks every narrated line must pass.

A line may name only cell types that are in the event it describes, and may state only
numbers that were measured in that event. This check alone decides whether a cell-type
mention can ship. It is deliberately strict and dumb: no model is involved.
"""

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import yaml

GLOSSARY_PATH = Path(__file__).with_name("glossary.yaml")

# Words that state a quantity without a digit. Each needs a measured value to stand on.
NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8,
    "nine": 9, "ten": 10, "twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "hundred": 100,
    "half": 50, "halved": 50, "quarter": 25, "third": 33, "twice": 2, "double": 2, "doubled": 2,
    "triple": 3,
}  # fmt: skip
# "one" as a pronoun or article is not a quantity claim.
FREE_NUMBER_WORDS = {"one"}

# A token that looks like a cell-type code: capitals followed by digits, e.g. DNa02, MBON07.
CODE = re.compile(r"\b[A-Z]{2,}[a-z]?-?[A-Za-z]?\d+[A-Za-z0-9]*\b|\b[A-Z]{3,}s?\b")
NUMBER = re.compile(r"(?<![A-Za-z])\d+(?:[.,]\d+)?")


@dataclass
class Verdict:
    ok: bool
    reason: str = ""


@lru_cache
def load_glossary() -> dict:
    return yaml.safe_load(GLOSSARY_PATH.read_text())


def _mentions(line: str, phrase: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9]){re.escape(phrase)}(?![A-Za-z0-9])", line, re.I) is not None


def cells_mentioned(line: str) -> dict[str, set[str]]:
    """Every glossary phrase found in the line, with the cell types it could refer to."""
    found: dict[str, set[str]] = {}
    for key, entry in load_glossary()["cells"].items():
        for phrase in [entry["name"], *entry.get("aliases", [])]:
            if _mentions(line, phrase):
                found.setdefault(phrase.lower(), set()).add(key)
    return found


def _numbers_in(facts: dict) -> list[float]:
    values = []
    for value in facts.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, int | float):
            values.append(float(value))
        elif isinstance(value, str):
            values += [float(m.replace(",", "")) for m in NUMBER.findall(value)]
    return values


def _supported(number: float, measured: list[float]) -> bool:
    # A measured value may be quoted rounded: to a whole number, or to the nearest ten when large.
    for value in measured:
        tolerance = max(0.5, 0.05 * abs(value))
        if abs(number - value) <= tolerance:
            return True
        # milliseconds may be said in seconds, and a fraction as a percentage
        if abs(number - value / 1000) <= 0.05 or abs(number - value * 100) <= 0.5:
            return True
    return False


def glossary_for(cells: list[str]) -> list[dict]:
    """The glossary entries the writer and the judge are shown for an event."""
    entries = load_glossary()["cells"]
    return [
        {"name": entries[c]["name"], "nickname": entries[c]["nickname"], "role": entries[c]["role"]}
        for c in cells
        if c in entries
    ]


def check_line(line: str, cells: list[str], facts: dict, max_words: int = 20) -> Verdict:
    words = line.split()
    if not words:
        return Verdict(False, "empty line")
    if len(words) > max_words:
        return Verdict(False, f"{len(words)} words; the limit is {max_words}")
    if "\n" in line.strip():
        return Verdict(False, "more than one line")

    allowed = set(cells)
    mentioned = cells_mentioned(line)
    for phrase, keys in mentioned.items():
        if not keys & allowed:
            return Verdict(False, f"names '{phrase}', which is not in this event")

    # A code-like token that is not a known name is an invented cell type.
    known = {
        token.lower()
        for entry in load_glossary()["cells"].values()
        for phrase in [entry["name"], *entry.get("aliases", [])]
        for token in phrase.split()
    }
    for token in CODE.findall(line):
        if token.lower().rstrip("s") not in known and token.lower() not in known:
            if token.upper() in {"AI", "LLM", "USA"}:
                continue
            return Verdict(False, f"'{token}' looks like a cell type that is not in the glossary")

    measured = _numbers_in(facts)
    for raw in NUMBER.findall(line):
        if not _supported(float(raw.replace(",", "")), measured):
            return Verdict(False, f"states the number {raw}, which was not measured in this event")
    for word in re.findall(r"[A-Za-z]+", line.lower()):
        if word in NUMBER_WORDS and word not in FREE_NUMBER_WORDS:
            if not _supported(float(NUMBER_WORDS[word]), measured):
                return Verdict(False, f"states a quantity ('{word}') that was not measured")
    return Verdict(True)
