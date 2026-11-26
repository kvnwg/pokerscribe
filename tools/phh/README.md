# PHH pipeline

Turns the University of Toronto Poker Hand History dataset
(https://github.com/uoftcprg/phh-dataset, MIT licence) into decision-point records.
It is separate from the app: nothing in `app/` imports it.

## Run

```
pip install -r tools/phh/requirements.txt
git clone --depth 1 https://github.com/uoftcprg/phh-dataset /path/to/phh-dataset   # about 17 GB
python -m tools.phh.build --root /path/to/phh-dataset --out /path/to/output --handhq-share 0.01 --workers 4
python -m tools.phh.report --stats /path/to/output/stats.json --out docs/research/DATASET.md
```

`--handhq-share 1` processes all 21.6 million HandHQ hands (about 10 hours on 2 cores, 4 GB of output).
Every Pluribus, WSOP and historical hand is always processed.

## Output

| File | What |
| --- | --- |
| `pluribus/decisions.parquet` | the 10,000 Pluribus hands, kept apart, with a `split` column (by day) |
| `handhq/train.parquet`, `validation.parquet`, `test.parquet` | HandHQ, split by site, stake and day |
| `evaluation/wsop.parquet`, `evaluation/historical.parquet` | Hold'em hands from the WSOP final table and the famous hands |
| `stats.json` | counts, drop reasons, duplicates, leak-check results |

One row per decision. Features (only what the acting player could see): `n_players`, `n_active`,
`street`, `position`, `seat`, `actor_id` (pseudonym), `actor_is_pluribus`, `opponents`
(position=pseudonym of everyone still in), `hole_cards` (own cards, or null when the log hides them),
`board` (cards dealt so far), `bb`, `pot_bb`, `to_call_bb`, `stack_bb`, `bet_bb`, `eff_stack_bb`
(null when stacks are unknown), `history` (every earlier action as `street:position:action+amount`),
`can_fold`, `can_check`, `can_call`, `can_raise`, `min_raise_to_bb`, `max_raise_to_bb`.
Label: `action`, `amount_to_bb`, `amount_added_bb`, `size_of_pot`, `all_in`, `label_source = observed`.
Bookkeeping: `hand_uid`, `source`, `venue`, `stakes`, `session`, `split`, `file`, `hand_index`.

## Guarantees

- No leakage: `replay.leak_check` rebuilds decisions from a copy of the hand cut off at the decision,
  with other players' cards hidden and results removed, and compares every feature.
- Hands with a missing action are dropped whole, never repaired by guessing.
- Duplicates: same site hand number (the copy showing more cards wins) or identical content.
- Observed actions are labelled as observed. They are data about behaviour, not correct play.
- Raw player names never reach the output.

## Code

`reader.py` (files to hands), `replay.py` (PokerKit replay to decision points, leak check),
`sources.py` (sources, sessions, splits, pseudonyms, duplicate keys), `build.py` (parallel build),
`report.py` (markdown report). Tests: `app/tests/test_phh_pipeline.py`.
