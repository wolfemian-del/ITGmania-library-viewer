<!--
Template for design proposals. Copy this file to
docs/proposals/NNNN-<slug>.md with the next number, fill it in, and
delete this comment and the other guidance comments before opening
the docs PR.

Why the prompts in §§1–4 ask about boundaries and coupling: proposal
0005's subject (the distribution panel) was built from a proposal
that never reached the repo, before the project's modularity and
comprehensibility principles existed, and disentangling it afterward
cost a survey, a proposal, two revision rounds across five review
reports, and three staged PRs. These prompts exist so a major change
is born modular instead of disentangled later. Keep the filled
proposal lean — answer the prompts; do not add ceremony.
-->

# Implementation Proposal: <Title>

| | |
|---|---|
| **Status** | Draft — for review |
| **Author** | <model name and version> |
| **Date** | <YYYY-MM-DD> |
| **Base** | main `<short sha>` (<what landed last that matters>) |
| **Related** | <issues, earlier proposals, the sequence this belongs to> |

<!--
When the owner accepts, before implementation:
1. Change Status to: Accepted — approved by the owner on <date>,
   with the review resolutions below.
2. Where §7 has questions, add a "## Review resolutions (<date>)"
   section here recording each open question's outcome and any
   amendments reviewers required, and retitle §7
   "Open Questions — Resolved". If there were no genuine questions,
   delete §7 instead of filling it in.
3. When review changes the text, record the changes in a
   "## Revision N (<date>, from <source>)" section at the top, so
   later reviewers read the corrected draft, not the errors.
-->

---

<In plain language, three to six sentences: what changes, what the
owner would notice (nothing, ideally, for a refactor), and the one
real decision in this proposal. Written for the owner, who decides
look and feel and does not read code first.>

## 1. Background and Goal

<Why now, what sequence or issue this serves, and what "done" means.
State the modularity question up front: does this change create a
new component boundary, move one, or add coupling across an existing
one? If it adds a feature, name the component it belongs to and the
boundary it will live behind — now, not in a later split.>

## 2. Current State (measured on main `<short sha>`)

<The relevant code as it is today: sizes, call sites, inputs, who
reads what. Every load-bearing number comes from a measurement or a
grep, not from memory — reviewers will check. Include a coupling
inventory: lines and methods involved, call sites in both
directions, outside references into the code being moved or changed,
settings keys and shared helpers/constants it touches, and untested
paths. (Proposal 0005 §2 is the worked example — that inventory is
what made the split stageable.)>

## 3. The Decision: <the component's contract / the real choice>

<The recommendation, with the reasoning a reviewer needs. Name the
recommendation inside each real choice, and give each defensible
alternative a short statement of what it would mean and why it is
not the recommendation — if a choice is close, say so, so a future
reader can tell a coin-flip from a conviction. Where a contract is
being set (constructor inputs, a settings key, a file format), name
it here and explain the decision; the contract itself is stated in
full in §4, not repeated here.>

## 4. Recommended Design in Detail (Option <X>)

<The design, in the order a reader needs it. State the component
boundary explicitly: what lives inside the new or changed component,
what stays outside, and what it must not reach back into. Give the
constructor contract as an enumerated input list (proposal 0005:
eight inputs). Then apply the legibility test, the project's
standing guideline: state the one-sentence description of the
component that a standalone reader needs first — what it does and
what it is given. If that sentence cannot be written, or the
component cannot be understood from it without holding the rest of
the file in mind, the boundary is wrong, however small the diff.
If this change does not touch a component boundary or constructor
(a constants move, a settings key), say so in one sentence and
describe the design in whatever shape fits; the legibility test
then applies to whatever new function or format the change
introduces.>

## 5. What Does Not Change

<Behaviour, formats, settings keys, and neighbouring components this
proposal deliberately leaves exactly as they are — the list the
implementation is later checked against.>

## 6. Test Plan (for the implementation PR)

<How the implementation PR will prove itself: tests that pin current
behaviour before anything moves, existing tests that move or change,
new tests, the wiring guard for any new optional input, the
full-suite expectation, and the live smoke. If the work is staged
across several PRs, lay the stages out here in order, with what each
one proves. Remember the file lists a move must update (the theme
guard's source list in tests/test_theme.py, the README) — the ones
that have gone stale before.>

## 7. Open Questions for Reviewers

- **Q1.** <The real decision, with the recommendation stated.>
- **Q2.** <...>

---

*Written by <model name and version>. <If AI models reviewed drafts
before this was filed, say so.>*
