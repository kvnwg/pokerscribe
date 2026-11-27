# abstraction: hand buckets for heads-up No-Limit Hold'em (Phase 5)

Heads-up No-Limit Hold'em has far too many hands to keep a strategy for each one. This crate
puts every hand (hole cards plus board) in a *bucket*, so that the blueprint solver of Phase 6
keeps one strategy per bucket, as Pluribus and Modicum do.

- Hands that differ only by the names of the suits are one hand (suit isomorphism).
- Preflop: all 169 classes, no grouping.
- Flop and turn: potential-aware buckets. A hand is described by where it lands on the next
  street (a histogram over the next street's buckets), and hands are grouped by k-means with
  earth mover's distance.
- River: a hand is described by its equity against the opponent's possible hands, as OCHS
  (opponent cluster hand strength, the default) or as one number, then k-means.
- The number of buckets on each street is a setting. Pluribus's blueprint used 200 on each
  postflop street.

Status, 27 Nov 2026: built and tested. Full tables were built on this machine at 50, 200, 500
and 1,000 buckets a street (times below). Nothing in the app or the solvers uses it yet. The
other parts of Phase 5 are other crates, added to `main` by other sessions while this one was
written: the action menu and mapping rule in `abstract_game`, the LBR exploiter in `lbr`.
This crate is not wired to them yet ("With the abstract game" below shows how), so the Phase 5
gate (LBR win rate against bucket count) has not been run.

The big tables are not in the repository. Build them with the command below. The repository
holds the code, and small test tables for a 20-card deck in `tests/fixtures/small`.

## Use

```bash
cd engine
```

```bash
cargo build --release -p abstraction
```

```bash
./target/release/abstraction-build build --out ~/abstraction/k200 --buckets 200
```

That builds `river.abs`, then `turn.abs`, then `flop.abs` in the directory, and appends one
line per table (times, memory, settings, checksum) to `build_log.jsonl` there. With 200 buckets
it takes about 7 minutes on 4 cores.

Each street can be built on its own, which keeps the peak memory to that street's:

```bash
./target/release/abstraction-build build --out ~/abstraction/k200 --buckets 200 --streets river
```

```bash
./target/release/abstraction-build build --out ~/abstraction/k200 --buckets 200 --streets turn
```

```bash
./target/release/abstraction-build build --out ~/abstraction/k200 --buckets 200 --streets flop
```

The turn reads `river.abs` from the directory and the flop reads `turn.abs`.

| Option | Meaning | Default |
| --- | --- | --- |
| `--out DIR` | Where the tables go. | required |
| `--buckets N` | Buckets on each street. | 200 |
| `--flop N`, `--turn N`, `--river N` | Buckets on one street. | |
| `--streets LIST` | Which tables to build, in order. | `river,turn,flop` |
| `--river-feature ochs` or `equity` | What describes a river hand. | `ochs` |
| `--opponent-clusters N` | Opponent groups for `ochs`. | 8 |
| `--turn-histogram buckets` or `equity` | What a turn hand's histogram is over: the river table's buckets, or equal slices of river equity. | `buckets` |
| `--equity-bins N` | Slices for `--turn-histogram equity`. | 50 |
| `--seed N` | The same seed and settings give the same tables. | 1 |
| `--max-iters N` | k-means iterations at most. | 50 |
| `--tolerance X` | Stop when under this share of the training hands change bucket. | 0.001 |
| `--restarts N` | k-means runs from different seeds; the best is kept. | 1 |
| `--river-train N`, `--turn-train N`, `--flop-train N` | Train the centres on N random hands (0: all of them). Every hand is then put in the bucket of its nearest centre. | 4,000,000, 2,000,000, 0 |
| `--river-init N`, `--turn-init N`, `--flop-init N` | Pick the first centres from N of the training hands (0: all). | 400,000, 200,000, 200,000 |
| `--ranks N` | Deck of the top N ranks. Smaller decks are for tests. | 13 |
| `--threads N` | Worker threads. | every core |

Set `ABSTRACTION_PROGRESS=1` to see every k-means iteration on standard error.

Other commands:

```bash
./target/release/abstraction-build info ~/abstraction/k200/river.abs
```

```bash
./target/release/abstraction-build check ~/abstraction/k200
```

```bash
./target/release/abstraction-build bucket ~/abstraction/k200 AhKh 9h8h2c
```

```bash
./target/release/abstraction-build stats ~/abstraction/k200
```

```bash
./target/release/abstraction-build gap ~/abstraction/k200 300
```

- `info` prints a table's header (all its settings), checks the checksum, and for an OCHS river
  table lists the opponent groups.
- `check` loads the three tables, verifies their checksums and runs the sanity checks of
  `src/checks.rs` on real hands (the nuts, air, draws). It exits with 1 if one fails.
- `bucket` prints the bucket of one hand: its number, its average equity and its size.
- `stats` measures how much of the hands' equity, and of how much that equity can still change
  on the next card, the buckets tell apart.
- `gap` measures the fast earth mover's distance against the exact one on random turn hands.

From Rust:

```rust
use abstraction::{parse_cards, Abstraction, Street};

let abstraction = Abstraction::load("/home/me/abstraction/k200".as_ref())?;
let hole = parse_cards("AhKh")?;
let board = parse_cards("9h8h2c")?;                 // 0, 3, 4 or 5 cards
let bucket = abstraction.bucket(&hole, &board);     // 0..abstraction.buckets(Street::Flop)
```

Cards are numbered as everywhere in the engine: `rank * 4 + suit`, rank 0 = 2 up to 12 = ace,
suit 0..3 = c, d, h, s. With no board cards the bucket is the preflop class, 0 to 168.
`Abstraction::load` checks the three checksums; `load_unchecked` skips that.

### With the abstract game

`abstract_game` (on `main`) takes its card abstraction through its `Bucketer` trait. This
crate does not depend on it: the branch was started before it existed, and it belongs to
another session. The adapter is short, and belongs in whichever crate first uses both (the
Phase 6 blueprint, say):

```rust
use abstract_game::{Bucketer, Card, Street};
use abstraction::Abstraction;

/// The built tables as the abstract game's card abstraction.
pub struct Buckets(pub Abstraction);

impl Bucketer for Buckets {
    fn num_buckets(&self, street: Street) -> u64 {
        let street = match street {
            Street::Preflop => abstraction::Street::Preflop,
            Street::Flop => abstraction::Street::Flop,
            Street::Turn => abstraction::Street::Turn,
            Street::River => abstraction::Street::River,
        };
        self.0.buckets(street) as u64
    }

    fn bucket(&self, hole: [Card; 2], board: &[Card]) -> u64 {
        self.0.bucket(&hole, board) as u64
    }
}
```

This was compiled and tested in a scratch copy of `main` as it was on 27 Nov 2026 (commit
`cac3c4c`), with the small tables of `tests/fixtures/small`. It is not compiled by this
crate's tests, so check it again if the trait has changed. In the same copy of `main` this
crate's own tests pass unchanged.

## Method

### 1. Suit isomorphism (`src/isomorphism.rs`)

`HandIndexer` gives every hand an index, the same for all hands that differ only by a
relabelling of the suits, and turns an index back into one hand of the class (the canonical
hand). It is Kevin Waugh's method ("A Fast and Optimal Hand Isomorphism Algorithm", 2013),
written from the paper. The board is a set: the order the cards came in is forgotten
(imperfect recall, as in Pluribus).

| Street | Deal | Canonical hands | Raw deals |
| --- | --- | --- | --- |
| Preflop | 2 | 169 | 1,326 |
| Flop | 2 + 3 | 1,286,792 | 25,989,600 |
| Turn | 2 + 4 | 13,960,050 | 305,377,800 |
| River | 2 + 5 | 123,156,254 | 2,809,475,760 |

`multiplicity(index)` is how many raw deals share an index (4 for suited hole cards, 6 for a
pair, 12 for offsuit). Every average and every k-means step weighs a canonical hand by it, so
the buckets are fitted to the real mix of deals.

### 2. Preflop

The 169 classes as they are. `Preflop` gives a class's number, its name ("AKs", "72o") and
its number of combinations.

### 3. River (`src/equity.rs`, `src/builder.rs`)

For one board of each of the 134,459 suit classes of boards, all 1,081 pairs of hole cards are
scored with the `eval` crate and sorted by strength once. One pass over the sorted list gives
every hand its wins and ties against all the hands the opponent can still hold (cards shared
with our hand are taken out). All 145 million hands take about 7 seconds on 4 cores.

- `--river-feature equity`: one number per hand, the equity against a random hand. It is
  kept exactly, as twice the wins plus the ties out of 1,980. Hands with the same number are
  the same point, so k-means runs on at most 1,981 weighted points and is instant.
- `--river-feature ochs` (default): 8 numbers per hand, the equity against each of 8 groups
  of opponent hole cards. The groups are made first: the 169 classes are clustered by the
  distribution of their river equity over all boards, with earth mover's distance, as in
  Johanson et al. (2013). With seed 1 they come out as: junk, weak offsuit hands, middling
  connectors, weak kings and queens with small jacks, queen-high and jack-high hands, weak
  aces with kings and small pairs, big aces and broadway hands, and the pairs 88 to AA
  (`abstraction-build info river.abs` lists them). Then k-means with straight-line distance
  on the 8 numbers. A hand that beats bluffs but loses to every value hand and a hand that
  does the reverse can have the same plain equity; OCHS tells them apart.

### 4. Turn and flop (`src/emd.rs`, `src/kmeans.rs`, `src/builder.rs`)

A turn hand becomes one of 46 river hands. Its description is the histogram of the river
buckets those 46 hands are in. A flop hand's is the histogram of turn buckets over its 47 turn
cards. Two hands are close when little has to be moved to turn one histogram into the other,
where moving a share of the hands from bucket `i` to bucket `j` costs that share times the
*ground distance* `d(i, j)` between the two buckets. That is the earth mover's distance (EMD).

- Ground distance between two river buckets: the straight-line distance between their centres
  (OCHS), or the difference of their equities (plain equity).
- Ground distance between two turn buckets: the earth mover's distance between their centres,
  which are themselves histograms over river buckets.

This is the potential-aware abstraction of Ganzfried and Sandholm (2014), which Pluribus's
abstraction follows. A flush draw (weak now, very strong on 9 river cards) and a weak made hand
of the same equity have different histograms and go to different buckets.

How the distance is computed:

- When the next street's buckets lie on a line (plain river equity, or slices of equity) the
  distance is exact and cheap: the area between the two cumulative curves.
- Otherwise an exact answer needs a transport problem solved for every hand and every centre,
  which is far too slow. `Matrix::greedy` is Ganzfried and Sandholm's approximation
  (Algorithm 2 of their paper): in round `r`, each bucket of the hand sends what it still has
  to its `r`-th nearest bucket of the centre, as much as fits. It builds a real plan, so it is
  never below the true distance. Measured against the exact distance: see "Measurements".
- k-means compares a hand with every centre. Most comparisons are ruled out by a lower bound
  before any distance is computed: the two histograms' average points (in OCHS space) can't be
  farther apart than their earth mover's distance, and neither can their average distances to
  12 anchor buckets. With 200 buckets 97% of the comparisons are ruled out, and the buckets
  are exactly the ones a plain k-means would give (a test checks this).
- The greedy distances between turn centres don't quite obey the triangle inequality, which the
  lower bound needs. They are replaced by the shortest route through other buckets, which
  restores it and brings them closer to the true distances.

`--turn-histogram equity` is the older, distribution-aware way of Johanson et al. (2013): the
turn hand's histogram is over 50 equal slices of river equity, on a line, with the exact
distance.

### 5. k-means (`src/kmeans.rs`)

- A canonical hand counts as many times as the deals it stands for.
- First centres: k-means++ (each new centre is a hand picked with chances in proportion to its
  squared distance from the centres so far), on a random sample of the training hands.
- Then Lloyd iterations: every training hand to its nearest centre, every centre to the mean
  of its hands. A centre that loses all its hands moves onto the hand that fits worst. It
  stops when fewer than 0.1% of the hands change bucket, or after 50 iterations.
- The river and turn train on a random sample (3.9 of 123 million and 1.9 of 14 million
  canonical hands) and then put every hand in the bucket of its nearest centre. The flop
  trains on every hand.
- Buckets are numbered by their average showdown equity against a random hand, weakest first.
  A table stores that equity for each bucket (exact, not an estimate), each bucket's size and
  its centre.

Same seed, same buckets: the random numbers come from the crate's own generator; the sums that
make a centre are sums of whole numbers, so the order in which threads add them doesn't
matter; sums of costs are taken over fixed blocks of hands in block order; ties go to the
lower-numbered centre. A test builds the same tables with 1 and 4 threads and compares the
bytes.

## Table files (`src/table.rs`)

One file per street: `flop.abs`, `turn.abs`, `river.abs`. All numbers are little-endian.

| Bytes | What |
| --- | --- |
| 8 | The text `PSABSTR` and a newline |
| 4 | Format version, now 1 |
| 4 | Length `H` of the header |
| `H` | The header as JSON: street, deck, number of hands and buckets, seed, every setting, the checksum of the table it was built from, the opponent groups, iterations and final cost |
| hands x 1 or 2 | The bucket of every canonical hand in index order: 1 byte each up to 256 buckets, else 2 |
| buckets x 8 | Real deals in each bucket |
| buckets x 4 | Each bucket's average equity |
| buckets x centre length x 4 | Each bucket's centre |
| see below | Distances between buckets: the river's and the turn's, for building the street before |
| 8 | XXH64 (seed 0) of every byte before it |

- Loading is one read of the whole file. Looking up a bucket is the hand's index (about 0.1
  microseconds) and one array read.
