# PokerStars adapter development fixtures

Every history in this directory is synthetic and uses invented hand IDs,
player names, timestamps, and amounts. The files contain no production export,
credential, account identifier, or player-identifying data.

These fixtures exercise deterministic adapter behavior only. They are not the
representative corpus required by issue #409 and must not be used to claim its
approximately 1,000-hand coverage or 99% clean-parse gate.

The separately attributed `public-format/` directory contains a sanitized
public format specimen. It is not synthetic and has its own provenance,
license, and evidence-boundary documentation.
