"""Reference river spots solved by the Python river solver (app/solver).

The Rust solver in engine/crates/subgame is checked against these (roadmap Phase 4: "matches
Phase 2"). Spots and results are in data/reference_spots/python_solver/, in the SPOT and
RESULT formats of data/SPOT_FORMAT.md; the reading, hashing and checking code is
tools/answer_keys', used as it is.

- defs.py: the spots. Twelve have answers known without a solver (closed form, or
  obvious); eight are realistic, four of them with the ranges the app itself builds from
  a betting line (app/solver/ranges.py).
- build.py: definitions to SPOT files.
- solve.py: solving a spot to a tight target, the RESULT file, and the numbers for
  docs/research/RIVER_SOLVER.md.
- known.py: reading the known answers (bluff share, call share, value) out of a RESULT.
- compare.py: checking another solver's answer against the saved one, by value and bounds.
- __main__.py: python -m tools.reference_spots --help

See data/reference_spots/python_solver/README.md and docs/research/RIVER_SOLVER.md.
"""
