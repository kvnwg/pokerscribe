# GTO Wizard Benchmark

Plays heads-up no-limit hold'em against GTO Wizard AI through the GTO Wizard Benchmark API
(https://benchmark.gtowizard.com), logs every hand, and saves the luck-adjusted result GTO Wizard
computes: the AIVAT win rate in bb/100 and its standard error.

The game is the one Slumbot plays: blinds 50 and 100, 20,000 chips each (200 big blinds), stacks
reset every hand. So this package is built like `tools/slumbot` and reuses its parts: the same
`Bot` interface, the same action parser, the same hand log. A bot written for one plays the other
unchanged.

**No real hand has been played with this code yet.** There was no API key when it was written
(26 Nov 2026). Everything was tested against a local mock server. See "What isn't known yet" and
"The first real run" before trusting it with a 10,000-hand session.

## THE TERMS. READ THIS FIRST.

GTO Wizard's terms (https://benchmark.gtowizard.com/terms/, last updated 21 Feb 2026, read
26 Nov 2026). This is our summary, not legal advice. Read the page itself before the first run.

> ## THESE HANDS ARE NEVER TRAINING DATA.
>
> **Nothing played here may ever be used to train, tune or calibrate anything.** Not B0, not the
> `TUNING` dict, not a blueprint, not a solver's ranges or bet sizes, not an opponent model, not a
> value network, not a threshold picked "by looking at how the hands went". The terms forbid using
> benchmark data "to train, fine-tune, or calibrate" any AI or solver, and forbid querying the
> API to work out GTO Wizard AI's strategy.
>
> This is stricter than our own rule that recorded hands are observations, never labels. These
> hands are not even observations for the agent. They are an exam result and nothing else.

What that means in practice:

1. **Benchmarking only.** The benchmark is the final exam for a finished agent. Don't choose
   between settings, bet sizes or agent versions by their GTO Wizard score: that is tuning on the
   benchmark by another name. Versions are chosen by the rules in `docs/research/README.md`
   (paired simulation, local best response), then the winner sits the exam.
2. **Keep the data fenced off.** Every line this tool writes carries
   `"source": "gtowizard_benchmark"` and `"use": "benchmark_only"`, and every session line carries
   the notice in full. Any script that builds a dataset must skip such lines. Don't copy these
   hands into `tools/phh`, into answer keys, into reference spots or into regression tests.
3. **No human help during hands.** The bot plays every decision alone. The runner never reads the
   keyboard and has no way to enter an action by hand. If the bot can't play a hand, the runner
   finishes it by rule (see "When the bot can't play a hand") and stops; the fix happens between
   hands. Don't stop a session mid-hand to change the bot and resume.
4. **Results are public.** GTO Wizard may publish the bot's name, organization, rank, results and
   every hand, for good, and may use our play to improve their AI. A bot appears on the
   leaderboard after one hand. **There are no practice hands**: the first smoke test counts.
5. **The key is ours alone.** No sharing, no public repository, no client-side code. It can be
   revoked at any time.
6. **Be light on their servers.** No working around rate limits. This runner plays one hand at a
   time, paces its requests, and stops when the server says no.

`play` refuses to start without `--accept-terms`.

## Getting access

There is no key yet. To request one:

1. Open https://benchmark.gtowizard.com and press "Evaluate Your Model". The form asks for:
   - an email address;
   - an organization (up to 64 characters; hobbyists on the leaderboard mostly write "Individual");
   - a bot name (up to 64 characters). **It is public and permanent**, so choose it for the real
     agent, not for a test;
   - an API key. The API's spec has you choose it yourself, 32 to 256 characters. (The site's FAQ
     says approved users get the key by email. Whichever happens, the key that works is the one
     confirmed in their reply.)
   - a reason for joining (up to 2,000 characters).
