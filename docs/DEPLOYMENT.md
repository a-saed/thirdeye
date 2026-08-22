# Deployment tasks

Not yet deployed. Recorded here so they are not rediscovered later.

## 404 must return a 404 status

`web/src/routes/notfound.tsx` renders a real "that page does not exist" page,
but **the HTTP status is still 200**. A single-page app's history fallback
serves `index.html` for every path, so the server reports success for an
address that does not exist.

For a product whose argument is that it says what it does not have, a 200 on a
missing page is the wrong default. It also lets search engines index every
typo'd URL as a real page.

The fix belongs in the host, not the bundle:

**nginx**

```nginx
location / {
  try_files $uri $uri/ /index.html;
}
# Known app routes rewrite to the SPA; everything else is a genuine 404.
location ~ ^/(report|tokens|compare)$ {
  try_files /index.html =404;
}
error_page 404 /index.html;   # renders the SPA, but with a 404 status
```

**Netlify** — `_redirects`:

```
/report   /index.html   200
/tokens   /index.html   200
/compare  /index.html   200
/*        /index.html   404
```

**Vercel** — `vercel.json` `routes` with `"status": 404` on the catch-all.

Whichever host is chosen, the check is:
`curl -o /dev/null -w '%{http_code}' https://HOST/nope` must print `404`.

## The API is the HTML origin for /report and /compare

Server-rendered meta tags landed for share previews, so those two paths are
**served by the Go API, not by a static host**. Facebook, LinkedIn, WhatsApp
and Slack do not execute JavaScript, so client-side `document.title` never
reached them and every shared report previewed as the generic home card.

Consequences for whatever hosting is chosen:

- `/report` and `/compare` must proxy to the API, which needs `-web` pointing
  at the built SPA directory (`web/dist`).
- Everything else — `/`, `/tokens`, `/assets/*`, the GeoJSON — can still be
  static.
- **JSON moved under `/api`.** It used to sit at the root, which collided the
  moment `/report` had to be a document as well as an endpoint. The dev proxy
  no longer rewrites the prefix.

```nginx
location /api/    { proxy_pass http://127.0.0.1:8080; }
location = /report  { proxy_pass http://127.0.0.1:8080; }
location = /compare { proxy_pass http://127.0.0.1:8080; }
location /         { try_files $uri $uri/ /index.html; }
```

Check: `curl -s 'https://HOST/report?lat=29.96&lon=31.26' | grep -o '<title>[^<]*'`
must show the place and figures, not the generic title.

Not built: a per-location OG **image** endpoint. The text tags carry most of
the value; an image needs a rendering library in Go.

## Other deployment work not yet started

- Hosting for the static bundle and the Go API; the API loads ~142 MB of
  parquet into RAM at startup and must be restarted after each monthly
  pipeline run.
- A scheduler for `pipeline/sources/archive_release.py`. It **must** run
  monthly: Overture's S3 keeps roughly two releases, the community mirror
  lags, and a release missing from both is gone permanently. 2026-06-17.0
  already is.
- TLS, and a domain. The contact link currently points at the GitHub repo's
  issues rather than an address.
