# PHH dataset: quality, coverage and limits

Built from `/home/claude/uoftcprg/phh-dataset` with HandHQ share 0.01 (10308 files, 732.2 s).

| Source | Hands read | Hold'em replayed | Other variants | Unreadable | Missing actions | Corrupt | Duplicates | Decisions | Own cards known | Leak checks (mismatches) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| pluribus | 10,000 | 10,000 | 0 | 0 | 0 | 0 | 0 | 91,356 | 100.0% | 91,356 (0) |
| handhq | 218,804 | 218,797 | 0 | 0 | 7 | 0 | 1 | 1,760,637 | 2.8% | 70,581 (0) |
| wsop | 83 | 11 | 72 | 0 | 0 | 0 | 0 | 88 | 100.0% | 88 (0) |
| historical | 5 | 1 | 4 | 0 | 0 | 0 | 0 | 10 | 90.0% | 10 (0) |

## Output files (decision rows)

- `evaluation/historical.parquet`: 10
- `evaluation/wsop.parquet`: 88
- `handhq/test.parquet`: 72,782
- `handhq/train.parquet`: 1,506,874
- `handhq/validation.parquet`: 180,977
- `pluribus/decisions.parquet`: 91,356

## Variants seen

- NT: 228,816
- FO/8: 14
- F7S: 13
- FR: 10
- F2L3D: 8
- PO: 8
- F7S/8: 7
- FT: 7
- N2L1D: 7
- FB: 1
- NS: 1

## Table sizes (Hold'em hands)

- pluribus: 6 players 10,000
- handhq: 2 players 30,560, 3 players 7,071, 4 players 20,745, 5 players 53,183, 6 players 62,684, 7 players 8,335, 8 players 17,156, 9 players 16,957, 10 players 2,106
- wsop: 5 players 11
- historical: 3 players 1

## Actions by street

- pluribus: flop bet 3,157, flop call 1,699, flop check 7,103, flop fold 1,776, flop raise 342, preflop call 6,372, preflop check 405, preflop fold 44,077, preflop raise 10,846, river bet 1,685, river call 612, river check 2,775, river fold 1,146, river raise 167, turn bet 2,147, turn call 1,053, turn check 4,594, turn fold 1,272, turn raise 128
- handhq: flop bet 71,959, flop call 36,832, flop check 124,139, flop fold 60,628, flop raise 12,253, preflop call 165,548, preflop check 40,562, preflop fold 816,888, preflop raise 169,432, river bet 25,121, river call 11,270, river check 43,496, river fold 16,776, river raise 2,776, turn bet 38,621, turn call 22,131, turn check 72,378, turn fold 24,678, turn raise 5,149
- wsop: flop bet 4, flop call 3, flop check 4, flop fold 1, preflop call 7, preflop check 1, preflop fold 39, preflop raise 15, river bet 2, river call 1, river check 1, river fold 1, river raise 1, turn bet 2, turn call 1, turn check 4, turn fold 1
- historical: flop bet 1, flop call 1, preflop call 1, preflop fold 1, preflop raise 2, turn bet 1, turn call 1, turn raise 2

## Examples of dropped hands

- out_of_turn: `data/handhq/FTP-2009-07-01_2009-07-23_1000NLH_OBFU/10/ftp NLH handhq_353-OBFUSCATED.phhs#826: 'p1 cc' while p2 was to act`
- out_of_turn: `data/handhq/FTP-2009-07-01_2009-07-23_600NLH_OBFU/6/ftp NLH handhq_12-OBFUSCATED.phhs#410: 'p1 cc' while p2 was to act`
- out_of_turn: `data/handhq/ONG-2009-07-01_2009-07-23_1000NLH_OBFU/10/ong NLH handhq_127-OBFUSCATED.phhs#471: 'p1 cc' while p2 was to act`

## Known limits

- HandHQ logs stacks as infinite: stack, effective stack and stack-to-pot ratio are missing there.
- HandHQ shows the acting player's cards mostly in hands that reached showdown (selection bias).
- Labels are the observed actions (`label_source = observed`), never the best actions.
- Splits keep whole session groups together (Pluribus: day folder; HandHQ: site, stake, day).
- The ACPC logs are only on Zenodo and are not part of this build.
