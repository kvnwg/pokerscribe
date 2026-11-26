# Slumbot benchmark

Plays heads-up no-limit hold'em against Slumbot (https://slumbot.com) through its public bot API,
logs every hand, and reports the win rate in bb/100 with its standard error. Slumbot's 2018 version
won the Annual Computer Poker Competition (ACPC). The site doesn't say which version it runs now.

Nothing in `app/` imports this package. Bot B0 is only a stub here: it gets wired up once
`tools/simulate.py` has a heads-up mode.

## Terms and permission (read 26 Nov 2026)

- **Bots are invited.** The API page says: "Slumbot now offers an API so that researchers and
  hobbyists can test their bots against Slumbot." The site provides `sample_api.py`, a check/call
  bot, as a starting point.
- **There is no terms-of-service page.** `/terms`, `/tos`, `/terms-of-service`, `/privacy` and
  `/robots.txt` all return 404. The API page and the Help page set no rate limits, no hand caps
  and no other usage rules.
- **No money is involved.** Play is free with chips that reset every hand.
- **Rule 4** (`docs/research/README.md`) allows this: the operator offers this environment for
  exactly this use. There is no real money and no evasion: the client sends an honest
  `User-Agent`, plays one hand at a time, and uses only the documented API, never the web UI.
- **Our own limits.** By default the client sends at most one request a second (it never goes
  below 0.2 s between requests). It backs off exponentially on network errors, HTTP 429 and 5xx,
  and follows `Retry-After`. Run one session at a time.
- **Logging in** is optional. It only matters for Slumbot's leaderboards, and the account must be
  registered on the website first.

## The API in brief

Each request is an HTTPS POST to `https://slumbot.com/slumbot/api/<endpoint>` with a JSON body and
`Content-Type: application/json`.

| Endpoint | Body | Reply |
| --- | --- | --- |
| `login` | `{"username", "password"}` | `{"token"}` |
| `new_hand` | `{"token"}`, or `{}` on the very first request | the hand state, plus a token on the first reply |
| `act` | `{"token", "incr"}` | the hand state after our action and Slumbot's reply |

- **The hand state** has `old_action`, `action`, `client_pos`, `hole_cards` and `board`.
- **At the end of a hand** it also has:
  - `winnings`: our chips won or lost.
  - `baseline_winnings`: our result minus what Slumbot made playing itself with our cards in our
    seat. This is a luck-reduced measure.
  - `bot_hole_cards`: after a showdown only.
  - `won_pot`, `session_num_hands`, `session_total` and `session_baseline_total`.
- **Errors** come back as `{"error_msg"}` with HTTP 200, for example "Bet size too small".
- **The token** can change during a session, so the client always uses the latest one it got. In
  practice only the first reply carries one.

### Rules and the action string

- **Blinds and stacks.** Blinds are 50 and 100 and both stacks are 20,000 chips (200 bb). Stacks
  reset after every hand.
- **Seats.** `client_pos` 0 is the big blind: second to act preflop, first on every later street.
  `client_pos` 1 is the small blind, which is also the button. A session starts with us in the big
  blind and then alternates, so play an even number of hands.
- **Action codes.** `k` check, `c` call, `f` fold, `b<n>` bet or raise, and `/` ends a street. A
  limp from the small blind is `c`.
- **Bet sizes.** `<n>` is the bettor's total on that street only, blinds included preflop. In
  `b200c/kb400` the small blind raises to 200 and the big blind calls. On the flop the big blind
  checks and the small blind bets 400 into the 400 pot.
- **Minimum bet.** A bet or raise adds at least the previous bet or raise on the street, and at
  least 100. A player can always go all-in for less.
- **All-in.** After an all-in is called, the remaining streets are empty: `b20000c///`.

`protocol.parse_action` turns the string into an `ActionHistory`. That holds the actions by street
(seat, kind, street total, chips added, hand total, all-in), whose turn it is, the pot, what each
seat has put in, the amount to call, and the legal raise range. It rejects every string that
Slumbot's reference parser rejects.

## Use

From the repo root:

```bash
python -m tools.slumbot play --hands 200 --log docs/research/runs/slumbot/my_run.jsonl --bot checkcall
```

```bash
python -m tools.slumbot play --hands 1000 --log docs/research/runs/slumbot/my_run.jsonl --resume
```

```bash
python -m tools.slumbot stats docs/research/runs/slumbot/my_run.jsonl
```

- `--hands` is the total number of hands for the log. With `--resume`, play continues until the
  log holds that many.
- `--login` reads `SLUMBOT_USERNAME` and `SLUMBOT_PASSWORD`, or asks for them. The password is
  never stored.
- `--min-interval` sets the time between requests (1.0 s by default).

## Files

| File | What |
| --- | --- |
| `protocol.py` | Slumbot's rules, the action-string parser, results from a history |
| `client.py` | `SlumbotClient`: login, new hand, act; rate limiting and retries (standard library only) |
| `bots.py` | `Bot`, `BotState` (chips and big blinds), `Decision`, `CheckCallBot`, the `B0Bot` stub |
| `session.py` | the hand loop, the JSONL log, resuming, bb/100 with standard error |
| `tests/` | the tests, and `recorded_hands.jsonl` (33 real hands from the first run, one per distinct action string) |

### The hand log

The log is one JSON object per line. A `session` line is written at every start or resume. Every
finished hand gets a `hand` line with:

- the seat and position, our cards, Slumbot's cards and the board;
- the raw `action` string, and the parsed history by street, both as text and as structured data;
- every decision we made, with the string it was made against;
- Slumbot's `winnings` and `baseline_winnings`;
- our own recomputation of the result from the cards and the history (`check`: `ok`, `mismatch`,
  or `unchecked` when Slumbot's cards weren't shown).

A hand that couldn't be finished gets an `aborted` line and isn't counted in the stats. This
happens when the server rejects an action, or when a retried request turns out to have gone
through already (the reply's `old_action` shows it). The session stops after three aborted hands
in a row. `note` lines record a hand cut off by a restart, a half-written line dropped after a
crash, and a refused token being replaced.

The API token is kept in `<log>.state.json` next to the log, never in the log itself. Git ignores
it. Don't share it.

### The stats

- **bb/100** is the mean result per hand in big blinds, times 100. The standard error is the
  per-hand standard deviation divided by the square root of the number of hands, the same way
  `tools/simulate.py` computes it.
- **Baseline bb/100** uses Slumbot's `baseline_winnings`. It cancels the luck of the cards when
  our play is close to Slumbot's own. A bot that plays very differently reaches pots Slumbot
  wouldn't, so the baseline can then be noisier than the raw number. In the check/call run its
  standard error was higher. Report both.
- **Breakdowns** by seat are reported too.

## First run

On 26 Nov 2026 the check/call bot played 200 hands: -257.8 ± 83.5 bb/100, or -206.5 ± 88.8 on the
baseline. All 200 results matched our recomputation. The log is
`docs/research/runs/slumbot/checkcall_200.jsonl`, and the details are in
`docs/research/experiments.md`. At the default pace a hand takes about 6 seconds.

## Wiring up B0 later

`B0Bot` raises `NotImplementedError` for now. Its docstring lists the steps:

1. Take `BotState.in_bb()`.
2. Build the simulator's heads-up `GameState` from it.
3. Call `advise` and map the advice to a `Decision`, clamped into `raise_bounds`.
4. When the advice isn't legal here, check or call instead, and count it.

Then run, for example, `--bot b0 --hands 10000`. That's an even number, so each seat is played
equally often.
