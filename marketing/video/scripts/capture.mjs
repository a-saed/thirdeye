// CAPTURE THE LIVE APP, AND REFUSE TO CONTINUE IF IT DISAGREES WITH THE API.
//
// Every number in the video comes from public/live.json, and every screen
// from public/captures/. Both are written here, from the live deployment, in
// one run. The first showcase video (2026-09-29) showed 130 cafes where the
// app said 37; this script exists so that cannot happen again. It fetches the
// numbers from the API, captures the real screens, reads the same numbers
// back off those screens, and exits non-zero on any mismatch.
//
// Run: npm run capture   (needs Chrome at /usr/bin/google-chrome or CHROME=...)

import { chromium } from 'playwright-core'
import fs from 'node:fs'
import path from 'node:path'

const BASE = process.env.BASE || 'https://thirdeye-466032735471.us-central1.run.app'
const CHROME = process.env.CHROME || '/usr/bin/google-chrome'
const OUT = path.resolve('public/captures')
const CATEGORY = 'cafe'
const K = 1 // the report's "~0.9 km², ~6 min on foot" catchment

// The two sites the video compares. Coordinates, not names: names come from
// the app's own reverse geocoder at capture time.
const A = { lat: 29.9513, lon: 31.2664 } // Maadi
const B = { lat: 30.0877, lon: 31.3263 } // Heliopolis

const fmt = n => n.toFixed(5)
const reportPath = p => `/report?lat=${fmt(p.lat)}&lon=${fmt(p.lon)}&k=${K}&category=${CATEGORY}`
const comparePath = `/compare?a=${fmt(A.lat)},${fmt(A.lon)}&b=${fmt(B.lat)},${fmt(B.lon)}&k=${K}&category=${CATEGORY}`
const searchPath = `/search?category=${CATEGORY}`

// RESOLVE_IP=<ipv4> pins the app's hostname to an address, for networks whose
// DNS returns only IPv6 to a machine with no IPv6 route (seen on a phone
// hotspot, 2026-10-06). API calls then go through Chrome, which honours the pin.
const RESOLVE_IP = process.env.RESOLVE_IP
const chromeArgs = RESOLVE_IP ? [`--host-resolver-rules=MAP ${new URL(BASE).host} ${RESOLVE_IP}`] : []
const browser = await chromium.launch({ executablePath: CHROME, headless: true, args: chromeArgs })
const apiPage = await browser.newPage()
if (RESOLVE_IP) await apiPage.goto(BASE + '/api/healthz')

async function api(p) {
  if (RESOLVE_IP) {
    const out = await apiPage.evaluate(async u => {
      const r = await fetch(u)
      return { ok: r.ok, status: r.status, body: r.ok ? await r.json() : null }
    }, BASE + p)
    if (!out.ok) throw new Error(`${p} -> HTTP ${out.status}`)
    return out.body
  }
  const r = await fetch(BASE + p)
  if (!r.ok) throw new Error(`${p} -> HTTP ${r.status}`)
  return r.json()
}

function metric(report, name) {
  const m = report.metrics.find(m => m.metric === name)
  if (!m) throw new Error(`metric ${name} missing from report`)
  return m
}

async function site(p) {
  const rep = await api(`/api/report?lat=${p.lat}&lon=${p.lon}&k=${K}&category=${CATEGORY}`)
  const places = await api(`/api/places?lat=${p.lat}&lon=${p.lon}&k=${K}&category=${CATEGORY}&limit=1000`)
  const comp = metric(rep, `business_count.${CATEGORY}`)
  const pop = metric(rep, 'population')
  const ppc = metric(rep, `people_per_competitor.${CATEGORY}`)
  return {
    lat: p.lat, lon: p.lon,
    competitors: comp.value,
    competitorsPerLandKm2: comp.value_per_land_km2,
    competitorsConfidence: comp.confidence,
    competitorsSources: comp.contributing_sources,
    competitorsAsOf: comp.as_of,
    cellsByConfidence: comp.cells_by_confidence,
    cellsTotal: comp.cells_total,
    cellsNoData: comp.cells_no_data,
    sourceCounts: comp.source_counts,
    agreementRatio: comp.agreement_ratio,
    population: Math.round(pop.value),
    populationAsOf: pop.as_of,
    peoplePerCompetitor: Math.round(ppc.value),
    duplicateFlagged: places.duplicate_flagged,
    records: places.total,
    landAreaKm2: rep.context.land_area_km2,
    duplicateInflationPct: rep.limitations?.duplicate_inflation_pct_range ?? null,
  }
}

