# Third Eye — design system

The visual half of the project's honesty rules. `CLAUDE.md` governs what the
numbers may claim; this file governs how they may look. Every screen cites it.

Implementation lives in `web/src/tokens.css`. This file is the specification —
if the two disagree, this file is wrong and should be corrected, not the CSS
quietly forked.

Preview: `web/src/routes/tokens.tsx`, served at `/tokens`.

---

## 1. The thesis: luminance encodes confidence

Dark, single mode. Not a toggle, not a preference — dark is the product.

The reason is not taste. Third Eye's central measured fact is that **66% of
inhabited cells are single-source and 22% have no business data at all**. A
product that must display that honestly, on every screen, cannot rely on
badges and footnotes to carry it. So confidence is carried by *brightness*:

| confidence | reads as | on screen |
|---|---|---|
| no data | absence | recedes into the canvas, barely separable from it |
| single source | present but unlit | sits mid, calm, no alarm |
| corroborated | evidence | the brightest thing in its region |

On a light theme this inverts and breaks: "no data" would have to be rendered
*darker* than real data, i.e. as ink, i.e. as the most visually assertive thing
on the page. Absence would look like emphasis. Dark is the only mode where
absence and dimness are the same gesture.

**Consequence for every screen:** if you find yourself adding a warning icon, a
red state, or an exclamation mark to communicate uncertainty, the design has
failed. Turn the brightness down instead.

---

## 2. Tokens

Defined in `web/src/tokens.css` as custom properties on `:root`. Never
hard-code a hex outside that file.

### Surfaces

| token | value | use |
|---|---|---|
| `--canvas` | `#101315` | page background, map ground |
| `--surface` | `#191D21` | panels, sheets |
| `--surface-2` | `#22272B` | cards on panels, inputs, table stripes |
| `--surface-3` | `#2C3236` | hover state for surface-2, dividers with weight |
| `--border` | `rgba(255,255,255,0.08)` | **hairlines only** |

Never pure black. `#000` makes a map read as a hole punched in the screen —
the basemap's own water and land polygons are lighter than it, so the
un-styled ground would advance in front of the data.

`--border` is an alpha white, never a solid grey, so a hairline sits correctly
on canvas, surface and surface-2 without three separate tokens. Hairlines only:
**a solid 1px grey border anywhere is a bug.** Separation comes from surface
elevation, not from outlines.

`--surface-3` is added to the starting palette because `#2C3236` was doing two
unrelated jobs — it was specified as `no-data`, and a hover state for cards
needs the same step above `--surface-2`. They are the same value but different
meanings, and a future adjustment to one must not silently move the other.

### Text

| token | value | contrast on canvas | contrast on surface-2 | use |
|---|---|---|---|---|
| `--text` | `#E6E9EC` | 15.30 | 12.37 | numbers, headings, anything load-bearing |
| `--text-muted` | `#9BA3AA` | 7.29 | 5.90 | labels, units, secondary rows |
| `--text-faint` | `#868F96` | 5.67 | 4.58 | captions, provenance lines, table headers |
| `--text-disabled` | `#6C757C` | 3.97 | 3.21 | **non-informational only** |

**Adjusted from the starting palette, with reason.** `text-faint` was specified
as `#6C757C`, which measures 3.97:1 on canvas and 3.21:1 on surface-2 — under
the 4.5:1 floor for body text on both. Provenance strings, `as_of` dates and
confidence captions are exactly the text this token is for, and they are the
text this product least tolerates being unreadable: a caveat nobody can read
is a caveat that was not made. Raised to `#868F96`, which clears 4.5:1 on both
backgrounds.

The original `#6C757C` is kept as `--text-disabled` for genuinely
non-informational use — inactive controls, placeholder text, decorative
separators. **Never use it for a sentence a user needs to read.**

### Data colours

| token | value | meaning |
|---|---|---|
| `--accent` | `#45C9A5` | corroborated. **One accent, reserved.** |
| `--amber` | `#D8A33F` | single source |
| `--no-data` | `#2C3236` | no data |

