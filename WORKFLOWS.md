# WORKFLOWS.md — how I work with coding agents

Not about this take-home — about my day-to-day. The short version: **agents write almost all
the code; I spend my time designing contracts, gating scope, and reviewing.**

## Tool stack
- **Claude Code (Opus)** as the primary driver, in the terminal and IDE. It's where ~90% of
  my code is written.
- **Plan mode** for anything non-trivial: the agent researches, writes a plan to a file, I
  approve/edit before a line of code is written. This is my main steering wheel.
- **A second-opinion model** (Codex / a different frontier model) for adversarial review of
  diffs and "try to break this" passes — catches things one model's blind spots miss.
- **MCP servers** I lean on: a headless-browser/Playwright server for live QA and crawling,
  GitHub (PRs/issues/CI), and a filesystem/search server. I add project-specific MCP tools
  when a workflow repeats.
- **Custom skills / slash commands** for the workflows I run constantly: schema-first
  scaffolding, "review this diff for X," QA-and-fix loops, and ship/PR flows.

## Delegation patterns
- **Contracts before code.** I have the agent define the data contract first (JSON Schema,
  types, validators) and make it executable, then build to it. It collapses the "looks right
  but is wrong" failure mode — the contract is the spec and the test. (This whole take-home is
  built that way: schema + cross-record validators are the gate every later phase must pass.)
- **Step gates.** One vertical slice at a time with an explicit "don't build X yet," and a
  verification command list that must pass before moving on. Keeps a long autonomous run from
  drifting.
- **Fan-out for research, single-thread for writes.** I'll spin up parallel read-only agents
  to survey a codebase or compare options, but keep mutation on one thread with a clear plan.
- **Self-verifying loops.** Generate → validate against a real gate → feed errors back → retry.
  I'd rather the agent prove it passed a check than tell me it did.

## What I let agents drive vs. always take the wheel on
**Agents drive:** implementation, tests, refactors, boilerplate, first drafts of docs, and
mechanical migrations. If there's a deterministic check (`validate`, `pytest`, a type checker),
I let the agent iterate against it unattended.

**I take the wheel on:** the data model and interface boundaries; scope (what's in/out of this
change); anything irreversible or outward-facing (prod, migrations, deletes, sending email);
and the honesty bar — I will not ship a confident-looking artifact built on evidence the tool
never actually observed. I also personally review the one diff that matters most in a change,
even when the rest is rubber-stamped.

## Principles
- **No slop.** A green check beats a confident paragraph. If I can't cite it, it doesn't ship.
- **Make the human surface shrink.** Every recurring correction should become a lint rule, a
  validator, or a skill — asked once, never again.
- **Cheap, fast feedback first.** Deterministic gates before LLM judgment; LLM judgment before
  a human. Reserve human attention for taste and irreversibility.
