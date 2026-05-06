"""Halt-event deduplication.

Both the Nasdaq RSS and NYSE CSV feeds report the same halt event (since the
exchange tape consolidates both). Polling at 5s means each event re-appears
in N consecutive polls until the feed rolls it off. We dedupe by halt-id
`(symbol, halt_date, halt_time)` so the runner only fires one Slack message
per real event, and one resume message per resume.

State lives in memory for the duration of a single market-session run. A
small persistence layer (writing seen-ids to disk between polls) is deferred
to D6 — the end-to-end runner — so the script survives restart-mid-session.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterator

from .feeds.types import HaltEvent

# halt_id -> the most-recently-seen HaltEvent for that id (so resume info
# accumulates as the feed publishes it).
HaltId = tuple[str, str, str]


@dataclass
class HaltTracker:
    """Tracks halt + resume events across feed polls.

    Use:
        tracker = HaltTracker()
        for event in tracker.ingest(events_from_this_poll):
            ... # only new halts and newly-published resumes come out
    """

    seen_halts: dict[HaltId, HaltEvent] = field(default_factory=dict)
    resumes_emitted: set[HaltId] = field(default_factory=set)

    def ingest(self, events: list[HaltEvent]) -> Iterator[tuple[str, HaltEvent]]:
        """Diff `events` against state and yield (kind, event) for new ones.

        kind ∈ {"halt", "resume"}.

        - halt: first time we see this halt_id
        - resume: previously-seen halt now has a resume_trade_time populated
          AND we haven't emitted a resume for this halt_id yet
        """
        for event in events:
            hid = event.halt_id
            previous = self.seen_halts.get(hid)

            if previous is None:
                # First sighting — emit halt
                self.seen_halts[hid] = event
                yield ("halt", event)
                # If the very first sighting already includes a resume time
                # (rare — usually catch-up from a feed roll), also emit resume
                if event.is_resumed and hid not in self.resumes_emitted:
                    self.resumes_emitted.add(hid)
                    yield ("resume", event)
                continue

            # Already seen — update stored event (resume info may have
            # populated since the prior poll) and check whether resume
            # is freshly-known.
            self.seen_halts[hid] = event
            if event.is_resumed and hid not in self.resumes_emitted:
                self.resumes_emitted.add(hid)
                yield ("resume", event)

    def __len__(self) -> int:
        return len(self.seen_halts)

    def reset(self) -> None:
        """Clear state — used at session boundary or for tests."""
        self.seen_halts.clear()
        self.resumes_emitted.clear()
