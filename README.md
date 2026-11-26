# diagrun (machin)

Where did your Claude Code tokens go? Agent-first and CLI-first: one native
binary, JSON on stdout, optional HTML report on [hart](https://hart.intrane.fr).

**[Site](https://javimosch.github.io/machin-claude-diagrun/)** ·
**[Original project: diagrun](https://github.com/Francoisnollet/diagrun)**

## Origin

Inspired by [diagrun](https://github.com/Francoisnollet/diagrun) by François
Nollet (MIT), a zero-dependency Node CLI. This is a new implementation in
machin, **not a clean-room one**: its source was read first, and the task-class
rules, their patterns and several thresholds are adapted from it. See
[LICENSE](LICENSE).

```sh
./build.sh
bin/diagrun guide
bin/diagrun scan --days 7                 # JSON
bin/diagrun report --days 30              # ~/.diagrun/report.html
bin/diagrun report --publish --owner you  # upload to hart (unlisted)
HART_READ_KEY=... bin/diagrun report --examples --publish --owner you --private
```

Agents working in this repo: see [AGENTS.md](AGENTS.md) and the
[diagrun skill](.claude/skills/diagrun/SKILL.md). They ask before publishing.

## Differences from the original

- Prices per model generation, including Fable, with 5 min and 1 h cache writes.
  Unknown models are listed as unpriced.
- Subagent spend is reported separately and never counted as part of a prompt.
- A message copied into a resumed transcript is billed once.
- Model savings have two figures: whole sessions that could have started on a
  cheaper model, and a per-prompt ceiling that ignores cache rebuilds.
- A re-read counts only for the same range with no edit in between.
- No prompt, path or command in any output unless `--examples` is given, and
  those cannot be published without `--private`.

## Cache-write breakdown

`cache_writes.rows` splits `parts.cache_write` by cause: `first_request`,
`growth`, `rebuild_idle_expired`, `rebuild_model_switch`,
`rebuild_context_shrunk` (compact, clear or rewind) and `rebuild_unexplained`.
A rebuild needs more than 2000 tokens, and more than 10% of the previous
prompt, not read back. These are inferences from token counts and timestamps.
A window that started before the `--days` cutoff shows its first request
inside the period as `first_request`.

`cache_writes.idle` splits the idle rebuilds by pause length and trigger (the
user lines between the two requests): `typed_prompt`, `command_or_interrupt`,
`question_answered`, `tool_result_or_approval` (a slow tool or a pending
approval), `background_task`, `agent_message`, `scheduled`,
`after_scheduled_wakeup`, `agent_instruction` (subagents), `system_injected` and
`no_new_input`. Only known markers are matched and they are not verified against
a format specification: `typed_prompt` may include scripts or unrecognised
schedulers. Events logged under line types other than user/assistant are not
seen.

## Limits

- Prices are hardcoded in `src/pricing.src` (cached 2026-11-03). Cache-read
  prices for models older than the 5.5 / 5.2 generation are assumed 0.1x input.
- Classification is a French/English keyword heuristic.
- Tests use synthetic transcripts. It has also been run on real ones, but its
  trigger markers are not verified against a format specification.
- Needs [machin](https://github.com/javimosch/machin) and a C compiler to build.
- [cli-specs](https://cli-specs.intrane.fr/): `output` and `guide` adopted
  (`cli-spec-conformance` passes all its checks for both). `feedback`, `update`
  and `install` are not implemented; there is deliberately no telemetry.

## Tests and memory

```sh
tests/capped.sh python3 tests/run.py
```

machin frees memory only when a goroutine returns or an `arena` block ends. The
loader therefore uses one goroutine per file and one arena per line. Always run
experiments on large inputs through `tests/capped.sh` (cgroup limit, no swap,
timeout; `CAP=2G LIMIT=300` to adjust). An early version without this exhausted
the development machine.

Files are read in 4 MB chunks, so file size alone no longer drives memory. The
main goroutine still grows with the number of transcript lines. On synthetic
input a single 1.6 GB file peaked at 640 MB under a 1 GB cap (13 s), and a
530 MB one at 296 MB.