`--accent` is reserved for corroboration and for the primary action on a
screen. It is not a brand colour to be sprinkled. If teal appears next to a
number, that number is corroborated — that association is the whole point and
it is destroyed by decorative use.

There is deliberately **no red token.** Nothing in this product is an error
state. A cell with no data is not a failure, it is a measurement. See §3.

### Spacing, radius, motion

- **Spacing: 4px base.** Use 4 / 8 / 12 / 16 / 24 / 32. Nothing between.
- **Radius: 8px cards, 6px controls.** Badges are pill (`999px`). The map is
  square-cornered — it is the ground, not an object.
- **Motion: 120ms ease-out** for state changes, 240ms for anything entering.
  No motion on numbers changing — a value that animates is a value being
  performed at the user. Numbers cut.

---

## 3. The confidence colour rule

**The most important rule in this file.**

| confidence | map fill | text | badge |
|---|---|---|---|
| corroborated | `--accent` @ 0.85 | `--text` | small positive badge, teal |
| single source | `--amber` @ 0.38 | `--text` | quiet amber badge |
| no data | `--map-no-data` @ 0.58 | `--text-muted` | grey badge, recedes |

Map fills use `--map-no-data` (`#3F4A52`), not `--no-data` (`#2C3236`). A badge
composites over `--surface-2`; a map fill composites over the veiled basemap.
Reaching the same perceptual position against a different backdrop requires a
different value, so there are two tokens. Everything else is shared.

### Single source is not a warning

66% of inhabited cells are single-source. If single-source is styled as a
problem, **the product looks broken everywhere it works.** The user's
impression after ten seconds would be that the data is bad, when in fact
single-source is the normal, expected, usable state for two thirds of the
coverage area.

So amber is used at low intensity, never with an icon, never with a border,
never with the word "warning", "caution", "limited" or "poor". It sits
*calmly beside* the number — same baseline, never above it, never in front of
it. The number is the subject; the confidence is an adjective.

Forbidden for single source: `⚠`, `!`, red, orange-red, bold weight, uppercase,
a coloured background stronger than 0.16 alpha, and any copy that implies the
number should be distrusted rather than qualified.

### The alpha ladder, and why it is not the hue

Measured relative luminance of the two hues:

```
--amber   #D8A33F   L = 0.4115
--accent  #45C9A5   L = 0.4576   contrast between them: 1.10
```

They are near-isoluminant. **As raw hues they do not deliver the brightness
ladder §1 depends on** — the distinction is carried entirely by hue, which
fails for colour-vision-deficient users and fails again in a screenshot pasted
into a monochrome deck.

The ladder is therefore produced by **alpha**, not by picking different hues.

**Measure against the real backdrop.** On a map the fill is never seen against
bare `--canvas` — it sits on the veiled basemap (§6): 0.45 `--canvas` over Dark
Matter's own `#0e0e0e` background, read from the published style. That ground
measures **L = 0.0052**. Composited against it:

```
ground (veiled Dark Matter)             L = 0.0052
no data        --map-no-data @ 0.58     L = 0.0304   ( x5.9  over ground  )
single source  --amber       @ 0.38     L = 0.0700   ( x2.30 over no-data )
corroborated   --accent      @ 0.85     L = 0.3296   ( x4.71 over single  )
```

**Monotonic is necessary but not sufficient. The ladder must also survive
area.** The first version of this ramp was monotonic — corroborated measured
2.48× single-source — and still read backwards on the map, because
single-source at 0.55 covered two thirds of the extent as a solid mustard
field. A large mass of mid-luminance warm colour is *louder* than scattered
brighter cells. The most common and least verified class was the most
assertive thing on screen.

So the rule is: **the class with the least evidence must never dominate the
composition.** Single-source is 66% of inhabited cells; its alpha is set low
enough that its total ink stays below corroborated's despite covering far more
ground. Corroborated is now 4.71× single-source, not 2.48×.

**These alpha values are load-bearing.** If a screen needs a different
intensity, change all three, and re-check *both* that the ladder is monotonic
*and* which class dominates by area.

