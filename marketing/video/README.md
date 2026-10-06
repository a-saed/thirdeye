# Third Eye videos

Remotion project for the LinkedIn series. Strategy and rules live in the
marketing playbook; the one rule enforced here is that **every number on screen
comes from the live app**.

```bash
npm i
npm run capture        # live numbers + real screens; fails if they disagree
npx remotion studio    # preview
npx remotion render Showcase out/showcase.mp4   # only when the cut is approved
```

`npm run capture` writes `public/live.json` and `public/captures/` (both
gitignored: derived and licence-bearing). Scenes read numbers only from
`src/live.ts`. If the network's DNS returns only IPv6 (seen on a phone
hotspot), pin the host: `RESOLVE_IP=<ipv4 from dig @8.8.8.8> npm run capture`.

Remotion is free for individuals and companies of up to 3 people.
