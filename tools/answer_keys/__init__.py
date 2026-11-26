"""Answer keys for the PokerScribe river and turn solvers (data/answer_keys/README.md), and
the harness that checks a solver against them (docs/research/PHASE4.md).

- spots.py: the spot format (data/SPOT_FORMAT.md): read, check, hash, and the betting tree
- spot_defs.py: the 40 spots, written by hand
- texassolver.py: a spot as a TexasSolver config, running it, and reading its output
- result.py: the RESULT format the parsed answers are saved in
- checks.py: the "expected" checks of the trivial spots, and our own exploitability check
- values.py: an answer's EVs, reach and action frequencies, and an exact best response,
  for river and turn spots
- turn_solver.py: an exact turn solver in numpy, the reference answer for the turn spots
- python_solver.py: the Python reference answers (data/answer_keys/python_solver/): river
  spots solved by app/solver, turn spots by turn_solver.py
- compare.py: a solver's answers against a reference, with the Phase 4 gates
- runner.py: run and time any binary that follows the subgame-solve command line
- standin_solver.py: that command line answered by the Python solvers, to test the harness
- __main__.py: the command line (python -m tools.answer_keys --help)

TexasSolver (AGPL-3.0) is only ever run as a separate program from its config files. None
of its code, binaries or output files are kept in this repo; only our parsed results are.
"""