**Hue is not the lever, and cannot be.** A warm fill over a near-black ground
composites toward brown as a matter of arithmetic: the current amber lands at
hue 39.4°, a deliberately cleaner amber (`#E8BC5A`) at 42.0°. Two and a half
degrees. What changes the reading is mass — dropping alpha 0.55 → 0.38 takes
the composited fill's value from 0.49 to 0.36. Do not try to fix a too-loud
class by hunting for a better hue.

The hues are kept because teal/amber is a blue-yellow pair, which survives
deuteranopia and protanopia — the two common forms — where a green/red pair
would not. Hue is the *secondary* channel; it is chosen to be safe, not to be
the primary encoding.

### Redundant encoding is required

Because the ladder can be flattened by a screenshot, a projector, or a user's
display settings, **confidence is never signalled by colour alone.** Every
confidence indicator carries a second, non-colour channel:

- corroborated — filled dot `●`
- single source — hollow ring `○`
- no data — horizontal dash `–`

A badge is glyph + label + colour. Drop the colour and it still reads.

---

## 4. Type

**One family.** System UI stack — no webfont, because the app must render
correctly with no network beyond the basemap, and a FOUT on a number is worse
than a slightly different grotesque.

```
ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto,
"Helvetica Neue", Arial, sans-serif
```

**Tabular figures are required on every numeric.** `font-variant-numeric:
tabular-nums`. This is not polish: the time-series scrubber changes values in
place, and proportional digits make columns shift as the user drags, which
reads as the layout being unstable and makes two adjacent values hard to
compare. Any element that can display a digit gets the token.

### Scale

Four sizes. Nothing else.

| token | size | line-height | use |
|---|---|---|---|
| `--t-caption` | 12px | 18px | captions, provenance, table cells' secondary lines |
| `--t-body` | 14px | 22px | body, labels, table cells |
| `--t-head` | 18px | 26px | section headings, emphasised values |
| `--t-hero` | 26px | 32px | the one number a screen is about |
| `--t-eyebrow` | 11px | — | uppercase structural furniture only, never running text |

**Raised one step on 2026-08-21**, from 11/13/16/23. The original was sized
against a spec page rather than a dense data screen: nearly every caption on
the report card is `--text-faint` at the smallest size, which put the caveats
carrying this product's honesty among the hardest things on it to read. A
caveat nobody can comfortably read is a caveat that was not made — the same
argument that raised `--text-faint` off the contrast floor.

`--t-eyebrow` exists so the raise did not drag 10px column labels along with
it. It is furniture — "ALL / INHABITED", "CATCHMENT" — and never a sentence.

23px is a *singular* size — one per screen, at most. If two numbers are both at
23px, neither is the answer.

### Weight

**Two weights only: 400 and 500.** No 600, no 700, no italics.

500 marks the load-bearing element in a group — nothing more. Emphasis in this
product comes from brightness and size, not from weight; a bold caveat reads as
shouting, and the caveats here are numerous enough that shouting them would be
unbearable.

### Case

**Sentence case everywhere.** Headings, buttons, labels, table headers, badges.
No `text-transform: uppercase` — except the two eyebrow labels already in use
for column headers, which are 10px/`--text-faint` and act as structural
furniture rather than language.

Never all-caps a word to create emphasis.

---

## 5. Numbers

Rules that follow directly from `CLAUDE.md`, expressed visually.

- **A number never appears without its confidence.** Not "usually" — never.
  There is no component that renders a bare value, the same way `api/types.go`
  has no path returning a bare `float64`.
- **Percentages carry one decimal**, always. JSON round-trips `66.0` as `66`,
  and "66%" beside "22.3%" reads as more precise than its neighbour rather than
  less. Format at the boundary, not at the source.
- **`as_of` sits with the value**, in 11px `--text-faint`, not in a tooltip.
  Population is a 2023 vintage served in 2026; that must be visible without
  interaction.
