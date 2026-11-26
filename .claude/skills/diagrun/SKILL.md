---
name: diagrun
description: Diagnose Claude Code token usage and cost with this repo's diagrun CLI, and offer an HTML report locally or on hart. Use when the user asks where their tokens or money went, why cache writes are high, or wants a usage report to read or share.
---

# diagrun

`bin/diagrun guide` is the manual (concepts, exit codes via `help-json`). This
file adds how to work with the user.

Transcripts are the user's private data. Use diagrun's output; do not open or
parse `~/.claude/projects` yourself. If a permission check blocks a command,
tell the user and give them the command to run. Do not get the data another way.

## 1. Build and scan

Needs [machin](https://github.com/javimosch/machin) and a C compiler.

```sh
./build.sh
CAP=2G LIMIT=300 tests/capped.sh bin/diagrun scan --days 7 > scan.json; echo "exit=$?"
```

Write `scan.json` outside the repo or delete it afterwards. `tests/capped.sh`
needs Linux with systemd. Without it, tell the user the run has no memory cap
and ask before running. Exit 137 usually means the cap was hit, 124 the time
limit.

Answer from the JSON: the largest costs first. Causes, task classes and triggers
are inferred, savings figures overlap (never add them), and on a subscription
only shares are meaningful.

## 2. Offer HTML only when it helps

Offer it when the user asks for a report, wants to share or keep one, or the
findings are too large for a short answer. A quick question gets a text answer.

Ask where it should go (use your question tool if you have one):

| Choice | Command |
|---|---|
| Local file (default) | `bin/diagrun report --days 7` |
| Private hart (password) | `HART_READ_KEY=... bin/diagrun report --days 7 --publish --owner NAME --private` |
| Unlisted hart (anyone with the link) | `bin/diagrun report --days 7 --publish --owner NAME` |

Run these through `tests/capped.sh` as above.

## 3. Publishing rules

- Publish only after the user says yes to this upload. A request for a report,
  or a clone of this repo, is not permission. A yes does not cover later uploads.
- Ask for `--owner`. Never guess it from git, the OS user or an email address.
- For `--private`, the user provides the password in `HART_READ_KEY`. Do not
  invent one silently, print it or write it to a file in the repo.
- Leave `--examples` out. If the user asks for it, warn that prompts, file names
  and commands (which may contain secrets) will be in the report; it then
  requires `--private`.
- Publishing needs the `hart` CLI, which is not part of this repo. Check with
  `command -v hart`; if it is missing, keep the local file and say so.
- Same owner and `--artifact` (default `diagrun`) adds a version at the same
  address. Say so before replacing a report. If a name is taken or a key is
  required, report the error; do not switch to another owner on your own.
- On success, give the user the `url` from the JSON output and who can open it.
- Do not set up a timer or other automatic publishing unless asked.