2. Make the key on the Mac without it touching the screen or a file. This puts 64 random
   characters on the clipboard:

   ```bash
   python3 -c "import secrets; print(secrets.token_urlsafe(48), end='')" | pbcopy
   ```

   Paste it into the form, then store it in the macOS Keychain (the command asks for the
   password: paste again):

   ```bash
   security add-generic-password -a "$USER" -s gtowizard-benchmark -w
   ```

   Then clear the clipboard:

   ```bash
   pbcopy < /dev/null
   ```

3. Wait for GTO Wizard's review and their email.

A draft for the "reason" box, to edit:

> PokerScribe is a one-person research project building a solver-based heads-up no-limit hold'em
> agent (a blueprint with depth-limited search, after Modicum). I'd like to measure it against
> GTO Wizard AI on the benchmark. Benchmark use only: the hands will not be used to train, tune
> or calibrate anything.

Something to decide before sending the form: every hand is public under the bot's name, the
harness test included. A few check/call hands under the real name will stay in its record. The
leaderboard shows organizations with several bots (Vrije Universiteit has three, MIT two), so a
second name for harness tests looks possible, each with its own request. Whether GTO Wizard
is happy with that is a question for them.

## The key

The key is read from the environment variable `GTOWIZARD_API_KEY`, and from nowhere else. There
is no `--key` option on purpose: a key on the command line ends up in the shell history. In each
terminal, before a run:

```bash
export GTOWIZARD_API_KEY="$(security find-generic-password -a "$USER" -s gtowizard-benchmark -w)"
```

The client sends the key in the `X-API-Key` header only. It never writes it to the hand log, the
ledger, the state file, the results file, an error message or the terminal. It cuts the key out
of any text the server sends back before showing it, refuses plain http (except to the mock on
this machine), and does not follow redirects. Never commit the key and never paste it into a
chat.

## Use

From the repo root. Check the key and the caps first (four small requests, no hand):

```bash
python -m tools.gtowizard limits
```

Play. `--hands` is the total wanted in the log:

```bash
python -m tools.gtowizard play --hands 1000 --log docs/research/runs/gtowizard/my_run.jsonl --bot checkcall --accept-terms
```

Continue the same log after a stop or a crash:

```bash
python -m tools.gtowizard play --hands 1000 --log docs/research/runs/gtowizard/my_run.jsonl --bot checkcall --accept-terms --resume
```

Fetch GTO Wizard's results again later and save them with the log:

```bash
python -m tools.gtowizard results docs/research/runs/gtowizard/my_run.jsonl
```

Summarise a log without any request:

```bash
python -m tools.gtowizard stats docs/research/runs/gtowizard/my_run.jsonl
```

Options for `play`:

- `--bot`: any bot in `tools/slumbot/bots.py` (`BOTS`). Today that is `checkcall`; `b0` is still
  a stub.
- `--min-interval`: seconds between requests (0.5 by default, never below 0.1). A check/call hand
  is about five requests, so at least 2.5 seconds a hand, and 10,000 hands take 7 hours or more
  before any thinking time.
- `--day-cap`, `--week-cap`, `--month-cap`: lower the caps for this run. They can't be raised.
- `--ledger`: the file that counts hands (see "The caps").
- `--url`: another address, for the mock.

`play` exits with 0 when the log holds the hands asked for, and 1 when it stopped early, with
the reason printed.

### Trying it without a key

The mock server stands in for the API on this machine:

```bash
python -m tools.gtowizard mock --port 8765
```

In a second terminal (any text works as the key there):

```bash
GTOWIZARD_API_KEY=any-text python -m tools.gtowizard play --url http://127.0.0.1:8765 --hands 20 --log /tmp/mock.jsonl --ledger /tmp/mock_ledger.jsonl --bot checkcall --accept-terms
```

The mock's opponent plays at random and its AIVAT numbers are made up. Its logs are marked
`"mock": true` and the summary says so. Give it its own `--ledger`, so mock hands don't count
against the real caps.

