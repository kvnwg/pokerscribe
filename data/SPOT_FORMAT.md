# SPOT and RESULT formats

The answer keys that the PokerScribe solvers (the Python river solver in `app/solver`, and
the Rust river and turn solver to come) are checked against. A SPOT is a postflop decision
to solve; a RESULT is one solver's answer to it.

Both formats use the conventions of `app/solver` (`docs/research/SOLVER.md`,
"Conventions"), so a river SPOT is a `RiverSpot` and a river RESULT node reads like a
solver label from `app/solver/labels.py`. The turn adds only what the river doesn't need:
a fourth board card in place of the fifth, river bet sizes, and the river card in node keys.

Code: `tools/answer_keys/spots.py` (read, check, tree), `tools/answer_keys/result.py`
(RESULT). Tests: `app/tests/test_answer_keys.py`.

## Conventions

- Player 0 is out of position (`"oop"`), player 1 is in position (`"ip"`). OOP acts first
  on every street.
- Amounts are chips. In this repo every pot is 100, so an amount is also a percent of the
  starting pot.
- Cards are a rank (`23456789TJQKA`) and a suit (`cdhs`): `"Ah"`, `"Td"`.
- A combo is two cards written as one string, higher rank first, then by suit in the order
  s, h, d, c: `"AhKd"`, `"QsQh"`, `"KhQs"`. `app.solver.spot.parse_combo` and
  `combo_text` give the canonical spelling.

## SPOT

One JSON file per spot, `data/answer_keys/spots/<id>.json`. They are built from
`tools/answer_keys/spot_defs.py` with `python -m tools.answer_keys make-spots`: edit the
definitions, not the JSON.

```json
{
  "format": "pokerscribe-spot",
  "version": 1,
  "id": "r05",
  "street": "river",
  "title": "Dry K72-94, polar IP with two sizes and a raise size",
  "tags": ["dry", "polar", "condensed", "raise-size"],
  "board": ["Ks", "7d", "2c", "4h", "9s"],
  "pot": 100,
  "stacks": [300, 300],
  "spr": 3.0,
  "max_raises": 3,
  "sizes": {
    "oop": {"bets": [0.5], "raises": [0.5], "allin": true},
    "ip": {"bets": [0.33, 1.0], "raises": [0.5], "allin": true}
  },
  "range_text": {"oop": "QQ-TT,88,KQo,...", "ip": "AK,KK:0.5,99:0.5,..."},
  "ranges": {"oop": {"TsTh": 1.0, "...": 1.0}, "ip": {"AsKh": 1.0, "...": 0.5}},
  "expected": [{"nodes": "^x$", "actor": "ip", "action": "x", "min": 0.98, "why": "..."}]
}
```

| Field | Meaning |
| --- | --- |
| `format`, `version` | Always `"pokerscribe-spot"`, `1`. |
| `id` | `r01` to `r30` for river spots, `t01` to `t10` for turn spots. The file name. |
| `street` | `"river"` or `"turn"`: the street the spot starts on. |
| `title`, `tags` | For people. Tags used: `trivial`, `dry`, `wet`, `paired`, `four-flush`, `polar`, `condensed`, `wide`, `low-spr`, `overbet`, `raise-size`, `reraise`, `three-sizes`. |
| `board` | 5 cards for a river spot, 4 for a turn spot. |
| `pot` | Chips in the middle when the spot starts. |
| `stacks` | Chips behind for `[oop, ip]` when the spot starts. Only the smaller one matters. |
| `spr` | `min(stacks) / pot`, rounded to 2 places. Informative only. |
| `max_raises` | Raises allowed after the first bet, on each street (0: bet, then only call or fold). 3 in every spot in this repo, because TexasSolver always allows 3 and can't be told otherwise. |
| `sizes` | Bet and raise sizes for each player: the river's for a river spot, the turn's for a turn spot. `app.solver.BetSizes.to_dict()`. |
| `river_sizes` | Turn spots only: the river's sizes, same layout. |
| `range_text` | The ranges as written: items separated by commas, each `app/poker/ranges.py` notation with an optional `:weight`. |
| `ranges` | The ranges as `{combo: weight}`, built from `range_text`. **This is the range**; `range_text` must expand to exactly it. |
| `expected` | Optional. Checks any correct answer must pass (the trivial spots have them; see below). |

A river spot is read as it is by `RiverSpot.from_dict` (it ignores the extra fields).

### Ranges

- Weights are over 0 and at most 1. Combos with weight 0 aren't listed.
- No combo uses a board card. For a turn spot, combos that use the river card are dropped
  from that river branch only: they are in `ranges`, and absent from the RESULT nodes
  after that card.
- The two ranges may share cards. Deals where they clash get no weight (exact card
  removal), as in `app/solver`.
- In this repo every range is made of whole hand classes (every live combo of `AKs`, all
  with the same weight), because TexasSolver reads ranges by class. The format itself
  allows any combos.

### Sizes

The same rules as `app/solver/tree.py`:

- A bet is a share of the pot at the start of the street: `0.5` with pot 100 is a bet of 50.
- A raise is a share of the pot after calling, added on top of the call: facing a bet of 50
  into 100, a raise of `0.5` is to `50 + 0.5 * (100 + 2 * 50) = 150`.
- A raise is at least the size of the bet or raise it answers, unless it is all in.
- Sizes at or over the effective stack become all in, and equal amounts are offered once.
  With `allin: true` going all in is always one of the choices.
- Amounts are rounded to 2 decimal places.

