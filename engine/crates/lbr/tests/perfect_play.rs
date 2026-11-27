//! Against perfect play LBR wins nothing.
//!
//! Three small games with exact answers:
//!
//! 1. A river spot with three kinds of hand (the textbook "AKQ" game), whose equilibrium is
//!    known in closed form. LBR's expected winnings are worked out exactly, not sampled.
//! 2. A river spot with wider ranges that block each other's cards, solved with the cfr
//!    crate's CFR+ and measured with its exact best response. In position LBR must equal
//!    that best response to the last digit.
//! 3. Stacks of one big blind, played through the match runner.

use cfr::{best_response_value, Cfr, Game, InfoKey, Node, Policy, Solver, TabularPolicy, Variant};
use lbr::{
    play_match, ActionProbs, AlwaysCall, BetSize, EvalRanker, Lbr, LbrConfig, MatchConfig,
    PublicState, Range, Strategy,
};
use nlhe::{parse_card, Action, Card, Config, Deal, HandRanker, State, Street};

const BUTTON: usize = 0;
const BIG_BLIND: usize = 1;
/// The pot at the start of the river, and each player's stack behind it.
const POT: f64 = 200.0;
const BEHIND: f64 = 200.0;

fn cards(s: &str) -> Vec<Card> {
    s.split_whitespace()
        .map(|c| parse_card(c).unwrap_or_else(|| panic!("bad card {c}")))
        .collect()
}

fn hands(list: &[&str]) -> Vec<[Card; 2]> {
    list.iter()
        .map(|h| cards(h).try_into().expect("two cards"))
        .collect()
}

/// The start of the river. Blinds 1 and 2, stacks of 300: the button raised to 100, the big
/// blind called, and both checked the flop and the turn. There are 200 in the pot and 200
/// behind, so all in is a pot-sized bet. The big blind acts first.
fn river(board: &[Card], button: [Card; 2], big_blind: [Card; 2]) -> State {
    let config = Config::new(&[300, 300], 1, 2, 0, BUTTON).unwrap();
    let deal = Deal::new(&[button, big_blind], board.try_into().expect("five cards")).unwrap();
    let mut state = State::new(&config, deal).unwrap();
    for action in [
        Action::RaiseTo(100),
        Action::Call,
        Action::Check,
        Action::Check,
        Action::Check,
        Action::Check,
    ] {
        state.apply(action).unwrap();
    }
    assert_eq!(state.street(), Street::River);
    assert_eq!(state.current_player(), Some(BIG_BLIND));
    assert_eq!(
        (state.pot() as f64, state.stacks()[0] as f64),
        (POT, BEHIND)
    );
    state
}

/// LBR's exact expected winnings for the whole hand, in chips, from `state` on. LBR's own
/// actions are whatever it chooses; the opponent's are averaged with their probabilities,
/// each branch with its own copy of LBR and of the range it tracks.
fn exact_value(opponent: &dyn Strategy, lbr: &Lbr, state: &State) -> f64 {
    let Some(seat) = state.current_player() else {
        return state.payouts(&EvalRanker).unwrap()[lbr.seat()] as f64;
    };
    if seat == lbr.seat() {
        let mut lbr = lbr.clone();
        let mut next = state.clone();
        next.apply(lbr.act(state)).unwrap();
        return exact_value(opponent, &lbr, &next);
    }
    let mut probs = ActionProbs::new();
    opponent.action_probs(&PublicState::new(state), state.hole_cards(seat), &mut probs);
    assert!((probs.total() - 1.0).abs() < 1e-12);
    let mut value = 0.0;
    for &(action, p) in probs.as_slice() {
        if p > 0.0 {
            let mut lbr = lbr.clone();
            lbr.observe(state, action);
            let mut next = state.clone();
            next.apply(action).unwrap();
            value += p * exact_value(opponent, &lbr, &next);
        }
    }
    value
}