- **Stale values** are not recoloured. They keep their confidence colour and
  gain a `–` prefix on the `as_of` line. Staleness is a property of the
  vintage, not of the confidence, and mixing them would corrupt the ladder.
- **Never render a missing value as `0`.** Missing is `–` in `--text-muted`.
  This is the same distinction the pipeline enforces between `unavailable` and
  a count of zero, and it is the single easiest place for the UI to lie.
- **Two denominators appear side by side** wherever a coverage share is shown,
  full polygon dimmed (`--text-faint`) and inhabited-only in `--text`. Neither
  is honest alone.

---

## 6. Map

**Basemap: CARTO Dark Matter**, keyless.

```
https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json
```

Desaturated further, and its labels dimmed, by a **veil**: a `background` layer
in `--canvas` at 0.45 opacity inserted above every basemap layer and below every
data layer. One layer, applied uniformly, rather than walking dozens of
imported layers and setting paint properties on each — which drifts every time
CARTO republishes the style.

**The hexes are the only saturated thing on screen.** Everything else — chrome,
basemap, text — is neutral. If a second saturated colour appears anywhere, the
confidence encoding has lost its monopoly on attention and the map stops
communicating.

Map rules:

- **Cell borders**: `rgba(255,255,255,0.10)`, hairline, and only above z9.
  Thousands of outlines at city scale is texture, not information.
- **Hover**: a 1.6px `--text` outline on the hovered cell. No fill change —
  changing the fill would change the confidence reading under the cursor.
- **"No data" must be perceptible as a class.** It recedes, but it does not
  vanish — at `#2C3236` @ 0.40 it measured 2.4× the veiled ground and read as
  *nothing here*, which is the opposite of *we don't know*. That distinction is
  the entire point of the class, and it covers 22% of inhabited coverage.
  Floor: **≥5× the ground luminance**, while staying below single-source.
- **Uninhabited cells** render at roughly a third of the inhabited alpha rather
  than being hidden, so the served city reads as figure and the dilation ring
  and farmland as ground. A toggle hides them outright.
- **`zoom` may only feed a top-level `step` or `interpolate`.** Wrapping one in
  a `case` makes the whole paint property invalid and MapLibre rejects the
  entire `addLayer` call — the map goes blank rather than degrading. Put
  `interpolate` outermost and per-feature `case` in the stop outputs.
- **A failed layer must surface in the UI**, not only the console. A blank map
  reads as "no data", which in this product is a meaningful and wrong message.

---

## 7. Components — behavioural spec

No implementations yet. These are the contracts.

**Metric card.** Value at 16px or 23px `--text`, tabular. Label above at 11px
`--text-faint`, sentence case. Confidence badge on the value's baseline, right.
`as_of` and contributing sources on an 11px line beneath. Background
`--surface-2`, radius 8, no border. Never a bare value.

**Confidence badge.** Pill, 11px, glyph + label. Background is the confidence
colour at 0.16 alpha; text is the confidence colour at full chroma, except
no-data, which uses `--text-muted` — full-chroma `--no-data` on its own tint
measures 2.70:1 and is unreadable.

**Buttons.** Primary: `--accent` fill, `--canvas` text, radius 6, 500 weight.
One per screen. Secondary: `--surface-2` fill, `--text`, hairline border.
Ghost: no fill, `--text-muted`, brightens to `--text` on hover. No destructive
variant — nothing here destroys anything.

**Panel.** `--surface`, radius 8, hairline border, 14/16 padding. Scrolls
internally rather than growing past the viewport.

**Table.** 13px cells, 11px `--text-faint` headers, numerics right-aligned and
tabular. Row separation by `--border` hairline, not by zebra fill. Sort
indicators are glyphs, never colour.

**Tooltip.** `--surface-2` (not black — black is the canvas and would vanish
into the map), radius 6, 11px, `--text` on key/value rows with keys in
`--text-faint`. Never contains a control.

---

## 8. Icon

`web/public/brand/` — nine files: `favicon`, `icon` and `lockup`, each in
`teal`, `white` and `black`. Usage notes in `docs/BRAND-ASSETS.md`.

