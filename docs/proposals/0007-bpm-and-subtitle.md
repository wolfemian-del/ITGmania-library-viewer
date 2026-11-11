# Implementation Proposal: BPM semantics and the Subtitle column

| | |
|---|---|
| **Status** | Accepted (owner, 2026-11-11) |
| **Author** | Muse (Muse Spark 1.3) |
| **Date** | 2026-11-11 |
| **Base** | main `aa1668a` (PRs #118, #120, #124, #125, #126 merged) |
| **Related** | Issues #48 and #49; one shared snapshot-schema bump binds them |

Two small correctness gaps in how the viewer reads a song. The BPM column
shows the game's display value while filtering, sorting and the chart
quietly use the real tempos — and some of those "real" tempos are warps
and zeros that stretch a song's range into nonsense; a chart with its own
timing is read as if it had the song's. Separately, a song's subtitle is
never read at all, so subtitle text ("Remix", "[Extended]") can't be
searched and two songs sharing a title look identical. This proposal
fixes the BPM reading, adds the subtitle as a searchable column that
stays hidden unless a user asks for it, and covers both with a single
snapshot-schema bump so saved libraries rebuild exactly once. The owner
would notice: nothing on screen by default, one "snapshot is invalid or
outdated" rebuild after upgrading, and BPM values that stop lying.

## Revision 1 (2026-11-11, from Grok's review)

Grok reviewed the draft as the sole lane, per the owner's process
decision for this proposal. It verified §2 claim by claim against main
`aa1668a` — every load-bearing measurement ratified — found §3, §4
and §5 consistent with no dropped decisions, and answered §7's three
questions concurring with the proposal's recommendation on each. No
design text changes: §7 is retitled Resolved and records the outcomes.
The review also left two implementation notes that need no text change
because the draft already carries them — the chart-timing fallback
keeps the `parse_bpms(...) or song_bounds` shape (§4), so a warp-only
chart falls back to the song's bounds rather than blanking them; and
§6's pins include the Q2+Q3 composition and the
`DEFAULT_VISIBLE_COLUMNS` exception. Both notes are carried into the
implementation assignments.

## 1. Background and Goal

Issues #48 and #49 were investigated read-only on 2026-11-09/10; the
measurements in §2 are from those investigations, freshness-checked
against current main on 2026-11-11 (no drift — `library_data.py` is
untouched since the checks). The owner made the option decisions on
2026-11-11; §3 records them. "Done" means: both issues' acceptance
criteria met, the schema at 3, and no release shipping the changed
parse behaviour without the bump.

The modularity question, up front: this change creates **no** new
component boundary and alters no constructor contract. Parsing stays in
`library_data.py`, where the repo's rules already put logic that does
not need the window; the column rides the existing `HEADERS` /
`COLUMN_GROUPS` machinery in `library_visualizer.py`. The proposal
exists because the change persists a changed file format (the snapshot
schema) and because both issues offered two or more defensible designs
— two of the three triggers in the workflow rule.

## 2. Current State (measured on main `0c5394b`, re-verified at `aa1668a`)

**The display/real split (issue #48 Q1).** The BPM column is
`format_bpm_display` (`library_data.py`): when a song sets
`#DISPLAYBPM`, the cell shows that (a value, a `lo:hi` range, or `*`);
otherwise it shows the parsed `#BPMS` range. The real bounds are parsed
once per song (`parse_cache_file`) into `bpm_min`/`bpm_max`, and
everything else uses those: the `bpm:` filter, the sort
(`bpm_sort_key` — max first, then min), and the distribution chart.
Probe [RAN]: a song with `#DISPLAYBPM` "150" and a real range of 0–300
displays "150", **matches `bpm:>250`**, and sorts as a 300-max song.
The README does not say the filter uses real tempos.

**Junk tempo values (Q2).** `parse_bpms` takes min/max over **every**
value in `#BPMS`. The issue's three synthetic cases reproduce exactly
[RAN]: `0=150,64=-150` → displays "−150–150"; `0=0,4=150` → "0–150";
`0=150,10=999999` → "150–999999". Knock-ons measured: the warp song
sorts below a plain 150 song at equal max; `bpm:0` matches a 0–150
song; one 150–999999 song is counted in every BPM chart bin its span
touches (by design for honest wide ranges — a matter of degree, not a
separate defect). In the simfile format a negative `#BPMS` value is a
warp, not a tempo, and 0 is not a playable tempo [INFERRED — standard
format semantics]. Whether the owner's real library contains such
songs is [UNVERIFIED].

**Chart-level timing ignored (Q3).** `parse_cache_file` parses BPM once
from the song chunk and stamps the same bounds and display string on
every chart row. It already parses each chart chunk's tags into a
per-chart map (STEPSTYPE, METER, RADARVALUES, …) — it just never looks
for BPMS or DISPLAYBPM there. The engine side [CODE, itgmania-notes
cache-format spec §2c and loadmem §4f]: each chart block in the cache
carries its own timing tags when it has them, and a chart's timing "is
filled only if it has its own timing tags"; `Steps::GetTimingData()`
returns the song timing when the chart's own is empty. The engine's
rule is "the chart's own when present, else the song's." Whether any
cache in the owner's library actually contains chart-level `#BPMS` is
[UNVERIFIED] — the spec was written from source, no real cache
inspected.

**Subtitle unread (issue #49).** There is no `SUBTITLE` reference
anywhere in `library_data.py`; the row takes
`"Title": song_tags.get("TITLE", path.stem)` only. Free-text search
matches a fixed corpus in `match_chart_query` (Title, Artist, Pack,
Chart, Type, Difficulty); the `title:` directive matches `row["Title"]`
only. A ready-made fixture exists and is unused:
`tests/fixtures/routine_subtitle.cache` contains
`#SUBTITLE:(Sunset Mix);`.

**The snapshot.** Parsed rows are saved under
`LIBRARY_CACHE_SCHEMA_VERSION = 2`, checked on load; a mismatch
discards the snapshot and re-parses. Loading also requires every
`HEADERS` key in every saved row, so a new row key invalidates old
snapshots even without a bump — the bump makes the invalidation
deliberate rather than incidental.

**Column machinery.** `HEADERS` lists the table's columns;
`COLUMN_GROUPS` groups them ("Song & chart" holds Title's neighbours);
`DEFAULT_VISIBLE_COLUMNS` is derived from the default-visible groups,
and a column with no saved visibility setting falls back to membership
in that set. So a column can be added to a default-visible group yet
default to hidden via one exception in the derivation, and existing
users get the same default with no settings migration. CSV export uses
`fieldnames=HEADERS`, so a new column reaches the export for free.

**Coupling inventory.** The changed parse outputs (`bpm_min`,
`bpm_max`, the display string, a new `Subtitle` row key) are consumed
by: row display (`format_bpm_display`), the `bpm:` filter, the BPM
sort key, the BPM distribution aggregation, free-text search, and CSV
export. No settings key is added or changed. No other file reads the
snapshot.

## 3. The Decisions (owner's, 2026-11-11)

**#48 Q1 → B: keep real tempos everywhere; document the split.**
Rejected: **A** (filter/sort/chart follow the displayed value) — it has
a hole: `#DISPLAYBPM` can be `*` (the game shows a random-looking
value) or a decorative range chosen for the song wheel, so A still
needs fallback rules and becomes "displayed, except when it isn't,"
harder to explain than B's one sentence; it also changes what clicking
a BPM chart bar selects. **C** (two columns, displayed and real) —
screen width and a second sort/filter semantics to explain, for a
distinction the README sentence covers. Under B the column heading
stays "BPM" — no short heading says "display value" clearly — and the
README's filter section gains one paragraph: the column shows what the
game shows, including `#DISPLAYBPM`; `bpm:`, sorting and the chart
always use the song's real `#BPMS` range.

**#48 Q2 → positive values only.** `parse_bpms` computes its bounds
over positive values only. If *no* positive value exists (a warp-only
`#BPMS`), it returns None and the song is treated exactly like a song
with no usable `#BPMS` today — blank cell (unless `#DISPLAYBPM` is
set), the missing-BPM sort group, never matches `bpm:`, the chart's
"?" bar. One existing missing-data path, not a new one. Very large
values stay as they are, per the issue, until a real library shows a
need. `#DISPLAYBPM` is author-supplied display text and is not touched.

**#48 Q3 → implement the chart-timing override.** In the chart loop,
each tag keys off independently, mirroring the engine: chart `#BPMS`
replaces the bounds (through the same `parse_bpms`, so Q2 composes for
free), chart `#DISPLAYBPM` replaces the display tag, each falling back
to the song's when absent.

**#49 → B: a real Subtitle column, searchable, hidden by default.**
Rejected: **A** (shown by default) — a mostly-empty column widening
everyone's table permanently; most songs have no subtitle. **C**
(searchable only, no column) — smallest diff, but duplicate titles stay
indistinguishable in the table, which is half the issue's complaint.
Under B the column joins `HEADERS` and the "Song & chart" group, is
subtracted in the `DEFAULT_VISIBLE_COLUMNS` derivation, and is opt-in
via View → Columns. The owner's framing: the default view should not
gain another column to hide away, but the column stays *possible* for
whoever wants it. Free-text search gains `"Subtitle"` in its corpus;
the `title:` directive is deliberately **not** extended (see §5).

**One shared schema bump, 2 → 3.** Q2 and Q3 change what parsing
produces and #49 adds a row key; any release shipping either without
the bump would keep serving old values from existing snapshots
silently. One bump covers both; the invariant is release-level — no
release ships the changed parse semantics or the new key without
schema 3.

## 4. Recommended Design in Detail

The legibility sentence for the whole change: *parsing turns a simfile
cache into rows whose BPM bounds are the real positive tempos of the
chart (or the song, when the chart has none) and whose subtitle rides
along as data; the table shows the subtitle only to users who ask for
the column.* Each piece below is understandable from that sentence
plus its own function.

- **`parse_bpms`** (library_data.py): filter to positive values before
  min/max; return None when none remain. One function; every consumer
  (display, filter, sort, chart) is fixed at the same point because
  they all read `bpm_min`/`bpm_max`.
- **`parse_cache_file`** chart loop: per row,
  `bounds = parse_bpms(chart_tags.get("BPMS")) or song_bounds` and the
  display string is built from `chart_tags.get("DISPLAYBPM") or
  song_display_tag` with those bounds — the same shape as the
  song-level code it sits beside.
- **README**: one paragraph in the filter/search section stating the
  Q1-B rule; the subtitle column's group membership and
  hidden-by-default behaviour (issue #49's acceptance criteria ask for
  the README to state it).
- **Subtitle**: `parse_cache_file` adds
  `"Subtitle": song_tags.get("SUBTITLE", "")` beside Title;
  `match_chart_query`'s free-text corpus gains `"Subtitle"`;
  `library_visualizer.py` adds `"Subtitle"` to `HEADERS` and to the
  "Song & chart" group, and `DEFAULT_VISIBLE_COLUMNS` subtracts it.
- **Schema**: `LIBRARY_CACHE_SCHEMA_VERSION` 2 → 3, carried by
  whichever implementation PR merges first; the second PR names it as
  already landed. Staging: PR-1 for #48 (Q2 + Q3 + the README
  paragraph), PR-2 for #49 (column + search + the bump if it has not
  landed). Either merge order satisfies the §3 invariant, because the
  invariant binds releases, not main-branch moments — and #49's
  `HEADERS` check independently invalidates pre-change snapshots.

## 5. What Does Not Change

- `#DISPLAYBPM` handling: author display text is shown verbatim,
  including `*`; Q1-B documents the split rather than moving it.
- Very large tempo values (999999 and kin): parsed and displayed as
  today.
- The `title:` search directive: still matches `row["Title"]` only.
  Free-text search is where subtitle text becomes findable. (Flagged
  for reviewers as §7 Q2 — this is the one place a reviewer might
  reasonably push.)
- The Course Builder: it has its own column list and renders
  `row["Title"]`; no option in issue #49 as written changes it.
  Subtitle disambiguation there is a deliberate non-goal, or a
  follow-up issue if the owner wants it.
- Settings: no key added, removed, or reshaped; column visibility uses
  the existing saved mechanism and its default fallback.
- The snapshot's location and format beyond the version number; the
  `.CRS` course output; every other column's defaults.

## 6. Test Plan (for the implementation PRs)

- **#48 pins**: the issue's three synthetic strings with post-fix
  expectations (`0=150,64=-150` → bounds 150–150, displays "150";
  `0=0,4=150` → "150"; `0=150,10=999999` → "150–999999", unchanged);
  the all-nonpositive case → treated as no BPM (blank cell, missing
  sort group, no `bpm:` match); a new synthetic split-timing fixture
  in `tests/fixtures/` where one chart carries its own BPMS/DISPLAYBPM
  (overrides) and a sibling chart does not (falls back to the song's);
  existing BPM tests keep their expectations for ordinary songs.
- **#49 pins**: parse with a subtitle (the existing
  `routine_subtitle.cache` fixture — its first use) and without
  (empty string); a search test where the term appears only in the
  subtitle; a visualizer test pinning Subtitle default-hidden while
  its "Song & chart" group-mates default to shown; CSV export includes
  the column.
- **Schema**: a schema-2 snapshot is discarded with the existing
  "invalid or outdated" message once the version is 3.
- **Suite expectation**: full suite green under the usual Xvfb run;
  no test deleted or expectation loosened.
- **Owner smoke**: launch after upgrading — one snapshot-rebuild
  message, click Load / refresh; View → Columns shows Subtitle
  available and off; enabling it shows the column. If the owner's
  library has a warp song, its BPM cell no longer shows a negative
  bound [UNVERIFIED whether it has one].

## 7. Open Questions — Resolved

- **Q1.** Is "no positive tempo ⇒ treated as no BPM" the right single
  missing-data treatment, or does any consumer (chart "?" bar, sort
  group) need to distinguish a warp-only song from an absent `#BPMS`?
  Recommendation: the single path — the consumers were audited in §2
  and none distinguishes today.
  **Resolution (2026-11-11): the single path, as recommended.** The
  reviewer confirmed every consumer already treats missing bounds
  uniformly; a distinct warp-only signal is revisited only if a real
  library shows authors relying on one.
- **Q2.** Should the `title:` directive also match Subtitle, or is
  free-text coverage the right scope for this change? The design says
  free-text only (§5); argue it if you disagree.
  **Resolution (2026-11-11): free-text only, as designed.** Widening
  `title:` would silently change the meaning of existing saved
  searches; if a combined directive is ever wanted, it gets its own
  name rather than a widened `title:`.
- **Q3.** The bump's placement: invariant-based (first implementation
  PR to merge carries it) versus fixed to one named PR. Recommendation:
  the invariant as stated in §4 — it is the release, not the branch
  moment, that users upgrade across.
  **Resolution (2026-11-11): invariant-based, as recommended.** The
  implementation PR that does not carry the bump states that the
  schema is already 3.

---

*Written by Muse (Muse Spark 1.3). The measurements in §2 come from
read-only investigations of issues #48 and #49 prepared 2026-11-09/10
and freshness-checked 2026-11-11; the option decisions in §3 are the
owner's, made 2026-11-11. No model reviewed a draft of this proposal
before filing.*
