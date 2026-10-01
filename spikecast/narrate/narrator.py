"""The commentary pipeline for one line: pick an event, write about it, check it.

    highest-priority event  ->  Claude writes  ->  rule check  ->  the line

A line that fails the rule check is rewritten once with the reason; if that fails too, the
event's own rule-built sentence is used instead. Narration never stalls on a model: with no
writer, the rule-built sentence is the line. Every attempt is kept, so the rejection rate
can be reported.
"""

import re
from dataclasses import dataclass, field

from spikecast.narrate.config import settings
from spikecast.narrate.events import Event
from spikecast.narrate.grounding import check_line, glossary_for
from spikecast.narrate.writer import Writer


@dataclass
class Draft:
    """A line and how it came to be."""

    event: Event
    text: str
    source: str  # "claude" or "template"
    attempts: list[dict] = field(default_factory=list)

    @property
    def key(self) -> str | None:
        """The word to colour: the first of the event's key words that the line uses."""
        words = {re.sub(r"[^\w'-]", "", w).lower(): w for w in self.text.split()}
        for key in self.event.keys:
            if key.lower() in words:
                return re.sub(r"[^\w'-]", "", words[key.lower()])
        return None


class Narrator:
    def __init__(self, mode: str = "broadcast", use_models: bool = True):
        self.writer = Writer(mode=mode, enabled=use_models)
        self.max_words = settings()["max_words"]

    def line_for(self, waiting: list[Event], previous: list[str]) -> Draft:
        event = max(waiting, key=lambda e: (e.priority, -e.frame))
        glossary = glossary_for(event.cells)
        attempts: list[dict] = []
        rejected: tuple[str, str] | None = None
        for _ in range(2):
            text, problem = self.writer.write(event, glossary, previous, rejected)
            if text is None:
                attempts.append({"text": None, "writer": problem})
                break
            rule = check_line(text, event.cells, event.facts, self.max_words)
            attempts.append({"text": text, "rule": "pass" if rule.ok else rule.reason})
            if rule.ok:
                return Draft(event, text, "claude", attempts)
            rejected = (text, rule.reason)
        return Draft(event, event.summary, "template", attempts)