A pointy-top hexagon with a node on centre: a bounded region with a point
fixed inside it, which is what every number in this product is. viewBox
100 × 115.47. Ring stroke is 8% of width, node diameter 0.30 of width. All
shapes are fills with `fill-rule="evenodd"` and no strokes, so scaling never
changes line weight.

**Two variants, hard switchover at 20px.**

| size | variant | why |
|---|---|---|
| ≤ 20px | `favicon-*` — solid hexagon, knocked-out node | the ring's 8% stroke closes up at favicon size |
| ≥ 24px | `icon-*` — ring plus separate node | the ring reads, and is the better mark |

The favicon knockout is *transparent*, not filled with `--canvas`: it takes
the colour of whatever tab bar sits behind it, so one file works on light and
dark chrome.

### No literal eye imagery

No iris or pupil rendering, no lashes, no lids, no almond shapes.

**A geometric node inside a bounded region is fine.** The rule is about
association, not geometry. A hexagon with a centre node reads first as a
coordinate fix — a point located within a cell — and the eye is a
second-order reading that suits the product name. What is prohibited is
depicting an actual eye, which would put surveillance in front of the
location fix rather than behind it. This tool observes buildings and business
listings, not people.

### Wordmark

The lockups' wordmark is **outlined paths, not live `<text>`.** They shipped
referencing IBM Plex Sans 400/600 and IBM Plex Mono 400; on any machine
without those fonts the browser silently substitutes a generic sans and the
tracking, weight contrast and total width all change. Outlining removes the
font dependency, which is what lets the app UI stay on the system stack
(§4) with no webfont.

**IBM Plex is brand type only. It is not a UI font here** — it appears solely
inside the outlined lockup, at display size. Do not add it to `--font`.

Clearspace is half a hexagon width on all sides. Minimum lockup width 120px;
drop the LOCATION INTELLIGENCE descriptor below 160px.

### Constraints for any future mark

No text, no gradients, no strokes thinner than 1/16 of the viewBox — they
disappear at 16px. A generated seven-cell H3-parent mark was tried and
retired for exactly that: at 16px the children blurred into grey mush and only
the accent cell survived.

---

## 10. Copy

The panel orients, it does not sell. **The map is the argument** — a claim the
user can see demonstrated beats a claim asserted next to it.

1. **Category first.** Say what kind of thing this is in the opening words.
   "Location intelligence from open data", not a question or a promise.
2. **One concrete claim, not a stack of benefits.** Three benefits read as
   none; a reader skims a list and retains nothing.
3. **No persuasion verbs, no rhetorical questions, no metaphor.** "Discover",
   "unlock", "Is this a good place to open?" and anything with a flourish are
   all out. This product's credibility rests on sounding like a measurement.
4. **Never name a city in the pitch.** Third Eye is a method that runs wherever
   open data exists; a place name in a sentence turns it into a local utility
   and makes adding a region a copy rewrite. Coverage is the status chip, and
   the live list comes from `pipeline/config/regions.json`.
5. **Tie the differentiator to something on screen.** "Where the record runs
   out, the map stays grey" works because grey cells are visible in the legend
   directly beneath it. An unverifiable claim about honesty is just marketing.

### Where the sharper line goes

Metadata, not the panel. `<title>` and the meta/OG description may be more
pointed than on-screen copy — they compete for attention in a search result or
a shared link, where there is no map to do the arguing.

---

## 9. Checklist for a new screen

1. Does every number carry a confidence indicator?
2. Does single-source look calm — no icon, no border, no alarm copy?
3. Is the brightness ladder intact, and monotonic?
4. Are all numerics tabular?
5. Is teal used only for corroboration and the one primary action?
6. Are missing values `–` rather than `0`?
7. Is `as_of` visible without interaction?
8. Are there exactly zero solid grey borders?
9. Is there at most one 23px number?
10. If the screen were printed in greyscale, would confidence still read?
11. Does the copy obey §10 — category first, one claim, no persuasion, no city?
