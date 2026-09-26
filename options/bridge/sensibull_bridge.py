#!/usr/bin/env python3
"""
Sensibull bridge for Options Desk.

Browsers cannot call Sensibull directly (cross-origin rules), so this small
server runs on YOUR computer, talks to Sensibull on the page's behalf, and
serves the Options Desk site itself at http://127.0.0.1:8765/options/.

  python3 options/bridge/sensibull_bridge.py            # stdlib only
  pip install playwright && playwright install chromium  # optional: interactive login

Endpoints (JSON):
  GET  /api/status                  bridge + login state
  POST /api/login   {login_id, secret, session_token}
  POST /api/logout
  GET  /api/chain?underlying=NIFTY  normalised live option chain
  GET  /api/history?symbol=^NSEI&iv=^INDIAVIX&range=10y   daily closes + IV (Yahoo Finance)

Security
  * Binds to 127.0.0.1 only. API calls are accepted only from allowed origins.
  * Your password / token is kept in memory only, never written to disk or logged.
  * Sensibull has no public API. This uses the same public endpoints its web app
    loads (see sensibull-quotes on PyPI). They may change or rate-limit without notice.
    Not affiliated with Sensibull. Use in line with Sensibull's terms.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

VERSION = "1.0"
OXIDE = "https://oxide.sensibull.com/v1/compute"
METACACHE_URL = f"{OXIDE}/cache/instrument_metacache/2"
LIVE_URL = f"{OXIDE}/cache/live_derivative_prices"
SENSIBULL_WEB = "https://web.sensibull.com/"
YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/"

# Exchange instrument tokens for index underlyings (Zerodha numbering, used by Sensibull).
# Used only if the metacache does not provide one. Override with ?token=...
FALLBACK_TOKENS = {
    "NIFTY": 256265,
    "BANKNIFTY": 260105,
    "FINNIFTY": 257801,
    "MIDCPNIFTY": 288009,
    "SENSEX": 265,
}
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")


# --------------------------------------------------------------------------- state
class Session:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.cookies: dict[str, str] = {}
        self.login_id: str = ""
        self.method: str = ""
        self.login_state: str = ""
        self.login_error: str = ""
        self.login_thread: threading.Thread | None = None

    def logged_in(self) -> bool:
        return bool(self.cookies)

    def cookie_header(self) -> str:
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())

    def clear(self) -> None:
        with self.lock:
            self.cookies = {}
            self.login_id = ""
            self.method = ""
            self.login_state = ""
            self.login_error = ""


SESSION = Session()
_META: dict = {"at": 0.0, "data": None, "tokens": {}}
_META_LOCK = threading.Lock()


def mask(s: str) -> str:
    s = s or ""
    if len(s) <= 4:
        return "*" * len(s)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


# --------------------------------------------------------------------------- http helpers
def http_json(url: str, *, sensibull: bool = True, timeout: float = 15.0):
    headers = {"User-Agent": UA, "Accept": "application/json, text/plain, */*"}
    if sensibull:
        headers["Origin"] = "https://web.sensibull.com"
        headers["Referer"] = SENSIBULL_WEB
        ck = SESSION.cookie_header()
        if ck:
            headers["Cookie"] = ck
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise BridgeError(f"{urllib.parse.urlsplit(url).netloc} answered HTTP {e.code}", 502) from None
    except urllib.error.URLError as e:
        raise BridgeError(f"Could not reach {urllib.parse.urlsplit(url).netloc}: {e.reason}", 502) from None
    except json.JSONDecodeError:
        raise BridgeError(f"{urllib.parse.urlsplit(url).netloc} returned non-JSON data", 502) from None


class BridgeError(Exception):
    def __init__(self, msg: str, status: int = 400):
        super().__init__(msg)
        self.status = status


# --------------------------------------------------------------------------- sensibull data
def metacache(max_age: float = 6 * 3600) -> tuple[dict, dict]:
    """Instrument metadata: token -> {strike, type, expiry, symbol, tradingsymbol, lot_size}."""
    with _META_LOCK:
        if _META["data"] is not None and time.time() - _META["at"] < max_age:
            return _META["data"], _META["tokens"]
    data = http_json(METACACHE_URL)
    tokens: dict[int, dict] = {}
    for symbol, sym_data in (data.get("derivatives") or {}).items():
        for expiry, exp_data in ((sym_data or {}).get("derivatives") or {}).items():
            for strike, strike_data in ((exp_data or {}).get("options") or {}).items():
                for typ in ("CE", "PE"):
                    o = (strike_data or {}).get(typ)
                    if not o or "instrument_token" not in o:
                        continue
                    tokens[int(o["instrument_token"])] = {
                        "symbol": symbol, "expiry": expiry, "type": typ,
                        "strike": _num(o.get("strike", strike)),
                        "tradingsymbol": o.get("tradingsymbol", ""),
                        "lot_size": o.get("lot_size"),
                    }
    with _META_LOCK:
        _META.update(at=time.time(), data=data, tokens=tokens)
    return data, tokens


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def underlying_token(symbol: str, meta: dict) -> int:
    sym = (meta.get("derivatives") or {}).get(symbol) or {}
    for key in ("underlying_instrument_token", "underlying_token", "instrument_token", "token"):
        if isinstance(sym.get(key), (int, str)) and str(sym.get(key)).isdigit():
            return int(sym[key])
    if symbol in FALLBACK_TOKENS:
        return FALLBACK_TOKENS[symbol]
    raise BridgeError(f"Unknown underlying {symbol!r}. Pass ?token=<instrument token>.")


def live_chain(symbol: str, token: int | None = None) -> dict:
    symbol = symbol.upper()
    try:
        meta, tokens = metacache()
    except BridgeError:
        meta, tokens = {}, {}   # chain can still be built if options carry strike/type
    tok = token or underlying_token(symbol, meta)
    raw = http_json(f"{LIVE_URL}/{tok}")
    if not raw or not raw.get("status"):
        raise BridgeError("Sensibull returned no data for this underlying", 502)
    return normalise(symbol, raw["data"], tokens)


def normalise(symbol: str, d: dict, tokens: dict) -> dict:
    lot_size = None
    expiries = []
    for expiry, ed in sorted((d.get("per_expiry_data") or {}).items()):
        rows: dict[float, dict] = {}
        for o in ed.get("options") or []:
            info = tokens.get(_int(o.get("token"))) or {}
            strike = _num(o.get("strike")) or info.get("strike")
            typ = o.get("option_type") or o.get("instrument_type") or info.get("type")
            if strike is None or typ not in ("CE", "PE"):
                continue
            g = o.get("greeks_with_iv") or o.get("greeks") or {}
            lot_size = lot_size or info.get("lot_size")
            rows.setdefault(strike, {"strike": strike})[typ] = {
                "ltp": o.get("last_price"),
                "oi": o.get("oi"),
                "volume": o.get("volume"),
                "iv": g.get("iv"),
                "delta": g.get("delta"),
                "gamma": g.get("gamma"),
                "theta": g.get("theta"),
                "vega": g.get("vega"),
                "tradingsymbol": info.get("tradingsymbol", ""),
            }
        expiries.append({
            "expiry": expiry,
            "future": ed.get("future_price"),
            "atm_strike": ed.get("atm_strike"),
            "atm_iv": ed.get("atm_iv"),
            "strikes": sorted(rows.values(), key=lambda r: r["strike"]),
        })
    return {
        "underlying": symbol,
        "spot": d.get("underlying_price"),
        "updated_at": d.get("last_updated_at"),
        "lot_size": lot_size,
        "expiries": [e for e in expiries if e["strikes"]],
    }


def _int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------- history (Yahoo)
def yahoo_series(symbol: str, rng: str) -> dict[str, float]:
    url = f"{YAHOO_CHART}{urllib.parse.quote(symbol)}?range={urllib.parse.quote(rng)}&interval=1d"
    data = http_json(url, sensibull=False)
    try:
        res = data["chart"]["result"][0]
        ts = res["timestamp"]
        closes = res["indicators"]["quote"][0]["close"]
    except (KeyError, IndexError, TypeError):
        raise BridgeError(f"No history returned for {symbol}", 502) from None
    out = {}
    for t, c in zip(ts, closes):
        if c is not None:
            day = datetime.fromtimestamp(t + 5.5 * 3600, tz=timezone.utc).strftime("%Y-%m-%d")
            out[day] = float(c)
    return out


def history(symbol: str, iv_symbol: str, rng: str) -> dict:
    px = yahoo_series(symbol, rng)
    ivs = yahoo_series(iv_symbol, rng) if iv_symbol else {}
    dates = sorted(px)
    return {
        "symbol": symbol, "iv_symbol": iv_symbol or None, "source": "Yahoo Finance",
        "dates": dates,
        "close": [px[d] for d in dates],
        "iv": [(ivs[d] / 100.0 if d in ivs else None) for d in dates],
    }


# --------------------------------------------------------------------------- login
def parse_token(token: str) -> dict[str, str]:
    token = token.strip()
    if "=" in token:   # a full Cookie header pasted: "a=b; c=d"
        out = {}
        for part in token.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                out[k.strip()] = v.strip()
        return out
    return {"access_token": token}


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def interactive_login(login_id: str, secret: str) -> None:
    """Open a real browser at Sensibull, prefill what we can, let the user finish (OTP / broker
    2FA), then capture the session cookies. Runs in its own thread."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        SESSION.login_error = "Interactive login needs Playwright: pip install playwright && playwright install chromium"
        return
    snapshot: dict[str, str] = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            ctx = browser.new_context()
            page = ctx.new_page()
            SESSION.login_state = "Opening Sensibull…"
            page.goto(SENSIBULL_WEB, wait_until="domcontentloaded", timeout=45000)
            _prefill(page, login_id, secret)
            secret = ""
            SESSION.login_state = ("Finish logging in (OTP / broker 2FA) in the window that opened, "
                                   "then close that window. This page updates automatically.")
            deadline = time.time() + 300
            while time.time() < deadline:
                try:
                    cookies = ctx.cookies(["https://web.sensibull.com", "https://oxide.sensibull.com", "https://sensibull.com"])
                except Exception:
                    break  # window / context closed by the user
                snapshot = {c["name"]: c["value"] for c in cookies}
                if any(n.lower() in ("access_token", "sb_access_token") for n in snapshot):
                    break
                if not browser.is_connected() or all(pg.is_closed() for pg in ctx.pages):
                    break
                time.sleep(1.5)
            try:
                browser.close()
            except Exception:
                pass
    except Exception as e:  # noqa: BLE001 - report any browser failure to the page
        SESSION.login_error = f"Login window failed: {e.__class__.__name__}: {str(e)[:200]}"
        return
    if not snapshot:
        SESSION.login_error = "No Sensibull session was captured. Log in fully before closing the window."
        return
    with SESSION.lock:
        SESSION.cookies = snapshot
        SESSION.method = "browser"
        SESSION.login_state = "Logged in"
        SESSION.login_error = ""


