# Agent instructions

- **Using the tool** (usage and cost questions, HTML or hart reports): follow
  [.claude/skills/diagrun/SKILL.md](.claude/skills/diagrun/SKILL.md). In short:
  never publish without the user's explicit yes, and keep `--examples` off.
- **Developing it:** `./build.sh`, then `tests/capped.sh python3 tests/run.py`.
  Tests use synthetic transcripts only; never develop or test against the
  user's real ones.
- **Memory:** run experiments on large inputs through `tests/capped.sh`,
  starting small. machin frees memory only when a goroutine returns or an
  `arena` block ends; an uncapped early version exhausted a development machine.
  See README, "Tests and memory".
- **Prices** live in `src/pricing.src`.
