/* Per-route title and description.
 *
 * Crawlers that do not run JavaScript read the tags in index.html, which carry
 * the home values — so those stay the strongest version. This updates the
 * document for humans navigating between routes, and for crawlers that do
 * execute scripts.
 */
export function setMeta(title: string, description: string) {
  document.title = title
  for (const [selector, attr] of [
    ['meta[name="description"]', 'content'],
    ['meta[property="og:title"]', 'content'],
    ['meta[property="og:description"]', 'content'],
  ] as const) {
    const el = document.head.querySelector(selector)
    if (!el) continue
    if (selector.includes('og:title')) el.setAttribute(attr, title)
    else el.setAttribute(attr, description)
  }
}