/// LBR's exact expected winnings in each seat (button, big blind) on the river, averaged
/// over every deal of one hand from each range that share no card.
fn river_values(
    config: &LbrConfig,
    opponent: &dyn Strategy,
    board: &[Card],
    button_range: &[[Card; 2]],
    big_blind_range: &[[Card; 2]],
) -> [f64; 2] {
    let mut total = [0.0; 2];
    let mut deals = 0;
    for &button in button_range {
        for &big_blind in big_blind_range {
            if lbr::card_mask(&button) & lbr::card_mask(&big_blind) != 0 {
                continue;
            }
            deals += 1;
            let state = river(board, button, big_blind);
            let as_button = Lbr::with_range(
                config,
                opponent,
                BUTTON,
                button,
                Range::from_hands(big_blind_range),
                0,
            );
            let as_big_blind = Lbr::with_range(
                config,
                opponent,
                BIG_BLIND,
                big_blind,
                Range::from_hands(button_range),
                0,
            );
            total[BUTTON] += exact_value(opponent, &as_button, &state);
            total[BIG_BLIND] += exact_value(opponent, &as_big_blind, &state);
        }
    }
    total.map(|t| t / deals as f64)
}

// ----- 1. the AKQ game -----

/// How the player with kings answers a bet.
#[derive(Clone, Copy)]
enum Calls {
    /// Often enough that a bluff earns nothing: pot / (pot + bet).
    Perfect,
    Always,
    Never,
}

/// How often the player with queens bets when checked to.
#[derive(Clone, Copy)]
enum Bluffs {
    /// Often enough that calling earns nothing: bet / (pot + bet) of the queens.
    Perfect,
    Always,
    Never,
}

/// The board is 2c 2d 2h 7s 8s. The button holds aces (the best hand) or queens (the worst),
/// equally often. The big blind holds kings, which beat queens and lose to aces. Nobody
/// holds a card the other could use, so the known solution is exact:
///
/// - kings check, and call a bet of size s with probability pot / (pot + s);
/// - aces bet everything; queens bluff everything with probability bet / (pot + bet) and
///   otherwise check;
/// - if kings bet, aces raise (or call) and queens fold.
struct Akq {
    calls: Calls,
    bluffs: Bluffs,
}

const ACE: u8 = 12;
const KING: u8 = 11;

impl Strategy for Akq {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        let legal = public.legal_actions();
        let all_in = legal.raise.map(|r| Action::RaiseTo(r.max_to));
        let rank = hole[0] / 4;
        if rank == KING {
            let Some(to_call) = legal.call else {
                out.push(Action::Check, 1.0);
                return;
            };
            let pot = public.pot() as f64;
            let call = match self.calls {
                Calls::Perfect => (pot - to_call as f64) / pot,
                Calls::Always => 1.0,
                Calls::Never => 0.0,
            };
            out.push(Action::Call, call);
            out.push(Action::Fold, 1.0 - call);
        } else if rank == ACE {
            out.push(all_in.unwrap_or(Action::Call), 1.0);
        } else if legal.check {
            let bet = public.stacks()[public.current_player().unwrap()] as f64;
            let bluff = match self.bluffs {
                Bluffs::Perfect => bet / (public.pot() as f64 + bet),
                Bluffs::Always => 1.0,
                Bluffs::Never => 0.0,
            };
            out.push(all_in.expect("the big blind has chips"), bluff);
            out.push(Action::Check, 1.0 - bluff);
        } else {
            out.push(Action::Fold, 1.0);
        }
    }
}

fn akq_values(config: &LbrConfig, opponent: &Akq) -> [f64; 2] {
    let board = cards("2c 2d 2h 7s 8s");
    let pairs = |rank: char| -> Vec<[Card; 2]> {
        let suits = ['c', 'd', 'h', 's'];
        let mut out = Vec::new();
        for a in 0..4 {
            for b in a + 1..4 {
                out.push(hands(&[&format!("{rank}{} {rank}{}", suits[a], suits[b])])[0]);
            }
        }
        out
    };
    let button: Vec<[Card; 2]> = pairs('A').into_iter().chain(pairs('Q')).collect();
    river_values(config, opponent, &board, &button, &pairs('K'))
}

