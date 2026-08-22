import React, { useEffect } from 'react'
import { setMeta } from '../components/meta'
import Footer from '../components/Footer'
import '../tokens.css'
import './notfound.css'

/** A real 404.
 *
 *  The SPA fallback serves index.html for any path, so an unknown URL used to
 *  render the home map as though it were the page you asked for. For a product
 *  built on saying what it does not have, quietly substituting a different page
 *  is exactly the wrong instinct.
 */
export default function NotFound() {
  useEffect(() => {
    setMeta('Not found — Third Eye', 'That page does not exist.')
  }, [])

  return (
    <div className="nf">
      <div className="nf-body">
        <img src="/brand/lockup-compact-teal.svg" height={32} alt="Third Eye" />
        <h1 className="nf-h1">That page does not exist</h1>
        <p className="nf-p">
          The address <code>{window.location.pathname}</code> is not a page here.
          It is not a missing report or a location we do not cover — there is
          simply nothing at this path.
        </p>
        <div className="nf-links">
          <a className="nf-btn" href="/">Open the coverage map</a>
          <a className="nf-alt" href="/tokens">Design system</a>
        </div>
      </div>
      <Footer />
    </div>
  )
}
