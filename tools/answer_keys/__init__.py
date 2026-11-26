"""Answer keys for the PokerScribe river and turn solvers (data/answer_keys/README.md).

- spots.py: the spot format (data/SPOT_FORMAT.md): read, check, hash, and the betting tree
- spot_defs.py: the 40 spots, written by hand
- texassolver.py: a spot as a TexasSolver config, running it, and reading its output
- result.py: the RESULT format the parsed answers are saved in
- checks.py: the "expected" checks of the trivial spots, and our own exploitability check
- __main__.py: the command line (python -m tools.answer_keys --help)

TexasSolver (AGPL-3.0) is only ever run as a separate program from its config files. None
of its code, binaries or output files are kept in this repo; only our parsed results are.
"""
