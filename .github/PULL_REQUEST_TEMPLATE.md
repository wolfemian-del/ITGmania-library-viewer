<!--
PR body skeleton for ITGmania-library-viewer, per AGENTS.md's Workflow
section. Plain language first, then technical detail; never leave out
relevant detail to keep it simple. Delete sections that have nothing to
say rather than filling them with "n/a" — except the attribution line,
which always stays.
-->

## In plain language

<What changed and why, in terms of what the owner would see. For a
refactor: say plainly that nothing about how the app looks or behaves
changes, if that is true.>

## What changed

<The technical summary: files, the shape of the change, anything a
reviewer should look at first.>

## Design choices

- **Taken:** <the option chosen, and the reason in one line.>
- **Rejected:** <the alternative, and why not.>
<!-- If this PR applies an accepted proposal's design: name it and state
     whether this PR departs from it, per AGENTS.md. A departure needs
     its own proposal. -->
<!-- If there was no real choice, write: "No design choice arose." -->

## How I checked it

- <Tests run, with counts and environment: e.g. "265 tests OK, zero
  skips under Xvfb; 3 live-Tk skips headless, as designed".>
- <Live smoke, mutation checks, greps — the evidence, not just the claim.>
- <What was NOT verified, honestly: e.g. Windows-only behaviour.>

## Windows checks

<Numbered checks the owner can run, where behaviour on Windows matters.
Delete this section if the change cannot behave differently there.>

Closes #<issue, when the PR completes one — repeat the keyword per
issue: "Closes #X, closes #Y">.

— <Model name (version)>
