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
from .reason_codes import is_phase1_emit_code

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
    # halt_ids we actually DELIVERED a halt alert for (passed the non-emit-code
    # filter AND — in live mode — posted successfully). seen_halts records mere
    # OBSERVATIONS; this records deliveries. A §7 Follow-up may only fire for a
    # halt we delivered. Persisted so a restart preserves the gate.
    emitted_halts: set[HaltId] = field(default_factory=set)
    # halt_ids for which a §7 Follow-up alert has already fired — one per halt,
    # ever. Persisted alongside seen_halts so a mid-session restart never
    # re-emits a follow-up.
    followed_up: set[HaltId] = field(default_factory=set)
    # Delivery-dedup for the HC event-wire lane. Keys are strings of the form
    # f"{news_id}|{symbol}|{event_type}" — one alert per (press release,
    # covered ticker, event type), ever. Persisted like followed_up so a
    # mid-session restart never re-emits an HC event. (Mirrors emitted_halts /
    # followed_up exactly; unlike them, keyed by string not HaltId.)
    hc_events_emitted: set[str] = field(default_factory=set)

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

            # Already seen. Fix #3: the SAME halt is reported by both feeds
            # (Nasdaq RSS + NYSE CSV), and one source can carry a malformed /
            # blank / non-emittable reason_code while the other carries the
            # valid emittable one. If the first sighting was non-emit it got
            # filtered in _emit and NEVER delivered — but it still recorded
            # seen_halts, so without this a later emittable record for the same
            # halt_id is silently shadowed. Re-yield "halt" when the stored code
            # was non-emit and the incoming one is emittable, but ONLY while the
            # halt was never actually delivered (emitted_halts is the delivery
            # ledger) so a genuinely-delivered halt never double-posts.
            # A placeholder rehydrated from disk (state.load) always has an
            # empty reason_code; it is NOT a genuine non-emit first source, so
            # exclude it — #3 is about same-session cross-SOURCE shadowing, and
            # the persisted emitted_halts set already governs restart dedup.
            upgraded = (
                hid not in self.emitted_halts
                and previous.source != "restored_from_state"
                and not is_phase1_emit_code(previous.reason_code)
                and is_phase1_emit_code(event.reason_code)
            )
            # update stored event (resume info may have populated since the
            # prior poll; also keep the better reason record)
            self.seen_halts[hid] = event
            if upgraded:
                yield ("halt", event)
            if event.is_resumed and hid not in self.resumes_emitted:
                self.resumes_emitted.add(hid)
                yield ("resume", event)

    def __len__(self) -> int:
        return len(self.seen_halts)

    def reset(self) -> None:
        """Clear state — used at session boundary or for tests."""
        self.seen_halts.clear()
        self.resumes_emitted.clear()
        self.emitted_halts.clear()
        self.followed_up.clear()
        self.hc_events_emitted.clear()