#[test]
fn akq_game_lbr_wins_exactly_nothing_from_the_solution() {
    let perfect = Akq {
        calls: Calls::Perfect,
        bluffs: Bluffs::Perfect,
    };
    // The game is worth a quarter of the pot to the kings and three quarters to the button.
    // Each put 100 in before the river, so the kings lose 50 a hand and the button wins 50.
    for (name, config) in [
        (
            "all in only",
            LbrConfig::new(&[BetSize::AllIn], Street::River),
        ),
        ("fcpa", LbrConfig::fcpa(Street::River)),
        ("56 bets", LbrConfig::bets56(Street::River)),
    ] {
        let [button, big_blind] = akq_values(&config, &perfect);
        println!(
            "AKQ, {name}: LBR wins {button:+.6} on the button, {big_blind:+.6} in the big blind"
        );
        assert!((button - POT / 4.0).abs() < 1e-9, "{name}: button {button}");
        assert!(
            (big_blind + POT / 4.0).abs() < 1e-9,
            "{name}: big blind {big_blind}"
        );
        assert!((button + big_blind).abs() < 1e-9, "{name}");
    }
    // With fold and call only, LBR cannot bet its aces and does worse than the solution.
    let [button, big_blind] = akq_values(&LbrConfig::fc(Street::River), &perfect);
    assert!((button - 0.0).abs() < 1e-9 && (big_blind + POT / 4.0).abs() < 1e-9);
}

#[test]
fn akq_game_lbr_wins_from_every_mistake() {
    let config = LbrConfig::fcpa(Street::River);
    let mistakes = [
        ("calls every bet", Calls::Always, Bluffs::Perfect),
        ("folds to every bet", Calls::Never, Bluffs::Perfect),
        ("always bluffs", Calls::Perfect, Bluffs::Always),
        ("never bluffs", Calls::Perfect, Bluffs::Never),
    ];
    for (name, calls, bluffs) in mistakes {
        let [button, big_blind] = akq_values(&config, &Akq { calls, bluffs });
        let total = button + big_blind;
        println!("AKQ, opponent {name}: LBR wins {total:+.3} chips over the two seats");
        // Each of these mistakes gives up exactly a quarter of the pot.
        assert!((total - POT / 4.0).abs() < 1e-9, "{name}: {total}");
    }
}

// ----- 2. a solved river spot with blockers -----

/// The river spot of [`river`] as a game for the cfr crate: check or bet all in, fold or
/// call. Player 0 is the big blind (first to act), player 1 the button.
#[derive(Clone)]
struct RiverGame {
    ranges: [Vec<[Card; 2]>; 2],
    strength: [Vec<u32>; 2],
    /// Every deal of one hand each that share no card, as indices into the ranges.
    deals: Vec<(u16, u16)>,
}

#[derive(Clone, Copy)]
struct Spot {
    deal: u16,
    line: u8,
}

const NOT_DEALT: u16 = u16::MAX;
// Lines: 0 start, 1 check, 2 check-bet, 3 bet; then the ends: 4 check-check, 5 check-bet-fold,
// 6 check-bet-call, 7 bet-fold, 8 bet-call.
const NEXT: [[u8; 2]; 4] = [[1, 3], [4, 2], [5, 6], [7, 8]];

impl RiverGame {
    fn new(board: &[Card], big_blind: &[[Card; 2]], button: &[[Card; 2]]) -> RiverGame {
        let strength = |range: &[[Card; 2]]| -> Vec<u32> {
            range
                .iter()
                .map(|h| {
                    EvalRanker
                        .rank7(&[h[0], h[1], board[0], board[1], board[2], board[3], board[4]])
                })
                .collect()
        };
        let mut deals = Vec::new();
        for (i, a) in big_blind.iter().enumerate() {
            for (j, b) in button.iter().enumerate() {
                if lbr::card_mask(a) & lbr::card_mask(b) == 0 {
                    deals.push((i as u16, j as u16));
                }
            }
        }
        RiverGame {
            strength: [strength(big_blind), strength(button)],
            ranges: [big_blind.to_vec(), button.to_vec()],
            deals,
        }
    }

