# eval: hold'em hand evaluator

Scores 5, 6 or 7 cards as the best 5-card hand. Part of the Rust engine for the solver-based agent.
No dependencies outside the standard library.

```rust
use eval::{eval7, parse_cards, Card, Category, Hand};

let cards: [Card; 7] = parse_cards("AhKh QhJh2c 7d Th").unwrap().try_into().unwrap();
let rank = eval7(&cards);
assert_eq!(rank.category(), Category::StraightFlush);
println!("{rank}");                         // "straight flush (7462)"

// Building a hand one card at a time is cheaper when many hands share a board.
let board = Hand::from_cards(&parse_cards("QhJh2c7dTh").unwrap());
let a = board.add("Ah".parse().unwrap()).add("Kh".parse().unwrap()).eval7();
let b = board.add("As".parse().unwrap()).add("Ad".parse().unwrap()).eval7();
assert!(a > b);
```

## API

| Item | What |
| --- | --- |
| `Card` | `index = rank * 4 + suit`, rank 0 = 2 up to 12 = ace, suit 0..3 = c, d, h, s. `Card::new(rank, suit)`, `from_index`, `rank()`, `suit()`, `index()`, `Card::all()` |
| `"Ah".parse::<Card>()`, `card.to_string()` | Parse and display. Letters can be either case; display is `"Ah"`, `"Td"` |
| `parse_cards("AhKs Qd")`, `format_cards(&cards)` | Lists of cards; spaces and commas are optional |
| `eval7`, `eval6`, `eval5` | Take `&[Card; N]` and return a `HandRank` |
| `eval(&[Card])` | Any of 5, 6 or 7 cards; panics otherwise |
| `Hand` | `Hand::new().add(card)`, `Hand::from_cards`, `eval()`, `eval7()`, `len()`, `contains()` |
| `HandRank` | Ordered: higher is better, equal ties. `value()` is 1 (7-5-4-3-2 offsuit) to 7,462 (royal flush); `category()` |
| `Category` | `HighCard` to `StraightFlush`, ordered, with `name()` and `value_range()` |

Cards must be distinct. Duplicates are not checked in release builds and give an unspecified result.

## How it works

`build.rs` makes the tables at compile time (about a second):

1. The 7,462 five-card classes are listed, sorted by strength and numbered 1 to 7,462.
2. Each card adds `5^rank` (a base-5 count of each rank) plus 1 to a 4-bit counter for its suit
   into a `u64`, and sets bit `16 * suit + rank` in a second `u64`.
3. Flush: the suit counters start at 3, so a suit with 5 or more cards sets its counter's top
   bit. That suit's 13-bit rank mask indexes an 8,192-entry table of best flushes and straight
   flushes. With 7 cards a flush rules out a full house and quads, so nothing else is needed.
4. Otherwise the base-5 number names the rank multiset. A perfect hash (hash and displace: a
   multiply, a 16-bit displacement and an XOR) maps it to a slot in a table of best non-flush
   classes, one table per hand size: 49,205 multisets for 7 cards in 65,536 slots (128 KB),
   18,395 for 6, 6,175 for 5.

## Tests

```bash
cargo test -p eval
```

```bash
cargo test --release -p eval -- --ignored
```

| Test | Checks |
| --- | --- |
| `five_card_hands_have_7462_ranks_in_naive_order` | All 2,598,960 five-card hands give exactly 7,462 distinct ranks, in the same order as a separate plain evaluator, with the standard category counts |
| `seven_card_category_counts` (ignored, slow) | All 133,784,560 seven-card hands: straight flush 41,584; four of a kind 224,848; full house 3,473,184; flush 4,047,644; straight 6,180,020; three of a kind 6,461,620; two pair 31,433,400; pair 58,627,800; high card 23,294,460; and 4,824 distinct ranks |
| `every_six_card_hand_matches_best_subset` (ignored, slow) | All 20,358,520 six-card hands equal the best of their 5-card subsets; 6,075 distinct ranks |
| `random_six_and_seven_card_hands_match_best_subset` | 200,000 random hands against the best of their 5-card subsets |
| `one_million_showdowns_match_pokerkit` | 1,000,000 random heads-up showdowns scored by PokerKit 0.7.8: same rank for all 2,000,000 hands, same category and same winner |

The two slow tests take about 1 second in a release build (much longer in a debug build).

### PokerKit fixture

`tests/fixtures/pokerkit_showdowns.bin` (4 MB) comes from `tools/reference/eval_fixtures.py`. To keep
it small it stores PokerKit's ranks, not the cards. The Rust test deals the same cards again from
the seed in the header (SplitMix64, partial Fisher-Yates) and first checks the header's checksum of
every dealt card. To rebuild it (about 2 minutes on 4 cores):

```bash
pip install pokerkit==0.7.8
```

```bash
python tools/reference/eval_fixtures.py
```

## Speed

```bash
cargo bench -p eval
```

Criterion, 26 Nov 2026, in a cloud container (Intel Xeon @ 2.10 GHz, 4 cores, one thread used),
Rust 1.97, release build:

| Benchmark | Time | Evaluations per second |
| --- | --- | --- |
| `eval7`, 65,536 random hands | 236 µs | 278 million |
| `eval6`, 65,536 random hands | 201 µs | 327 million |
| `eval5`, 65,536 random hands | 151 µs | 435 million |
| All 2,118,760 boards for AhKd, built with `Hand::add` | 3.02 ms | 702 million |

The random benchmarks read each hand from an array and add its cards, so they include that cost.
The enumeration shares the work of the first cards across boards, as an equity calculation would.