## What the runner does

### The hand loop

1. Ask for a hand (`POST /hands`). The reply already holds GTO Wizard AI's first action when it
   acts first.
2. Read the state, check it against our own parse of the action history, and hand the bot a
   `BotState`. Send the bot's decision (`POST /hands/{id}/act`). Repeat until the hand is over.
3. Write the hand to the log, with `winnings` and `aivat_score`.

The server is the judge of what is legal: the bot gets the server's `legal_actions` and
`raise_range`. A bet or raise names the total for the betting round, as in Slumbot's `b<n>`.

### Resuming

The server keeps unfinished hands (`GET /hands/in-progress`). Every session starts by finishing
those, whoever left them, before dealing new ones. A hand cut off by a crash or Ctrl-C is played
to the end by the bot on the next run and logged with `"resumed": true`. A line the crash cut in
half is dropped from the log. Nobody knows yet what the server does with a hand left open for a
long time, so resume soon.

### Replies lost on the way

When a request gets no usable answer (a timeout, a dropped connection, a 502, 503 or 504), the
server may or may not have applied it. Sending "check" again could then check the next street as
well. So an action is never blindly re-sent: the runner looks the hand up in
`/hands/in-progress`. An unchanged action history means the action wasn't applied, and it is
sent again after a pause. A longer one means it was, and play carries on from there. If the hand
is gone, the action ended it and the result never reached us: the log gets a `lost` line. The
hand still counts at GTO Wizard and towards the caps. It is left out of the log's own numbers.

The same goes for a new-hand request without an answer: the runner looks for the hand that may
have been dealt and plays it, so no hand is left behind.

### When the bot can't play a hand

If the bot raises an error, returns an illegal action, has its action refused by the server, or
if a reply disagrees with our own reading of the hand (whose turn, the pot, check or call), the
runner does not guess and does not ask anyone. It finishes that hand by rule: check when checking
is free, fold otherwise. The hand is logged with the reason in `fallback`, and the session stops
after it. Fix the cause, then `--resume`.

### The caps

GTO Wizard's limits, per user and per game (FAQ read 26 Nov 2026; they "may change at any time"):

| Window | Hands | Resets |
| --- | --- | --- |
| Day | 10,000 | midnight UTC |
| Week | 25,000 | Monday, midnight UTC |
| Month | 50,000 | the 1st, midnight UTC |

Before every new hand the runner checks all three and never starts a hand that would go over. It
stops and says when the cap resets. Hands already open are still finished: they were counted
when they were dealt.

Two counts are used, and the larger one wins:

- **The ledger**: a local file with one line per hand started (time and hand id, nothing else),
  shared by every session on this machine whatever log they write. By default it is
  `gtowizard_ledger.jsonl` in PokerScribe's data folder
  (`~/Library/Application Support/PokerScribe/`); `--ledger` or `GTOWIZARD_LEDGER` moves it.
- **The server's count**: `total_hands` from `GET /results` since the start of the day, week and
  month, fetched when a session starts. It covers hands played from another machine or with
  another tool.

If GTO Wizard raises its limits, change `PUBLISHED` in `limits.py`, with the date. If they lower
them, the server's refusal (a 429) stops the session cleanly; then lower `PUBLISHED`.

With two keys (say a test bot and the real one), give each its own `--ledger`.

### Pace and politeness