The spots in this repo are also chosen so that the edge cases stay simple: the min-raise
rule never binds (raise sizes are at least 0.5), no first bet of a spot is already all in,
and every amount is a whole number of chips. `make-spots` refuses a spot that breaks this.
Later sizes can reach the stack (three raises a street run out of chips quickly); they
become the all-in, and TexasSolver caps and merges them the same way. Every TexasSolver
solve rebuilds its tree and compares it node by node with the spot's, so a difference in
these rules can't slip into a key.

### Node keys

A node is keyed by the actions that lead to it, separated by single spaces. `""` is the
start of the spot.

| Token | Meaning |
| --- | --- |
| `x` | check |
| `b50` | bet: the player has now put in 50 on this street |
| `r150` | raise: the player has now put in 150 on this street ("raise to 150") |
| `c` | call |
| `f` | fold |
| `7h` | the river card (turn spots only) |

Amounts are what that player has put in **on the current street**, so they start again
from 0 on the river. Amounts are printed without trailing zeros: `b50`, `b33.5`.

- River: `"x b75 r200 c"` is check, bet 75, raise to 200, call.
- Turn: `"x b50 c 7h b100"` is check, bet 50, call, the river is the 7h, OOP bets 100 into
  the pot of 200.

A street ends with a call, or with a check by IP or by the second player to check. After a
call that puts a player all in, or a fold, the hand has no more decisions. Otherwise a turn
spot deals each of the 48 cards left (in the order 2c 2d 2h 2s 3c ... As) and the river
starts with OOP to act, with pot `pot + 2 * called` and stack `stack - called`.

At each node the actions are in this order: `x`, then bets from smallest to largest; or
`f`, `c`, then raises from smallest to largest. `spots.decision_nodes(spot)` gives every
decision node with its actor and actions; for a river spot it is exactly
`app.solver.GameTree`.

### Expected checks

Each check applies to every node whose key matches the regular expression `nodes`
(Python `re.search`) and whose actor is `actor` (`"oop"`, `"ip"` or `"any"`). For every
combo there, the total probability of the actions of kind `action` must be at least `min`
and/or at most `max`. Kinds: `x`, `c`, `f`, `b` (any bet), `r` (any raise). `why` says why
the answer is obvious.

Write checks only for nodes the acting player always reaches by their own choices.
Elsewhere a correct solver may leave any strategy (a node nobody plays to has no right
answer), which is why r03 checks only IP facing the first bet.

## RESULT

One file per solved spot, JSON Lines: `data/answer_keys/<solver>/<id>.jsonl`, or
`<id>.jsonl.gz` (gzip) when it is over 1 MB. Line 1 is the header, and every other line
is one decision node.

Header:

```json
{"format": "pokerscribe-answer-key", "version": 1, "kind": "header", "label_source": "solver",
 "spot_id": "r05", "spot_sha256": "9f2c...", "street": "river",
 "solver": {"name": "TexasSolver", "version": "console@02c8021", "binary_sha256": "...",
            "settings": {"accuracy_pct_of_pot": 0.3, "max_iterations": 5000, "print_interval": 10,
                         "threads": 4, "use_isomorphism": 0, "allin_threshold": 1000,
                         "raise_limit": 3, "dump_rounds": 1},
            "iterations": 120, "elapsed_s": 3.2, "exploitability_pot": 0.0027,
            "exploitability_trace": [[0, 61.2], [10, 4.1]], "converged": true,
            "reading": "by", "notes": []},
 "checks": {"exploitability_pot": 0.0026, "filled_rows": 0, "expected_failures": []},
 "nodes": 18, "created": "2026-11-26T12:00:00Z"}
```

| Field | Meaning |
| --- | --- |
| `spot_sha256` | sha256 of the spot file's canonical JSON (keys sorted, no spaces): `spots.spot_hash`. A result belongs to exactly that spot; if the spot changes, it must be solved again. |
| `solver.exploitability_pot` | The solver's own exploitability at the end, as a share of the starting pot (0.003 = 0.3%). |
| `solver.exploitability_trace` | `[iteration, percent of the pot]` as the solver printed it. |
| `solver.converged` | The last exploitability is at or under the target. |
| `solver.reading`, `solver.notes` | How TexasSolver's amounts were read, and anything odd found reading its output (`data/answer_keys/README.md`, "Quirks"). |
| `checks.exploitability_pot` | River spots: exploitability of this answer worked out by `app/solver/exploitability.py`, independent of the solver. `null` for turn spots. |
| `checks.filled_rows` | Combos the solver left out at some node, given a uniform row for that check. |
| `checks.expected_failures` | The spot's expected checks that fail (always empty in a saved result). |

Node lines, in the order of `spots.decision_nodes`:

```json
{"kind": "node", "node": "x b33", "actor": "oop", "actions": ["f", "c", "r116", "r300"],
 "strategy": {"TsTh": {"f": 0.0, "c": 0.91, "r116": 0.09, "r300": 0.0}, "...": {}}}
```

- `node`, `actor`, `actions`: as in the spot's tree. A result has exactly the spot's
  decision nodes, with the same actions.
- `strategy`: every combo of the actor that can be dealt at that node (its range, less the
  river card on a turn spot), with one probability per action, adding up to 1. Rounded to
  6 decimal places.
- Values (EVs) aren't included: TexasSolver doesn't print them.

`label_source` is always `"solver"`. As with every label in this project, a RESULT is a
solver's answer, not a record of anyone's play (rule 3 in `docs/research/README.md`).

### Comparing a solver with a RESULT

A solver's answer can differ from the key and still be right: spots can have more than one
equilibrium. So the main test is exploitability (for river spots,
`checks.river_exploitability` on the new answer), then the expected checks, then closeness
to the key's action frequencies at the nodes both players reach often.