def _prefill(page, login_id: str, secret: str) -> None:
    """Best effort: the Sensibull login UI is not documented, so every step may no-op."""
    for label in ("Login", "Log in", "Sign in", "Sign In"):
        try:
            btn = page.get_by_text(label, exact=True).first
            if btn.is_visible(timeout=1500):
                btn.click(timeout=2000)
                break
        except Exception:
            pass
    if login_id:
        for sel in ("input[type=tel]", "input[type=email]", "input[name*=phone i]",
                    "input[name*=mobile i]", "input[name*=email i]", "input[type=text]"):
            try:
                el = page.locator(sel).first
                if el.is_visible(timeout=1500):
                    el.fill(login_id, timeout=2000)
                    break
            except Exception:
                pass
    if secret:
        try:
            el = page.locator("input[type=password]").first
            if el.is_visible(timeout=1500):
                el.fill(secret, timeout=2000)
        except Exception:
            pass


# --------------------------------------------------------------------------- server
class Handler(SimpleHTTPRequestHandler):
    server_version = f"SensibullBridge/{VERSION}"
    allowed_origins: set[str] = set()

    def log_message(self, fmt, *args):  # quieter logs; never print request bodies
        if self.path.startswith("/api/"):
            sys.stderr.write("%s %s\n" % (self.command, self.path.split("?")[0]))

    # -- CORS
    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin")
        return origin is None or origin in self.allowed_origins

    def _cors(self):
        origin = self.headers.get("Origin")
        if origin and origin in self.allowed_origins:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            if self.headers.get("Access-Control-Request-Private-Network"):
                self.send_header("Access-Control-Allow-Private-Network", "true")

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _json(self, obj, status=200):
        body = json.dumps(obj).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204 if self._origin_ok() else 403)
        self._cors()
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_GET(self):
        if not self.path.startswith("/api/"):
            if self.path in ("/", ""):
                self.send_response(302)
                self.send_header("Location", "/options/live.html")
                self.end_headers()
                return
            return super().do_GET()
        if not self._origin_ok():
            return self._json({"ok": False, "error": "Origin not allowed. Start the bridge with --allow-origin <origin>."}, 403)
        url = urllib.parse.urlsplit(self.path)
        q = dict(urllib.parse.parse_qsl(url.query))
        try:
            if url.path == "/api/status":
                return self._json({
                    "ok": True, "version": VERSION, "logged_in": SESSION.logged_in(),
                    "login_id": mask(SESSION.login_id), "method": SESSION.method,
                    "login_state": SESSION.login_state, "login_error": SESSION.login_error,
                    "playwright": playwright_available(),
                })
            if url.path == "/api/chain":
                tok = q.get("token")
                chain = live_chain(q.get("underlying", "NIFTY"), int(tok) if tok and tok.isdigit() else None)
                return self._json({"ok": True, "chain": chain})
            if url.path == "/api/history":
                return self._json({"ok": True, **history(q.get("symbol", "^NSEI"), q.get("iv", "^INDIAVIX"), q.get("range", "10y"))})
            return self._json({"ok": False, "error": "Not found"}, 404)
        except BridgeError as e:
            return self._json({"ok": False, "error": str(e)}, e.status)
        except Exception as e:  # noqa: BLE001
            return self._json({"ok": False, "error": f"{e.__class__.__name__}: {e}"}, 500)

    def do_POST(self):
        if not self.path.startswith("/api/"):
            return self._json({"ok": False, "error": "Not found"}, 404)
        # Require an allowed Origin (if present) and a JSON body: blocks cross-site form posts.
        if not self._origin_ok() or "application/json" not in (self.headers.get("Content-Type") or ""):
            return self._json({"ok": False, "error": "Forbidden"}, 403)
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(min(n, 65536)) or b"{}")
        except (ValueError, json.JSONDecodeError):
            return self._json({"ok": False, "error": "Bad JSON"}, 400)
        path = urllib.parse.urlsplit(self.path).path
        if path == "/api/logout":
            SESSION.clear()
            return self._json({"ok": True})
        if path == "/api/login":
            login_id = str(body.get("login_id") or "").strip()
            secret = str(body.get("secret") or "")
            token = str(body.get("session_token") or "").strip()
            if token:
                with SESSION.lock:
                    SESSION.cookies = parse_token(token)
                    SESSION.login_id = login_id
                    SESSION.method = "token"
                    SESSION.login_state = "Logged in"
                    SESSION.login_error = ""
                return self._json({"ok": True, "pending": False,
                                   "message": "Session token set. It is attached to every Sensibull request the bridge makes."})
            if not login_id:
                return self._json({"ok": False, "error": "Enter a login ID or a session token."}, 400)
            if not playwright_available():
                return self._json({"ok": False, "error": (
                    "Sensibull logs in with an OTP or through your broker, which needs a real browser window. "
                    "Install it with: pip install playwright && playwright install chromium, then restart the bridge. "
                    "Or paste your session token under Advanced.")}, 400)
            if SESSION.login_thread and SESSION.login_thread.is_alive():
                return self._json({"ok": True, "pending": True, "message": "A login window is already open."})
            SESSION.clear()
            SESSION.login_id = login_id
            SESSION.login_state = "Starting browser…"
            t = threading.Thread(target=interactive_login, args=(login_id, secret), daemon=True)
            SESSION.login_thread = t
            t.start()
            return self._json({"ok": True, "pending": True, "message": "A Sensibull login window is opening on this computer. Finish logging in there, then close it."})
        return self._json({"ok": False, "error": "Not found"}, 404)


def main() -> None:
    ap = argparse.ArgumentParser(description="Local bridge between Options Desk and Sensibull")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--allow-origin", action="append", default=[], help="extra browser origin allowed to use the API")
    ap.add_argument("--root", default=str(Path(__file__).resolve().parents[2]), help="directory served as the website root")
    args = ap.parse_args()

    Handler.allowed_origins = {
        "https://karve99.github.io",
        f"http://127.0.0.1:{args.port}",
        f"http://localhost:{args.port}",
        *args.allow_origin,
    }
    mimetypes.add_type("application/javascript", ".js")
    os.chdir(args.root)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"Sensibull bridge {VERSION} on http://127.0.0.1:{args.port}")
    print(f"  Open  http://127.0.0.1:{args.port}/options/live.html")
    print(f"  Serving files from {args.root}")
    print(f"  Interactive login: {'available' if playwright_available() else 'not installed (pip install playwright && playwright install chromium)'}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