- A table of another format version, a file of the wrong length or a failed checksum is
  refused with a message that says which.
- Build times and thread counts are not in the file, so the same seed gives the same bytes and
  the same checksum. They go to `build_log.jsonl`.
- A table is written under a temporary name and renamed, so a stopped build never leaves half
  a table.

## Measurements

Taken on 26 and 27 Nov 2026 on this machine: a cloud container with 4 virtual cores of an
Intel Xeon at 2.1 GHz and 15 GB of memory, Linux, Rust 1.97.0, `cargo build --release` with
the default profile. Seed 1, default settings, all 4 cores, one process per street, nothing
else running. The numbers are the tool's own (it writes them to `build_log.jsonl`). Memory is
the highest resident memory of the process.

### Build time

| Buckets a street | River | Turn | Flop | All three |
| --- | --- | --- | --- | --- |
| 50 | 35 s | 94 s | 38 s | 2.8 min |
| 200 | 60 s | 4.9 min | 73 s | 7.1 min |
| 500 | 2.0 min | 10.6 min | 2.3 min | 14.9 min |
| 1,000 | 3.3 min | 20.4 min | 3.2 min | 26.9 min |

### Memory

| Buckets a street | River | Turn | Flop |
| --- | --- | --- | --- |
| 50 | 2.9 GB | 1.7 GB | 0.4 GB |
| 200 | 2.9 GB | 1.7 GB | 0.4 GB |
| 500 | 2.9 GB | 1.8 GB | 0.5 GB |
| 1,000 | 2.9 GB | 1.9 GB | 0.6 GB |

