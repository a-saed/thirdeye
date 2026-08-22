# Third Eye — SVG assets

## Files
icon-*            ring mark, use at 24px and above
favicon-*         solid hexagon with knockout node, use at 20px and below
lockup-*          icon + wordmark + descriptor

Each in teal (#45C9A5), white (mono light-on-dark), and black (mono dark-on-light).

## Geometry
Pointy-top hexagon, viewBox 100 x 115.47 (ratio 1 : 1.1547).
Ring stroke 8% of width. Node diameter 0.30 of width, on centre.
All shapes are fills with fill-rule="evenodd" — no strokes, so scaling never
changes line weight and the mark stays a single path per colour.

## Favicon
<link rel="icon" href="thirdeye-favicon-teal.svg" type="image/svg+xml">
The knockout is transparent, so it picks up whatever sits behind it.
Ship a 32x32 PNG fallback from the ring version for older browsers.

## Wordmark type
The lockup SVGs use live <text> in IBM Plex Sans 400/600 and IBM Plex Mono 400.
That renders correctly only where those fonts are installed. Before sending the
lockup outside the team, outline the text (Illustrator: Type > Create Outlines;
Figma: Outline stroke / flatten) and re-save.

## Clearspace
Half a hexagon width on all sides. Minimum lockup width 120px; drop the
LOCATION INTELLIGENCE descriptor below 160px.