One hand at a time, one request at a time, at most one request per `--min-interval`. A 429 is
waited out a few times when the server names a short wait (`Retry-After`), and ends the session
when the wait is long or the 429 keeps coming. The API allows up to 20 hands at once (a comment
in GTO Wizard's own client, dated 9 Apr 2026). This runner doesn't use that.

## The results

### The naming trap

The API calls the standard error of the AIVAT win rate `aivat_std_bb_per_100`. Its own
description says it is a standard error and that the old name is kept for compatibility. This
tool saves it as `aivat_standard_error_bb_per_100`, next to the API's object as it came.

### What is saved

After every session, and with the `results` command, the runner asks `GET /results` twice and
saves both answers as a `results` line in the log and in `<log>.results.json`:

- `all_time`: everything played under the key. This is what the leaderboard shows.
- `this_log`: hands since this log's first session. That is this log's own result as long as
  nothing else was played with the key in that time. `matches_log` says whether the server's
  hand count for the window equals the log's.

Each has `hands`, `aivat_bb_per_100`, `aivat_standard_error_bb_per_100`, `aivat_ci95_bb_per_100`
(win rate ± 1.96 standard errors; the leaderboard ranks by the lower end), `raw_bb_per_100`, and
`api`, the server's object untouched (with the chance and action corrections).

The log also has GTO Wizard's `aivat_score` for every hand, in chips. `stats` computes the log's
own AIVAT bb/100 and standard error from those, the same way `tools/simulate.py` does, and prints
them beside the server's figures. The two should agree.

Only GTO Wizard can compute AIVAT: it needs GTO Wizard AI's strategy.

### How many hands

From `docs/research/BENCHMARKS.md`: on the leaderboard of 26 Nov 2026 a standard error of
2 bb/100 took about 16,000 hands and 1 bb/100 about 64,000. One month's cap of 50,000 hands
gives about 1.1 bb/100.

### Writing a run up

A benchmark run goes in `docs/research/experiments.md` like any other run: the command, the
hands, the AIVAT win rate and its standard error, the date. That is reporting an exam result. It
is not a reason to change the agent (see the terms above).

## The hand log

One JSON object per line. Every line has `"source": "gtowizard_benchmark"` and
`"use": "benchmark_only"`.

- `session`: written at every start or resume. The bot, the rules, the address, the caps, hands
  used and left, how many open hands were found, and the terms notice.
- `hand`: a finished hand.
  - `hand_id`, our seat and position, our cards, GTO Wizard AI's cards (after a showdown, if the
    server shows them) and the board;
  - `action_history` as the server sent it, the same history as a Slumbot string (`action`), by
    street as text (`streets`) and as structured data (`history`);
  - `decisions`: each action we sent and the history it was sent against, with `"fallback": true`
    on those played by rule;
  - `winnings` (chips) and `aivat_score` (chips, luck-adjusted, from GTO Wizard);
  - `check`: our own recomputation of the result from the cards and the history: `ok`,
    `mismatch`, `unchecked` (cards not shown) or `unreadable`;
  - `resumed`, `fallback` (the reason, or null), `notes` (differences between the server's rules
    and ours), `postflop_first`, and `game_state`, the final state exactly as the server sent it.
- `lost`: a hand that ended on the server without its result reaching us, with the actions sent
  and the one whose reply never came (`unanswered`).
- `results`: see above.
- `note`: a cut line dropped, an unanswered new-hand request, the betting order, a stop.

`<log>.state.json` only remembers which hand was open. It holds no secret and git ignores it.

A hand line is about 2 KB, so 50,000 hands are about 100 MB. Commit the small
`<log>.results.json`; keep big hand logs out of git.

## What isn't known yet

The public spec (https://researcher.gtowizard.com/openapi.json, copy in
`docs/research/runs/benchmarks_2026-11-26/`) gives the shapes. It leaves these open. The code is
written to cope either way, and the mock server takes the guess named here.