const failures = []
function expect(label, onScreen, fromApi) {
  const ok = String(onScreen).replace(/,/g, '') === String(fromApi)
  console.log(`${ok ? 'ok  ' : 'FAIL'} ${label}: screen=${onScreen} api=${fromApi}`)
  if (!ok) failures.push(label)
}

const numberIn = (text, re) => {
  const m = text.match(re)
  return m ? m[1].replace(/,/g, '') : null
}

fs.mkdirSync(OUT, { recursive: true })
const live = {
  fetchedAt: new Date().toISOString(),
  base: BASE,
  category: CATEGORY,
  k: K,
  a: await site(A),
  b: await site(B),
  urls: { reportA: reportPath(A), reportB: reportPath(B), compare: comparePath, search: searchPath },
}
// Map data for the fly-in: the coverage hexes exactly as the app draws them,
// and the catchment's places (position and source only; names stay out).
fs.mkdirSync('public/data', { recursive: true })
const placesA = await api(`/api/places?lat=${A.lat}&lon=${A.lon}&k=${K}&category=${CATEGORY}&limit=1000`)
fs.writeFileSync('public/data/places-a.json', JSON.stringify(
  placesA.places.map(p => ({ lat: p.lat, lon: p.lon, source: p.source, flagged: !!p.duplicate_suspected }))))
{
  const r = RESOLVE_IP
    ? await apiPage.evaluate(async u => (await fetch(u)).text(), BASE + '/coverage-res8.geojson')
    : await (await fetch(BASE + '/coverage-res8.geojson')).text()
  fs.writeFileSync('public/data/coverage-res8.geojson', r)
}
const search = await api(`/api/search?category=${CATEGORY}`)
live.searchMatches = search.counts.matched

const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 3 })
const settle = async p => {
  await page.goto(BASE + p, { waitUntil: 'networkidle', timeout: 90000 })
  await page.waitForTimeout(2500) // map tiles fade in after network idle
}

// --- Report A ---
await settle(reportPath(A))
const cardText = await page.locator('div.rc-card').first().innerText()
expect('report card: competitors', numberIn(cardText, /\n\s*([\d,]+)\s*\n/), live.a.competitors)
const placesHead = await page.locator('section.rc-places').innerText()
expect('places: records', numberIn(placesHead, /([\d,]+) records/), live.a.records)
expect('places: flagged', numberIn(placesHead, /([\d,]+) flagged/), live.a.duplicateFlagged)
live.a.name = (await page.locator('.rc').innerText()).split('\n')[0].trim()
// The small print on the card, which the video shows: check it too.
const single = live.a.cellsByConfidence.single_source ?? 0
expect('card: single-source cells', numberIn(cardText, /(\d+) single-source/), single)
expect('card: no-data cells', numberIn(cardText, /(\d+) no data/), live.a.cellsNoData)
expect('card: cells total', numberIn(cardText, /of (\d+) cells/), live.a.cellsTotal)
expect('card: per land km2', numberIn(cardText, /([\d.]+) per land/), live.a.competitorsPerLandKm2.toFixed(1))
expect('card: sources differ', numberIn(cardText, /differ ([\d.]+)/), (1 / live.a.agreementRatio).toFixed(2))
const dup = live.a.duplicateInflationPct
expect('card: duplicate inflation low', numberIn(cardText, /includes ([\d.]+)/), dup?.[0])
expect('card: duplicate inflation high', numberIn(cardText.replace(/\s+/g, ''), /[\d.]+[–-]([\d.]+)%duplicate/), dup?.[1])
// The walk time is the app's own label for this catchment, not ours.
const catchBtn = await page.locator('button', { hasText: 'min on foot' }).evaluateAll(bs =>
  bs.map(b => ({ text: b.innerText.replace(/\s+/g, ' ').trim(), on: b.className })))
