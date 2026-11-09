# Notes for AI agents

A small Python desktop app (Tkinter) that reads ITGmania's song cache and a player's Stats.xml, shows
them in a sortable, filterable table, and can build .CRS course files. Read README.md first.

## Who you are working for
- The owner is not a developer and decides the look and feel. Explain in plain language first, then
  give the full technical detail. Never leave out relevant detail to keep it simple.
- Several LLMs work on this repo, each as both developer and reviewer. Write code the next reader
  can follow without asking the model that wrote it.

## Code rules
- Python only. Standard-library code and widely used, maintained Python packages are fine; other
  languages, build steps, code generation and clever metaprogramming are not, unless the owner agrees.
- If you add a package, say what it is for, list it in README.md (and requirements.txt), and prefer
  packages that install with plain pip on Windows. Do not limit a useful feature to avoid a dependency.
- Keep logic that does not need the window in library_data.py (no Tkinter) with tests in tests/.
- Prefer small, single-purpose functions and clear names. Comment only where a passage's purpose or
  ordering could be misread. Documentation lives in README.md; update it when behavior changes.
- Features that need data most users lack (for example the notes repo's modeled-difficulty JSON)
  must be optional, toggleable or a plugin.
- If more than one reasonable approach exists, describe the options briefly (what it is, effect on
  readability, dependencies, and what the user sees), recommend one, and wait for the owner's choice.
  Do not build them all. If an option uses a non-Python language or a new dependency, include a
  Python-only option. If only one conventional approach exists, proceed and say which in one sentence.

## Workflow
- Never commit to main without the owner's explicit say-so. Use a one-use branch per task and open
  a pull request; another LLM reviews it, and only the owner merges.
- Ask the owner before committing to this repo, once per branch, unless the owner has said not to.
- Some changes get a design proposal first: a numbered document in docs/proposals/, reviewed like a
  pull request and marked Accepted by the owner before implementation. Write one when a change
  creates or alters a component boundary or constructor contract, persists a new settings key or
  file format, or has two or more defensible designs where the choice constrains later work.
  A change that applies a design an accepted proposal already settled needs no new proposal; its
  pull request cites that proposal instead. Everything else goes straight to implementation with
  the issue as the spec.
- In the pull request, say in plain language what changed and why, how you checked it, and which
  model wrote it. When a real design choice existed, say which option was taken and which was
  rejected.
- Reviewing: report findings to the owner first and get confirmation before making fixes. Explain
  the real effect of each issue and order by importance. Say which findings you ran and which you
  only read.
- Interface changes: give a text mockup or narrative description; the owner approves look and feel.

## ITGmania behavior
- Do not answer from memory. Read https://github.com/wolfemian-del/itgmania-notes (INDEX.md first),
  then the ITGmania source if the notes do not cover it.
- Version basis is ITGmania v1.3.0 stable. Beta behavior is unverified unless a note says so. If a
  note shows beta differs in something the viewer depends on, tell the owner before changing the viewer.
- Tag technical claims: [CODE] (file and function), [INFERRED], [UNVERIFIED], [RAN] (you executed
  it in your sandbox: name the test or script and the Python version), [TESTED]/[OBSERVED] (the owner
  ran or saw it). Never present an inference as fact.
- .CRS files: follow the notes' course format reference (cref). Do not write what the notes say the
  game ignores or mishandles. If existing viewer code already writes something of that kind,
  report it to the owner as a finding; do not change it until the owner confirms.

## Running and checking
- Run: python library_visualizer.py (Python 3.10+; the owner uses 3.14 on Windows 11).
- Tests: python -m unittest discover -s tests
- Many sandboxes have no Tkinter or display. If you cannot open the window, say so and list checks
  the owner can run.

## Privacy
- This repo is public. Never commit tokens, Stats.xml, real cache files or personal paths. Put small
  synthetic sample data in tests/fixtures/.