The river's memory is the description of every hand (8 numbers of 2 bytes for 123 million
hands: 2.0 GB) plus the hands' equity and buckets. The turn's is the river bucket of every
turn hand on each of its 46 river cards (1.3 GB) plus the river table and the river equity.
Neither changes much with the number of buckets.

The single command that builds all three streets in one process peaks at the river's 2.9 GB.
It is also a little quicker (147 s against 167 s with 50 buckets), since it keeps the hands'
equity from one street to the next.

### Where the time goes

Seconds on 4 cores.

| Buckets | Street | Describing the hands | First centres | Iterations | Every hand to its bucket | Rest | Iterations run | Compared in full |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 50 | river | 15 | 0 | 14 | 5 | 1 | 50 | all |
| 50 | turn | 16 | 1 | 66 | 10 | 0 | 48 | 5.3% |
| 50 | flop | 15 | 1 | 21 | 1 | 0 | 31 | 5.0% |
| 200 | river | 14 | 1 | 30 | 14 | 1 | 50 | all |
| 200 | turn | 16 | 6 | 228 | 42 | 0 | 47 | 2.7% |
| 200 | flop | 15 | 4 | 51 | 3 | 0 | 25 | 3.2% |
| 500 | river | 14 | 3 | 65 | 35 | 1 | 50 | all |
| 500 | turn | 17 | 16 | 498 | 103 | 5 | 45 | 1.9% |
| 500 | flop | 16 | 12 | 105 | 5 | 0 | 29 | 2.5% |
| 1,000 | river | 14 | 4 | 114 | 66 | 1 | 50 | all |
| 1,000 | turn | 22 | 43 | 919 | 193 | 48 | 47 | 1.4% |
| 1,000 | flop | 15 | 26 | 142 | 9 | 0 | 25 | 1.9% |

