"""HC event-wire layer (v1 — PR-wire consumer).

Consumes the PRN/BW/GlobeNewswire NewsItems that halt_monitor already fetches
each news poll, classifies each into an HC event type (clinical-trial topline
readout / FDA approval / CRL / medtech clearance), and — via the emit path in
halt_monitor — fires an SA-faithful #street-account alert when the issuer's
self-identified ticker is in the covered universe.

Design of record: research/sa_monitor_hc_event_wire_design_2026-07-13.md.

- `types.HCEvent`  — the classified-event dataclass.
- `classify.classify(item) -> Optional[HCEvent]` — precision-biased keyword
  classifier anchored to the locked headlines in template-library.md §15/§16/§19.

The universe filter, per-ticker attribution, dedup, and delivery gating live in
halt_monitor._emit_hc_events — this package only decides *what kind of event*
a headline is (or None), never *whether to fire*.
"""