| Open question | What the code does |
| --- | --- |
| Who acts first after the flop. Standard heads-up rules and the ACPC rules the benchmark cites say the big blind. The benchmark paper's own rules text (arXiv 2603.23660, appendix) says the small blind acts first on every round | Starts with the big blind. The first decision after a flop settles it: only one order makes it our turn. If it is the other one, the runner switches, writes a `betting_order` note and prints it. If so, tell the solver work: it would be a different game from the one the blueprint assumes |
| Status codes: a refused key, an illegal action, an unknown hand, a cap or rate limit | 401 and 403 stop the session. Any other 4xx on an action leads to the check-or-fold rule and a stop. 429 is treated as a limit. 502, 503 and 504 are "engine busy", as in GTO Wizard's client |
| What `/results` says before any hand | A 404 and an object of zeros are both read as "nothing yet" |
| Whether `start_date` filters by a hand's start or end | Used for the server's cap count and the `this_log` window. `limits` shows the count, and `matches_log` flags a window that doesn't fit. If the server refuses the question, the ledger alone is used and a note says so |
| Position names | "SB" and "BB" as in the paper's prompt; "small blind", "big blind" and the button's names are read too |
| The units of the `game` block (blinds, starting stack) | Expected as 50, 100 and 20,000 chips. Anything else is written in the hand's `notes`, and play goes on: a hand that really ran on other rules would fail the pot check |
| The order of `players` and their names | We are the player whose hole cards are shown |
| Whether GTO Wizard AI's cards are shown after a showdown, and how hidden cards look | If they are shown, the result is recomputed (`check`); if not, `unchecked`. Null, empty or masked cards all read as hidden |
| Whether `_` is written after a fold, an all-in call or the last river action | Read with or without |
| Whether a reply can come back while GTO Wizard AI is still to act | The hand is looked up again a few times, then the session stops and leaves it open |
| What happens to a hand left open for hours | Unknown. Resume soon |
| Request rate limits | None published. We pace ourselves and obey 429 |
| The exact minimum-raise rule | The server's `raise_range` is used. A difference from our parser's is written in the hand's `notes` |

The mock server reuses the Slumbot parser for its rules, so it can't reveal a rules mistake that
the client shares. Only a real run can.

## The first real run

Every hand is public and counts. Keep the first run tiny and look before going on.

1. `python -m tools.gtowizard limits`. It proves the key works and shows the server's hand count.
2. Play 2 hands with `--bot checkcall` (one in each seat), under the name chosen for tests.
3. `python -m tools.gtowizard stats <log>`. Both result checks should say `ok` (or `unchecked`
   if the cards aren't shown).
4. Open the log. Look for `note` lines, for `notes` and `fallback` on the hands, and at
   `postflop_first`. Compare `game_state` with the table above and correct this README.
5. Run `limits` again: the server's count should have grown by 2. If it hasn't, the server's
   count can't be relied on and the ledger carries the caps alone.
6. Then 20 hands, then a real session.

## Files

| File | What |
| --- | --- |
| `protocol.py` | Reads the server's game state into the Slumbot tools' `BotState`; checks it against our own parse; settles the betting order |
| `client.py` | `GTOWizardClient`: the four endpoints, the key, pacing, errors (standard library only) |
| `limits.py` | The caps, the UTC windows, the ledger |
| `session.py` | The hand loop, resuming, lost replies, the check-or-fold rule, the log, results and stats |
| `mock_server.py` | The local stand-in for the API, with knobs for errors, rate limits and caps |
| `tests/` | The tests, against the mock over real HTTP on 127.0.0.1. Nothing in them can reach the real API |

`tools/slumbot/protocol.py` gained two optional arguments for this package: who acts first after
the flop (`parse_action(..., postflop_first=...)`) and the opponent's name in the per-street
text. Slumbot's behaviour is unchanged.

## Wiring up a real agent

The interface is `tools.slumbot.bots.Bot`: implement `act(state) -> Decision`, add the class to
`BOTS`, and it plays both benchmarks. `state.raise_bounds`, `state.legal()` and
`state.is_legal()` answer from GTO Wizard's server here. A bot that keeps notes during a hand
gets `start_hand` at its first decision. On a resumed hand that is in the middle of the hand,
with the whole history in `state.history`.

Decide slowly if needed: the client waits up to 180 seconds for a reply, and nothing published
limits thinking time between requests.
