"""News-wire ingest layer (Phase 2 slice 2A).

Three public-RSS news sources for halt cross-reference:
- PR Newswire (prnewswire.com)
- Business Wire (businesswire.com)
- GlobeNewswire (globenewswire.com)

All three publish a healthcare-tagged sub-feed plus a firehose. Adapters here
return a uniform NewsItem regardless of source. Slice 2A ships the parsers
without any integration into halt_monitor.py — slice 2B builds the cross-ref
engine on top.

Mirrors the architectural shape of `src/feeds/` (the halt-feed layer): one
module per source, a shared `types` module, a thin `fetch()` that wraps
`parse(bytes)`.
"""
