# Postflop Solver Plugin

This binary adapts the AGPL-licensed
[`postflop-solver`](https://github.com/b-inary/postflop-solver) library to Poker
Hero's stdin/stdout JSON recommendation contract. The dependency is pinned to
revision `9d1509fe5077d019825f833eed04b16d342dfda1`.

It supports heads-up flop, turn, and river decisions with explicit IP/OOP
position or an unambiguous pair of reviewed six-max seats. Canonical `dealer`
positions are equivalent to the button and use the IP route. Contradictory,
duplicate, unknown, and bare small-blind versus big-blind seat pairs are
rejected rather than guessed. A raised decision requires ordered current-street
OOP/IP actions and both visible player stacks. Bet and raise amounts are total
chips committed by that player on the street; contradictory or incomplete
histories are rejected before solving. Poker Hero routes supported preflop
states to its position-aware training chart, and routes ambiguous positions,
ambiguous preflop, multiway postflop, incomplete, and resource-limited spots to
the bundled range/EV engine when fallback is enabled.

The backend defaults to contextual range selection. An exact heads-up
state with a single-raised-pot history, matching reviewed seats, and a verified
root pot uses the preflop chart's position-specific opener boundary and
flat-caller band. An exact open/3-bet/call history can instead use the adjusted
3-bettor range and the opener's call band after removing its 4-bet segment. An
exact open/3-bet/4-bet/call history can use the opener's adjusted 4-bet range and
the 3-bettor's call band after removing its 5-bet segment. The modeled sizes
and a reconstructable starting effective stack follow the chart's existing
response adjustments. Incomplete stack evidence uses a labeled 100 BB standard
assumption. A turn state additionally requires a terminal completed-flop line;
a river state requires terminal completed-flop and completed-turn lines. The
backend uses those lines to verify the original pot and stack assumptions. With
both visible stacks, the adapter also runs a compact flop-root conditioning
solve, replays the terminal actions and actual dealt cards, and passes the
posterior hand weights to the normal current-street solve. The conditioning
tree preserves observed prior-street sizes but uses one downstream bet size and
no unobserved raises so it remains inside the same memory ceiling. Its model,
reach, active hands, exploitability, and memory are returned as evidence. Other
histories retain the selected starting OOP/IP ranges, and
`POKER_POSTFLOP_SOLVER_RANGE_MODE=configured`
disables contextual selection entirely. The adapter returns the selected range
source and policy context in recommendation evidence; configured starting
ranges can still be conditioned by a complete reviewed line.

The plugin and its combined work are distributed under AGPL-3.0-or-later. See
the upstream repository and `Cargo.lock` for dependency details.

The Rust stdin contract does not currently consume Poker Hero's schema-v5
grading-reference structural, economic, or utility configuration. The backend
therefore rejects schema-v5 benchmark cases for `local_solver` before launching
this binary. Adding JSON fields without using them is insufficient: future
mastery-gradeable routing must consume the complete context and expose an
immutable configured binding that the benchmark verifies and records.