- Describing the hands takes about 15 seconds whatever the bucket count: scoring every river
  hand against the 8 opponent groups, or reading the next street's bucket for every hand and
  every card that can come (plus the river pass again, for the hands' exact equity).
- The turn's iterations are most of a build. Each one compares 1.9 million hands with every
  centre by earth mover's distance. "Compared in full" is the share of those comparisons the
  lower bound did not rule out. It falls as the buckets get smaller, so the time grows about
  in step with the bucket count, not with its square.
- The river always ran to the limit of 50 iterations. The turn and flop stopped by the rule
  (under 0.1% of the hands changing bucket).
- The "rest" of the 1,000-bucket turn is the table of distances between its 1,000 centres,
  which the flop build needs.

### Table sizes on disk

| Buckets a street | `river.abs` | `turn.abs` | `flop.abs` | All three |
| --- | --- | --- | --- | --- |
| 50 | 123.2 MB | 14.0 MB | 1.3 MB | 138 MB |
| 200 | 123.3 MB | 14.3 MB | 1.4 MB | 139 MB |
| 500 | 247.4 MB | 29.9 MB | 3.6 MB | 281 MB |
| 1,000 | 250.4 MB | 36.0 MB | 6.6 MB | 293 MB |

One byte per hand up to 256 buckets, two above that. The rest of a file (centres, distances
between buckets) is small next to it.

### Loading and looking up

| Buckets a street | Load, checksums verified | Load, unchecked |
| --- | --- | --- |
| 50 | 0.12 s | 0.09 s |
| 200 | 0.12 s | 0.08 s |
| 500 | 0.39 s | 0.19 s |
| 1,000 | 0.38 s | 0.15 s |

That is all three tables, with the files already in the system's cache.

Looking up the bucket of a random hand takes about 0.1 microseconds on the flop and 0.2 to
0.3 on the turn and river, on one core. The index itself is about 0.1 microseconds on every
street; the rest is the read from a table that is too big for the fast caches.

### On 64 cores

Not measured: this machine has 4 cores. What was measured is how the build speeds up from 1
to 2 to 4 threads, with 50 buckets a street:

| Threads | River | Turn | Flop | All three | Speed-up |
| --- | --- | --- | --- | --- | --- |
| 1 | 132 s | 370 s | 144 s | 646 s | |
| 2 | 68 s | 180 s | 76 s | 324 s | 2.0x |
| 4 | 35 s | 94 s | 38 s | 167 s | 3.9x |

And with 200 buckets, 2 threads against 4: river 116 s against 60 s, turn 582 s against
292 s, flop 149 s against 73 s. In all 847 s against 425 s, 2.0x.

Every thread count gave the same checksums, as it must.

Fitting "time = a part that doesn't speed up + a part that divides by the threads" to those
numbers puts the first part at 5 to 7 seconds for a whole build (reading and writing the
tables, mostly) at both bucket counts. So nearly all of the work divides by the cores, at
least up to 4.

The estimate for 64 cores, two ways. "As measured" keeps 7 seconds and divides the rest by 16
(64 cores against 4). "Half as good" divides it by 8: a cautious guess for what 4 cores can't
show, such as many cores sharing the memory's speed, slower single cores on big machines, and
steps that only start to count with 64 threads.

| Buckets a street | 4 cores, measured | 64 cores, as measured | 64 cores, half as good |
| --- | --- | --- | --- |
| 50 | 2.8 min | 17 s | 27 s |
| 200 | 7.1 min | 33 s | 1.0 min |
| 500 | 14.9 min | 1.0 min | 2.0 min |
| 1,000 | 26.9 min | 1.8 min | 3.5 min |

So a full build with 200 buckets a street should take about a minute on 64 cores, and with
1,000 buckets 2 to 4 minutes. This is an extrapolation over 16 times more cores than were
measured, not a measurement.

- Memory on 64 cores: as above, plus the sums that each thread keeps during k-means. Next to
  nothing with 200 buckets; up to about 2 GB more for the turn and flop with 1,000.
- With 64 cores there is less reason to train on a sample of the hands (point 4 of "Things to
  know"). With 200 buckets, 50 iterations over every river hand and 47 over every turn hand
  would take about 11 and 31 minutes on 4 cores, going by the few iterations that were timed.
  That makes about 3 to 6 minutes for the whole build on 64 cores.
- Get the same checksums as in `build_log.jsonl` here and you know the 64-core build did the
  same thing: 200 buckets, seed 1, default settings give river `e7ff8e349b9587b6`, turn
  `e8f2df9a3d04e8b8`, flop `7e143f5b92504f9b`.

### The other methods, with 200 buckets

| Method | River | Turn | Flop | All three |
| --- | --- | --- | --- | --- |
| Default: OCHS river, histograms over the next street's buckets | 60 s | 4.9 min | 73 s | 7.1 min |
| `--river-feature equity` | 8 s | 65 s | 2.8 min | 4.1 min |
| `--turn-histogram equity`, river as default | 60 s | 51 s | 3.0 min | 4.8 min |

On a line the distance is exact and cheap, so the turn is quick. Both flops ran to the limit
of 50 iterations. The plain-equity river needs 0.7 GB.

### What the buckets tell apart

`abstraction-build stats` gives every flop and turn hand two numbers: its equity against a
random hand, and how much that equity moves with the next card (the standard deviation over
the cards that can come: large for a draw, small for a made hand). It then reports how much
of the differences between hands the buckets account for (1 minus the variation inside
buckets over the total variation, real deals weighted). 100% would mean all the hands of a
bucket have the same number.

| Tables | River: equity | Turn: equity | Turn: movement | Flop: equity | Flop: movement |
| --- | --- | --- | --- | --- | --- |
| 50 buckets | 97.5% | 96.1% | 80.0% | 95.8% | 86.1% |
| 200 buckets | 98.8% | 98.0% | 89.3% | 97.6% | 91.3% |
| 500 buckets | 99.3% | 98.6% | 92.5% | 98.4% | 94.1% |
| 1,000 buckets | 99.5% | 98.9% | 94.4% | 98.7% | 95.6% |
| 200, `--river-feature equity` | 100.0% | 99.8% | 96.9% | 99.5% | 95.9% |
| 200, `--turn-histogram equity` | 98.8% | 99.7% | 96.8% | 99.5% | 95.9% |
| 200 equal slices of equity, no clustering | | 100.0% | 52.1% | 100.0% | 53.1% |

- Buckets cut from equity alone (last row) know a hand's equity and only half of how much
  it can still move. With 200 potential-aware buckets it is 98% of the first and 90% of the
  second. That is the point of the method.
- The two plain-equity rows score higher than the default. That does not make them better:
  both numbers are about equity against a random hand, which is exactly what those methods
  cluster on. The OCHS river spends part of its buckets on which kinds of opponent hands are
  beaten, and this measure gives no credit for that. Which one plays better is for the Phase 5
  gate (LBR against bucket count) to say.
- Going from 200 to 1,000 buckets moves these numbers by 1 to 5 points.

### The fast distance against the exact one

`abstraction-build gap` takes random turn hands (2,000 here) and compares the greedy distance
with the exact one (a transport problem solved for each pair), for the hand's own bucket's
centre and for another bucket's centre.

| Buckets | Own centre: greedy over exact | Worst hand | Other centre: greedy over exact | Worst hand | Lower bound, own and other centre |
| --- | --- | --- | --- | --- | --- |
| 50 | +6.2% | +32.9% | +3.1% | +22.7% | 63% and 90% of exact |
| 200 | +6.1% | +29.5% | +3.0% | +19.6% | 54% and 90% |
| 500 | +6.1% | +28.7% | +3.1% | +20.3% | 51% and 90% |
| 1,000 | +6.0% | +25.3% | +3.0% | +19.3% | 50% and 90% |

The greedy distance is 3% to 6% too long on average, the same at every bucket count. k-means
only needs to know which centre is nearest, so an error of the same size for every centre
matters less than these numbers suggest; how often it changes the nearest centre was not
measured.

## Tests

```bash
cargo test -p abstraction
```

```bash
cargo test --release -p abstraction
```

```bash
cargo test --release -p abstraction -- --ignored
```

The first runs the quick tests (about 25 seconds in a debug build, compiling included). The
second adds five that are slow without optimisation (about 20 seconds). The third runs the
exhaustive and real-deck ones (about 2.5 minutes on 4 cores and 3 GB of memory;
`built_tables_pass_the_checks` needs `ABSTRACTION_TABLES` set to a directory of built tables
and does nothing without it). All three were run on the final code, and the last one against
the 200-bucket and 1,000-bucket tables. On `main` the third is what the nightly "Rust slow
tests" workflow runs.

| Test | Checks |
| --- | --- |
| `canonical_hand_counts` | 169, 1,286,792, 13,960,050 and 123,156,254 |
| `counts_for_other_deals` | The method against other published counts: 55,190,538 and 2,428,287,420 when the board's order is kept, 1,755 flops, 134,459 river boards |
| `small_deck_counts_match_brute_force` | On decks of 12 to 20 cards: the number of indexes is the number of suit classes counted by brute force, and every index is hit by exactly `multiplicity` deals |
| `preflop_and_flop_round_trip`, `turn_round_trip`, `river_round_trip` (last two ignored) | `index(unindex(i)) == i` for every index of every street |
| `every_flop_deal_maps_to_a_canonical_hand`, `every_turn_deal...`, `every_river_deal...` (last two ignored) | Every raw deal (all 2,809,475,760 on the river) maps to an index in range, and every index is hit exactly `multiplicity` times. So every hand maps to a canonical one, every index is used, and the weights are right |
| `relabelled_hands_share_an_index` | 20,000 random hands per street: all 24 suit relabellings and any card order give the same index, and the canonical hand is one of the relabellings |
| `equity::tests` | The one-pass showdown against comparing every pair of hands one at a time, with and without opponent groups |
| `emd::tests` | The exact transport solver on cases done by hand; the line distance equals the exact one; the greedy distance is never below the exact one and the lower bound never above |
| `bounds_never_change_the_nearest_centre` | With the lower bounds or without, every hand lands on the same centre at the same cost |
| `same_seed_same_buckets_with_one_thread_or_many`, `same_seed_same_tables_whatever_the_thread_count` | Same seed, same buckets, with 1, 3 or 4 threads; another seed gives other buckets |
| `river_buckets_follow_equity` | 24-card deck: the royal flush is in the top bucket, quads share it (the nuts and the near-nuts), the best and worst hands sit in the best and worst buckets, a hand's equity is close to its bucket's |
| `turn_and_flop_buckets_follow_equity_and_potential` | 24-card deck: the buckets explain the hands' equity and more of its spread over the next card than buckets cut from equity alone; hands sit closer to their bucket's mean histogram than in those; the stored bucket equity is the exact average |
| `the_other_methods_build_too` | Plain-equity river, turn over slices of equity |
| `tables_save_load_and_look_up`, `table::tests` | Files come back as written; lookups agree with the table for random hands in any suits; a damaged file, another format version or tables of another deck are refused |
| `fixture_tables_rebuild_exactly` | The small tables in `tests/fixtures/small` load, and building again from the settings in their headers gives the same bytes |
| `real_river_table_groups_hands_sensibly` (ignored, 1 minute) | Builds the real river table with 50 buckets: the nuts and the near-nuts share the top bucket, air sits in the bottom one, stronger hands are in higher buckets, and the table's checksum is the recorded one |
| `built_tables_pass_the_checks` (ignored) | The checks of `abstraction-build check` on tables you built |

## Things to know

1. The small tables in `tests/fixtures/small` are for a deck of tens to aces with 12 buckets.
   A change that alters the buckets on purpose makes `fixture_tables_rebuild_exactly` fail.
   Rebuild them from `engine`, and remember that every table built before is stale too:

   ```bash
   rm crates/abstraction/tests/fixtures/small/*.abs
   ```

   ```bash
   ./target/release/abstraction-build build --out crates/abstraction/tests/fixtures/small --ranks 5 --buckets 12
   ```

   ```bash
   rm crates/abstraction/tests/fixtures/small/build_log.jsonl
   ```

   Also update `RIVER_50_CHECKSUM` in `tests/real_deck.rs` and the three checksums quoted
   under "On 64 cores".
2. "Same seed, same tables" is tested here across runs and thread counts on one machine. The
   code uses only exact integer sums and plain floating-point steps in a fixed order, so other
   machines should give the same bytes, but that has not been tried on a Mac.
3. On 64 cores the tables must be built with the same code version to get the same checksums.
   The header's `built_by` and `format` say which.
4. The river and the turn train their centres on a random sample: 4 and 2 million draws,
   which is 3.9 of the 123 million river hands and 1.9 of the 14 million turn hands. Every
   hand is then put in the bucket of its nearest centre. `--river-train 0 --turn-train 0`
   trains on every hand. Timed for a few iterations with 200 buckets on 4 cores: about 14
   seconds an iteration for the river (0.6 on the sample; 3.6 GB of memory, not 2.9) and
   about 40 for the turn (5 on the sample). Whether that gives better buckets was not
   measured.
5. Most of the gain comes early. In the 200-bucket build, `--tolerance 0.005` would have
   stopped the river at iteration 27 of 50 with a cost 0.35% above the final one, the turn at
   24 of 47 (0.06% above) and the flop at 15 of 25 (0.19% above): about half the iterations.
   The river was still improving slowly when it hit the limit of 50; `--max-iters` raises it.
6. With `--river-feature equity` a river hand is one of at most 1,981 values, and a table
   can't have more buckets than there are different values. On small decks it can come out
   with fewer buckets than asked. The header says both: `buckets` is what the table has,
   `settings.buckets` what was asked for.
7. OCHS or plain equity, and how many buckets: not decided here. This crate only measures how
   well the buckets describe equity ("What the buckets tell apart"). The Phase 5 gate (LBR
   win rate against bucket count) decides. It needs a strategy trained in the abstract game
   at each bucket count and the LBR exploiter run against it, which is the next piece of
   work, not part of this crate.
8. A lookup costs 0.1 to 0.3 microseconds. A solver that needs a hand's bucket at many nodes
   should look it up once per street when the cards are dealt, not at every node.
9. The checks of `src/checks.rs` pass on all six sets of tables built here (50, 200, 500 and
   1,000 buckets, and the two other methods with 200). With the default river the nut flush
   and the second nut flush share the top bucket at every count. The three best sets on a dry
   board share it with 50 buckets, which is what `real_river_table_groups_hands_sensibly`
   asserts. With more buckets they separate: buckets 199, 198 and 198 of 200, and 999, 998
   and 994 of 1,000.
