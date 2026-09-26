# Options Desk

A three-page options trading dashboard for Indian index options, built as a static site
(no build step) that runs on GitHub Pages.

| Page | File | What it does |
|------|------|--------------|
| 1 · Learn | `index.html` | Twelve lessons that take a complete beginner from "what is an index" to strategies, the Greeks, IV, risk and reading a chain. Interactive payoff charts, a Black–Scholes pricer, a time-decay chart, a strategy explorer, a position-size calculator and quizzes. Progress is saved in the browser. |
| 2 · Live | `live.html` | Live option chain from **Zerodha Kite** (official Kite Connect API) or Sensibull through a local bridge, with login for both. With Kite it also shows your funds, margins and positions, and imports your F&O positions into the builder. Shows spot, future, ATM IV, expected move, PCR, max pain, OI by strike and the IV smile. Click **B** / **S** on any strike to build a strategy and track paper-trade P&L, payoff and net Greeks. A clearly labelled simulated feed is available when the bridge is not running. |
| 3 · Research agent | `agent.html` | A Karpathy [autoresearch](https://github.com/karpathy/autoresearch)-style loop. An agent reads a research program and the results log, proposes one strategy change, a fixed harness backtests it, and the change is kept only if the score improves. It runs until stopped. The proposer is either a free local mutation search or Claude via your Anthropic API key. |

## Viewing on your phone

* **Learn, Research agent and the simulated Live page** work on any phone once the site is
  published. GitHub Pages serves this repository's `master` branch at
  `https://ravishkarve.github.io/karve99.github.io/options/`.
* **Live Kite / Sensibull data on the phone**: start the bridge in phone mode on your computer

  ```bash
  python3 options/bridge/sensibull_bridge.py --phone
  ```

  On the computer, open the Live page and press **📱 Open on phone**, then scan the QR code
  with the phone (same Wi-Fi). Log in to Kite or Sensibull on the computer; the phone shows
  the same live data, account and positions. The link carries a one-time pairing code, and
  other devices on the network are refused without it. The Wi-Fi connection is plain HTTP,
  so use it on a network you trust. If the detected address is wrong, pass
  `--lan-ip 192.168.x.y`, and allow port 8765 through the computer's firewall if asked.
* Phones get a compact option chain (OI · LTP · strike · LTP · OI) so both sides fit.

## Connecting to Zerodha Kite

Kite Connect is Zerodha's official API. The bridge talks to it for you, so your API secret
and access token never reach the browser page.

1. Create an app at [developers.kite.trade](https://developers.kite.trade). Set its
   **redirect URL** to `http://127.0.0.1:8765/api/kite/callback`.
2. Start the bridge: `python3 options/bridge/sensibull_bridge.py`. You can pass
   `KITE_API_KEY=... KITE_API_SECRET=...` as environment variables instead of typing them.
3. Open `http://127.0.0.1:8765/options/live.html`, choose **Zerodha Kite**, enter the API
   key and secret, and press **Log in with Kite**. Zerodha's own login page opens in a new
   tab, where you sign in with your user ID, password and TOTP. The page never sees your
   Zerodha password.

| Kite plan | What works here |
|---|---|
| Personal (free) | Profile, funds and margins, positions with P&L, importing positions into the builder |
| Connect (₹500/month) | All of the above, plus the live option chain and NIFTY / India VIX history for the research agent |

* Kite quotes carry no IV or Greeks. The bridge computes them from last prices with
  Black–Scholes (r = 6%), so they will differ slightly from Kite's or Sensibull's.
* Kite sessions expire every morning (around 6 AM), so log in once a day. Restarting the
  bridge also requires a new login.
* Read-only: the bridge has no order endpoints.
* The login callback is protected against login CSRF with a one-time `state` value, and
  the bridge rejects requests whose Host header is not 127.0.0.1 or localhost (DNS rebinding).

## Connecting to Sensibull

Sensibull has no public API, and browsers block cross-site calls. The page therefore
talks to a small bridge that runs on your own computer:

```bash
python3 options/bridge/sensibull_bridge.py        # Python 3.9+, standard library only
# then open http://127.0.0.1:8765/options/live.html
```

* **Market data** (option chain, greeks, OI) comes from the same public endpoints the
  Sensibull web app loads (`oxide.sensibull.com/v1/compute/cache/...`). These work
  without logging in, and may change or be rate-limited without notice.
* **Login**: enter your Sensibull login ID and press *Log in to Sensibull*. Sensibull
  signs in with an OTP or through your broker, so the bridge opens a real browser window
  at web.sensibull.com. It pre-fills what it can; you finish the login there and close the
  window, and the bridge keeps the session cookies. This needs Playwright:
  `pip install playwright && playwright install chromium`.
  Alternatively, paste the `access_token` cookie from web.sensibull.com under *Advanced*.
* Credentials and cookies live only in the bridge's memory. Nothing is written to disk
  or sent anywhere except Sensibull. The page stores your login ID only if you tick
  *Remember*. The bridge listens on 127.0.0.1 only (unless `--phone`) and accepts API calls
  only from the GitHub Pages site and itself (add more with `--allow-origin`).
* The page never places orders. It is for analysis and paper trading.

Not affiliated with or endorsed by Sensibull; use it in line with Sensibull's terms.

## The research agent

| autoresearch | here |
|---|---|
| `program.md` | the editable research program (objective, risk limits, guidance) |
| `train.py` | the strategy config: structure, DTE, strike deltas, wings, profit target, stop loss, exit timing, IV-rank and trend filters, position size, cooldown |
| `prepare.py` (fixed) | `js/backtest.js`: pricing, costs, margin, data splits and the metric |
| `results.tsv` | the results log (downloadable) |
| keep / `git revert` | kept only if the score beats the best so far |

* **Score**: by default the worse of train and validation CAGR, so a strategy must work
  in both periods. Runs that exceed the drawdown limit or trade too rarely are discarded.
* **Test period**: the last 20% of the data is never shown to the agent. Compare it with
  validation to spot overfitting.
* **Data**: a synthetic stochastic-volatility market with jumps (seeded, with an adjustable
  volatility premium), your own CSV (`date,close[,vix]`), or NIFTY 50 + India VIX
  history downloaded through the bridge from Zerodha Kite (Connect plan) or Yahoo Finance.
* **Claude proposer**: calls the Anthropic API directly from the browser with your key
  (Claude Opus 5 by default, with server-side refusal fallbacks and structured JSON
  output). Each experiment is one call, and the loop stops at your spend cap.

**Limitations.** Options are priced with Black–Scholes from the day's implied volatility
and a fixed skew, not from historical option quotes. Fills are at daily closes with
modelled slippage and charges, and margin is approximate. Treat results as research
leads, not trading signals.

## Development

```bash
python3 -m unittest options/bridge/test_bridge.py options/bridge/test_kite.py   # offline bridge + Kite tests
python3 options/bridge/sensibull_bridge.py          # serves the site + API on :8765
```