const activeCatch = catchBtn.find(b => /active|on|selected/.test(b.on)) ?? catchBtn[K]
live.catchment = { label: activeCatch?.text ?? null, all: catchBtn.map(b => b.text) }
live.walkMinutes = Number(numberIn(activeCatch?.text ?? '', /~(\d+) min on foot/))
if (!live.walkMinutes) failures.push('walk minutes not found on the report page')
console.log(`ok   catchment label: ${live.catchment.label}`)
await page.locator('div.rc-card').first().screenshot({ path: `${OUT}/report-card.png` })
// Where the evidence sits inside the card, so the video can draw its
// highlights on the exact lines. Boxes are in the capture's pixels (x3).
live.cardBoxes = await page.locator('div.rc-card').first().evaluate((card, dpr) => {
  const c = card.getBoundingClientRect()
  const find = re => {
    // Smallest element whose own text matches: a line, not the whole card.
    const hits = [...card.querySelectorAll('*')].filter(e => re.test(e.innerText || ''))
    const e = hits.sort((a, b) => a.innerText.length - b.innerText.length)[0]
    if (!e) return null
    const r = e.getBoundingClientRect()
    return { x: (r.left - c.left) * dpr, y: (r.top - c.top) * dpr, w: r.width * dpr, h: r.height * dpr }
  }
  return {
    value: find(/^\s*\d[\d,]*\s*$/),
    confidence: find(/single source|corroborated/i),
    asOf: find(/as of/i),
    differ: find(/sources differ/i),
    duplicates: find(/duplicate inflation/i),
  }
}, 3)
await page.locator('section.rc-cards').screenshot({ path: `${OUT}/report-cards.png` })
await page.locator('div.rc-map-wrap').screenshot({ path: `${OUT}/report-map.png` })
await page.locator('section.rc-places').screenshot({ path: `${OUT}/report-places.png` })

// --- Compare ---
await settle(comparePath)
const rows = await page.locator('section.cmp-rows').innerText()
const firstRow = rows.split('\n').join(' ')
const compNums = firstRow.match(/Cafe competitors.*?([\d,]+).*?([\d,]+)/)
expect('compare: A competitors', compNums?.[1], live.a.competitors)
expect('compare: B competitors', compNums?.[2], live.b.competitors)
live.b.name = (await page.locator('div.cmp-slot-b').innerText()).split('\n')[1]?.trim()
await page.locator('section.cmp-rows').screenshot({ path: `${OUT}/compare-rows.png` })
await page.locator('div.cmp-minis').screenshot({ path: `${OUT}/compare-minis.png` })

// --- Search ---
await settle(searchPath)
const head = await page.locator('section.sr-results').innerText()
expect('search: matches', numberIn(head, /([\d,]+) cells match/), live.searchMatches)
const box = await page.locator('main.sr-main').boundingBox()
await page.screenshot({ path: `${OUT}/search.png`, clip: { x: 0, y: 0, width: 1280, height: Math.min(900, box.y + 760) } })

// --- Phone-width captures: the app's text is larger relative to the frame,
// which is what a 1080-wide video needs to stay legible on a phone. ---
const phone = await browser.newPage({ viewport: { width: 430, height: 932 }, deviceScaleFactor: 3, isMobile: true, hasTouch: true })
// The amber cells are drawn from the 4.8 MB coverage file; on a slow link the
// first capture fired before it arrived and showed an empty map.
const coverageLoaded = phone.waitForResponse(r => r.url().includes('coverage-res8.geojson') && r.ok(), { timeout: 180000 })
await phone.goto(BASE + searchPath, { waitUntil: 'load', timeout: 90000 })
await coverageLoaded
await phone.locator('section.sr-results').getByText('cells match').first().waitFor({ timeout: 60000 })
await phone.waitForTimeout(4000)
const res = await phone.locator('section.sr-results').boundingBox()
expect('search (phone): matches', numberIn(await phone.locator('section.sr-results').innerText(), /([\d,]+) cells match/), live.searchMatches)
await phone.screenshot({ path: `${OUT}/search-phone.png`, clip: { x: 0, y: 0, width: 430, height: res.y + 120 } })

await browser.close()

if (failures.length) {
  console.error(`\n${failures.length} mismatch(es) between the screen and the API: ${failures.join(', ')}`)
  console.error('public/live.json NOT written. Fix the data or the selectors before rendering.')
  process.exit(1)
}
fs.writeFileSync('public/live.json', JSON.stringify(live, null, 2))
console.log(`\nwrote public/live.json and ${fs.readdirSync(OUT).length} captures (fetched ${live.fetchedAt})`)