    fn key(line: u8, hand: usize) -> InfoKey {
        (line as u64) << 16 | hand as u64
    }
}

impl Game for RiverGame {
    type State = Spot;

    fn num_players(&self) -> usize {
        2
    }

    fn root(&self) -> Spot {
        Spot {
            deal: NOT_DEALT,
            line: 0,
        }
    }

    fn node(&self, s: &Spot) -> Node {
        match (s.deal, s.line) {
            (NOT_DEALT, _) => Node::Chance,
            (_, 0 | 2) => Node::Player(0),
            (_, 1 | 3) => Node::Player(1),
            _ => Node::Terminal,
        }
    }

    fn chance_outcomes(&self, _s: &Spot, out: &mut Vec<(cfr::Action, f64)>) {
        let p = 1.0 / self.deals.len() as f64;
        out.extend((0..self.deals.len()).map(|d| (d as cfr::Action, p)));
    }

    fn legal_actions(&self, _s: &Spot, out: &mut Vec<cfr::Action>) {
        out.extend([0, 1]);
    }

    fn apply(&self, s: &mut Spot, action: cfr::Action) {
        if s.deal == NOT_DEALT {
            s.deal = action as u16;
        } else {
            s.line = NEXT[s.line as usize][action as usize];
        }
    }

    fn info_key(&self, s: &Spot) -> InfoKey {
        let (i, j) = self.deals[s.deal as usize];
        RiverGame::key(s.line, if matches!(s.line, 0 | 2) { i } else { j } as usize)
    }

    /// Chips won over the whole hand: each player put half the pot in before the river.
    fn utility(&self, s: &Spot, player: usize) -> f64 {
        let (i, j) = self.deals[s.deal as usize];
        let showdown = match self.strength[0][i as usize].cmp(&self.strength[1][j as usize]) {
            std::cmp::Ordering::Greater => 1.0,
            std::cmp::Ordering::Equal => 0.0,
            std::cmp::Ordering::Less => -1.0,
        };
        let big_blind = match s.line {
            4 => showdown * POT / 2.0,
            5 => -POT / 2.0,
            7 => POT / 2.0,
            6 | 8 => showdown * (POT / 2.0 + BEHIND),
            _ => unreachable!("not the end of the hand"),
        };
        if player == 0 {
            big_blind
        } else {
            -big_blind
        }
    }
}

/// The solved policy as a strategy LBR can read.
struct Solved<'a> {
    game: &'a RiverGame,
    policy: TabularPolicy,
}

impl Strategy for Solved<'_> {
    fn action_probs(&self, public: &PublicState<'_>, hole: [Card; 2], out: &mut ActionProbs) {
        let river: Vec<Action> = public
            .history()
            .iter()
            .filter(|m| m.street == Street::River)
            .map(|m| m.action)
            .collect();
        let line = match river.as_slice() {
            [] => 0,
            [Action::Check] => 1,
            [Action::Check, Action::RaiseTo(_)] => 2,
            [Action::RaiseTo(_)] => 3,
            other => panic!("a line outside the solved game: {other:?}"),
        };
        let player = if public.current_player() == Some(BIG_BLIND) {
            0
        } else {
            1
        };
        let hand = self.game.ranges[player]
            .iter()
            .position(|h| lbr::combo_index(h[0], h[1]) == lbr::combo_index(hole[0], hole[1]))
            .expect("a hand of the range");
        let mut probs = [0.0; 2];
        self.policy
            .action_probs(RiverGame::key(line, hand), &mut probs);
        let (passive, aggressive) = if line < 2 {
            let all_in = public.legal_actions().raise.expect("chips behind").max_to;
            (Action::Check, Action::RaiseTo(all_in))
        } else {
            (Action::Fold, Action::Call)
        };
        out.push(passive, probs[0]);
        out.push(aggressive, probs[1]);
    }
}

