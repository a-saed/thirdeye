# Mobile UX pass — design

Status: approved 2026-09-06. Scope: `web/` presentation only. No API, pipeline
or data changes.

## Why

The responsive pass that preceded this one fixed overflow and touch targets and
declared the job done. Both were genuinely clean, and both were the wrong
measurement. Measured at 375x667 with touch emulation active:

| Route | Length | Finding |
| --- | --- | --- |
| `/report` | 6.4 screens | `.rc-verdict` — the synthesis — sits at 2887px, second to last. 261px of subnav + controls precede any data. |
| `/compare` | 4.4 screens | `.cmp-share` sits at 266px, above the comparison it copies. |
| `/search` | 24.5 screens | footer at 15847px, effectively unreachable. |
| `/` | 1 screen | fixed in the previous pass; map now holds 67% of the viewport. |

`footer.ft` costs 629px — 0.9 of a screen — on every page.

### The finding that matters most

Touch has no hover, and this product carries a great deal of meaning in
`title=`. Measured, per route:

- **`/compare`** — `span.cmp-conf` renders as a 9px `○` whose only carrier of
  meaning is `title="Single source"`. On a phone the confidence encoding on
  that screen cannot be read at all. `span.cmp-dim` (`ⓘ`) and the disabled
  `.cmp-open` are the same shape of problem: the reason the control is
  disabled exists only in a tooltip.
- **`/report`** — 10 distinct hover-only carriers, including the confidence
  badge's explanation, `estimated from res-8` → *"Kontur publishes population
  on res-8 hexagons"*, the `dup?` tag, and the snapshot-gap note.

This is not a styling defect. `docs/DESIGN.md` §9 asks "does every number carry
a confidence indicator?" and "if the screen were printed in greyscale, would
confidence still read?"; `CLAUDE.md` rule 3 says provenance is not optional.
A phone user currently receives the numbers without the caveats. The tokens
file already states the principle for a different reason: *a caveat nobody can
read is a caveat that was not made.*

## Decisions taken

1. **Audience: both, equally.** Design for the field case — someone standing
   somewhere, deciding about this spot — but remove nothing. Promote the
   synthesis; keep every section reachable by disclosure rather than cutting.
2. **Tooltips: hybrid.** Short labels that are currently tooltip-only become
   visible text. Long explanations get a tappable inline note.
3. **Structure: ordered bands + disclosure.** One linear stack per screen,
   ordered by decision value. Rejected: segmented tabs, because they put a
   navigation decision between someone and a link they were sent, and the tab
   state would have to live in a URL that exists to be shared.

## Components

Both are mobile-first in effect; desktop behaviour is unchanged.

### `<Note>`

A 44px `(i)` trigger that expands an inline note **in document flow**, pushing
subsequent content down. No overlay, no anchor positioning, no z-index
negotiation with the map. Replaces long `title=` strings.

- Collapsed: the trigger only.
- Expanded: `--surface-2`, radius 6, `--t-caption`, matching §7's tooltip
  colours so the two read as the same object in different media.
- `aria-expanded` on the trigger; the note gets an id referenced by
  `aria-controls`.
- The `title` attribute is **retained** for pointer users, so desktop hover
  is unaffected.

### `<Disclosure>`

A section wrapper whose summary carries a count or a value — never a bare
"Show more". `Places · 140`, `Trend · 23 snapshots`, `Caveats · 4`.

Rationale: a collapsed section that does not say what it is hiding is how a
caveat gets lost. The count is the honesty mechanism, not decoration.

## Per-route changes

### `/report`

Order becomes:

```
identity  ->  verdict  ->  headline cards  ->  map
          ->  catchment + category controls
          ->  places (disclosure)  ->  series (disclosure)
          ->  provenance (disclosure)  ->  compact footer
```

- `.rc-verdict` moves directly beneath the place name. It is the synthesis and
  it currently arrives last.
- `.rc-controls` moves below the map: they act on the map and the cards, and
  261px of chrome before any data is the wrong opening.
- Sticky bottom bar carries **Copy link** and **Compare** — the two actions
  taken after reading. §7 caps primary buttons at one per screen; Compare is
  the primary, Copy link is secondary.
- Every long `title=` becomes a `<Note>`.

### `/compare`

- `.cmp-share` moves to the sticky bar.
- `.cmp-conf` gains its label inline: `○ Single source`.
- `.cmp-open` in its disabled state gains visible text — *"Choose a location
  for this side first"* — replacing a grey link whose reason was hover-only.
- `.cmp-caveats` becomes a disclosure with a count.

### `/search`

The list stays long: 100 ranked results is the right shape, and trapping it in
a ~250px internal scroller would be worse. Instead a slim **sticky results
bar** — `3,859 cells · top 100 · Filters` — keeps the count, the ranking
metric and the filter toggle reachable at row 80.

### `/`

No structural change; the previous pass settled it. The expanded sheet's
governorate table becomes a disclosure.

### Footer

Compact bar: brand line, "Report an issue", "Design system", and
`Data sources · 7 · ODbL, CDLA, CC BY` as a disclosure summary.

**Licence note.** `Footer.tsx` states that attribution is a licence condition,
not a credit role. The collapsed summary therefore names the licences without
interaction; only the per-source links are behind the tap. This matches what
MapLibre's own attribution control does. Flagged to the owner as a licence
decision rather than a layout one.

## Verification

1. Existing audit — all routes at 375x667, 360x844, 414x896, touch on: zero
   document overflow, nothing clipped, no control missing, every hit area
   >= 44px.
2. **New check** — assert zero elements whose only carrier of meaning is
   `title=`, so this class of defect cannot regress silently.
3. Interaction checks driven over CDP, not inspected: every disclosure and
   note opens, the sticky bars stay in the viewport at scroll depth.
4. Desktop regression at 1280px on every route: order, tooltips and footer
   unchanged.
5. `npx tsc --noEmit` and `npm run build` (which runs the map-style validator).

## Out of scope

Shortening the search results list; any change to API responses; the 9px
decorative glyphs (`.cb-glyph` is `aria-hidden`); code-splitting the 1.27 MB
bundle.