#[test]
fn solved_river_spot_lbr_cannot_beat_the_solution() {
    // Kings, tens and aces sit in both ranges, so each player's hand changes what the other
    // can hold: the range tracking has to get card removal right.
    let board = cards("Kh Th 7s 4c 2d");
    let big_blind = hands(&[
        "As Kd", "Ac Ks", "Kd Qd", "Ks Jc", "Kc Ts", "Td 9d", "Tc 8c", "9s 9c", "7d 7c", "Qs Js",
        "Ah 5h", "6s 5s", "As Qc", "8h 6h",
    ]);
    let button = hands(&[
        "Ad Ac", "Ah Kc", "Ks Qh", "Kd Jd", "Ts Td", "4h 4d", "Qd Qc", "Jd Jc", "Kc Tc", "9h 8h",
        "Qh Jh", "6d 5d", "As 3s", "Ad Qs",
    ]);
    let game = RiverGame::new(&board, &big_blind, &button);
    let mut solver = Cfr::new(game.clone(), Variant::CfrPlus);
    solver.run(3_000);
    let solved = Solved {
        game: &game,
        policy: solver.average_policy(),
    };
    // What an exact best response wins from the solution in each seat. The two sum to the
    // distance from equilibrium (the game is zero-sum), which CFR+ has driven to almost 0.
    let best_big_blind = best_response_value(&game, &solved.policy, 0);
    let best_button = best_response_value(&game, &solved.policy, 1);
    let gap = best_big_blind + best_button;
    println!(
        "solved river spot: {} deals, best responses {best_button:+.6} (button) and \
         {best_big_blind:+.6} (big blind), {gap:.2e} chips from equilibrium",
        game.deals.len()
    );
    assert!((0.0..0.05).contains(&gap), "not solved: {gap}");

    // All in is the pot-sized bet here, so fcpa has exactly the solved game's actions.
    let config = LbrConfig::fcpa(Street::River);
    let [lbr_button, lbr_big_blind] = river_values(&config, &solved, &board, &button, &big_blind);
    println!(
        "LBR wins {lbr_button:+.6} on the button and {lbr_big_blind:+.6} in the big blind: \
         {:+.6} chips over the two seats, in a pot of {POT}",
        lbr_button + lbr_big_blind
    );
    // Last to act, with one bet size and no raise possible, LBR's look one action ahead is
    // the whole rest of the game: it is an exact best response.
    assert!(
        (lbr_button - best_button).abs() < 1e-9,
        "{lbr_button} against {best_button}"
    );
    // First to act it assumes a check ends the hand, so it can only do worse than the best.
    assert!(lbr_big_blind <= best_big_blind + 1e-9);
    // Against the solution it wins nothing over the two seats.
    assert!(lbr_button + lbr_big_blind <= gap + 1e-9);
    assert!(
        lbr_button + lbr_big_blind > -0.05 * POT,
        "LBR lost more than 5% of the pot"
    );
}

// ----- 3. one big blind each, through the match runner -----

#[test]
fn one_big_blind_stacks_lbr_wins_exactly_nothing() {
    // Blinds 1 and 2, stacks of 2. The big blind is all in on posting. The small blind has
    // one decision: put the other chip in to win 3, or fold. Every hand has more than the
    // 25% it needs against a random hand (the worst, 3-2 offsuit, has 32%), so perfect play
    // is to always call, and LBR must find the same. Each deal is then a showdown played
    // from both seats, and the two results cancel.
    let table = MatchConfig {
        hands: 600,
        seed: 3,
        small_blind: 1,
        big_blind: 2,
        stack: 2,
    };
    let config = LbrConfig::fcpa(Street::Preflop).with_sampled_preflop(300);
    let result = play_match(&AlwaysCall, &config, &table);
    assert_eq!(result.hands, 600);
    assert_eq!(result.bb_per_100, 0.0);
    assert_eq!(result.std_err, 0.0);
    // The seats on their own are not zero: the showdowns are real.
    assert_eq!(result.button_bb_per_100, -result.big_blind_bb_per_100);
    assert!(result.button_bb_per_100 != 0.0);
}
