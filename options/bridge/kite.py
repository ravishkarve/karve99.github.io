"""
Zerodha Kite Connect client for the Options Desk bridge (standard library only).

Uses the official, documented Kite Connect v3 REST API (https://kite.trade/docs/connect/v3/),
following the same endpoints and login flow as Zerodha's pykiteconnect:

  1. Browser -> https://kite.zerodha.com/connect/login?v=3&api_key=...
  2. Kite redirects to your app's redirect URL with ?request_token=...
  3. POST /session/token {api_key, request_token, checksum=sha256(api_key+request_token+api_secret)}
     returns an access_token valid until ~6 AM the next day.
  4. Every request sends  X-Kite-Version: 3  and  Authorization: token api_key:access_token

Plans: the free "Personal" plan covers profile, funds and positions. Live quotes (the option
chain) and historical candles need the paid Kite Connect plan.

This module is read-only: it never places, modifies or cancels orders.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

ROOT = "https://api.kite.trade"
LOGIN = "https://kite.zerodha.com/connect/login"
IST = timezone(timedelta(hours=5, minutes=30))
RISK_FREE = 0.06

# underlying -> (options exchange, index quote key)
UNDERLYINGS = {
    "NIFTY": ("NFO", "NSE:NIFTY 50"),
    "BANKNIFTY": ("NFO", "NSE:NIFTY BANK"),
    "FINNIFTY": ("NFO", "NSE:NIFTY FIN SERVICE"),
    "MIDCPNIFTY": ("NFO", "NSE:NIFTY MID SELECT"),
    "SENSEX": ("BFO", "BSE:SENSEX"),
}
HISTORY_KEYS = {"NIFTY": "NSE:NIFTY 50", "BANKNIFTY": "NSE:NIFTY BANK", "SENSEX": "BSE:SENSEX"}
VIX_KEY = "NSE:INDIA VIX"


class KiteError(Exception):
    def __init__(self, msg: str, status: int = 502, kind: str = ""):
        super().__init__(msg)
        self.status = status
        self.kind = kind


# --------------------------------------------------------------------------- Black-Scholes (IV + greeks)
def _ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _npdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_price(typ: str, s: float, k: float, t: float, v: float, r: float = RISK_FREE) -> float:
    if t <= 0 or v <= 0:
        return max(s - k, 0.0) if typ == "CE" else max(k - s, 0.0)
    sq = v * math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * v * v) * t) / sq
    d2 = d1 - sq
    if typ == "CE":
        return s * _ncdf(d1) - k * math.exp(-r * t) * _ncdf(d2)
    return k * math.exp(-r * t) * _ncdf(-d2) - s * _ncdf(-d1)


def implied_vol(typ: str, price: float, s: float, k: float, t: float, r: float = RISK_FREE):
    if not price or price <= 0 or t <= 0 or s <= 0:
        return None
    intrinsic = max(s - k * math.exp(-r * t), 0) if typ == "CE" else max(k * math.exp(-r * t) - s, 0)
    if price <= intrinsic + 1e-6:
        return None
    lo, hi = 1e-4, 5.0
    if bs_price(typ, s, k, t, hi, r) < price:
        return None
    for _ in range(70):
        mid = 0.5 * (lo + hi)
        if bs_price(typ, s, k, t, mid, r) > price:
            hi = mid
        else:
            lo = mid
    return 0.5 * (lo + hi)


def greeks(typ: str, s: float, k: float, t: float, v: float, r: float = RISK_FREE) -> dict:
    sq = v * math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * v * v) * t) / sq
    d2 = d1 - sq
    disc = k * math.exp(-r * t)
    if typ == "CE":
        delta = _ncdf(d1)
        theta = -s * _npdf(d1) * v / (2 * math.sqrt(t)) - r * disc * _ncdf(d2)
    else:
        delta = _ncdf(d1) - 1
        theta = -s * _npdf(d1) * v / (2 * math.sqrt(t)) + r * disc * _ncdf(-d2)
    return {
        "delta": delta,
        "gamma": _npdf(d1) / (s * sq),
        "theta": theta / 365.0,
        "vega": s * _npdf(d1) * math.sqrt(t) / 100.0,
    }


def years_to_expiry(expiry: str, now: datetime | None = None) -> float:
    now = now or datetime.now(IST)
    exp = datetime.strptime(expiry, "%Y-%m-%d").replace(hour=15, minute=30, tzinfo=IST)
    return max((exp - now).total_seconds() / (365 * 24 * 3600), 0.0)


def mask(s: str) -> str:
    s = s or ""
    return s[:3] + "*" * max(len(s) - 5, 0) + s[-2:] if len(s) > 5 else "*" * len(s)


# --------------------------------------------------------------------------- client
class Kite:
    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.lock = threading.Lock()
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.access_token = ""
        self.user: dict = {}
        self.login_at = 0.0
        self.pending_state = ""
        self.pending_at = 0.0
        self.last_error = ""
        self._instruments: dict[str, tuple[str, list[dict]]] = {}   # exchange -> (IST day, rows)
        self.opener = urllib.request.urlopen   # replaced in tests

    # ---- state
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def logged_in(self) -> bool:
        return bool(self.access_token)

    def configure(self, api_key: str, api_secret: str) -> None:
        with self.lock:
            if api_key.strip() != self.api_key:
                self.access_token, self.user = "", {}
            self.api_key = api_key.strip()
            if api_secret.strip():
                self.api_secret = api_secret.strip()

    def status(self) -> dict:
        return {
            "configured": self.configured(),
            "logged_in": self.logged_in(),
            "api_key": mask(self.api_key),
            "user_id": self.user.get("user_id", ""),
            "user_name": self.user.get("user_name", ""),
            "login_at": self.login_at,
            "error": self.last_error,
        }

    # ---- login flow
    def login_url(self) -> str:
        if not self.configured():
            raise KiteError("Enter your Kite Connect API key and secret first.", 400)
        self.pending_state = secrets.token_urlsafe(16)
        self.pending_at = time.time()
        q = urllib.parse.urlencode({"v": "3", "api_key": self.api_key,
                                    "redirect_params": urllib.parse.urlencode({"state": self.pending_state})})
        return f"{LOGIN}?{q}"

    def complete_login(self, request_token: str, state: str | None) -> dict:
        # Login-CSRF guard: the callback must match a login started from this bridge.
        fresh = self.pending_at and time.time() - self.pending_at < 600
        if state is not None and state != self.pending_state:
            raise KiteError("Login state did not match. Start the login again from the Live page.", 400)
        if state is None and not fresh:
            raise KiteError("No login was started from this bridge in the last 10 minutes.", 400)
        if not request_token:
            raise KiteError("Kite did not return a request token.", 400)
        checksum = hashlib.sha256((self.api_key + request_token + self.api_secret).encode()).hexdigest()
        data = self._call("POST", "/session/token", form={"api_key": self.api_key, "request_token": request_token, "checksum": checksum}, auth=False)
        with self.lock:
            self.access_token = data["access_token"]
            self.user = {k: data.get(k) for k in ("user_id", "user_name", "user_shortname", "email", "broker")}
            self.login_at = time.time()
            self.pending_state, self.pending_at, self.last_error = "", 0.0, ""
        return self.user

    def logout(self) -> None:
        tok = self.access_token
        with self.lock:
            self.access_token, self.user = "", {}
        if tok:
            try:   # best effort: the local session is already cleared
                self._call("DELETE", "/session/token", params=[("api_key", self.api_key), ("access_token", tok)], auth=False)
            except Exception:  # noqa: BLE001
                pass

    # ---- HTTP
    def _call(self, method: str, path: str, params=None, form=None, auth: bool = True, raw: bool = False):
        url = ROOT + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        headers = {"X-Kite-Version": "3", "User-Agent": "OptionsDesk-Bridge/1.1"}
        if auth:
            if not self.access_token:
                raise KiteError("Not logged in to Kite. Use 'Log in with Kite' on the Live page.", 401, "TokenException")
            headers["Authorization"] = f"token {self.api_key}:{self.access_token}"
        body = None
        if form is not None:
            body = urllib.parse.urlencode(form).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        req = urllib.request.Request(url, data=body, headers=headers, method=method)
        try:
            with self.opener(req, timeout=20) as r:
                ctype = r.headers.get("Content-Type", "")
                payload = r.read()
        except urllib.error.HTTPError as e:
            payload = e.read() if hasattr(e, "read") else b""
            try:
                err = json.loads(payload.decode())
            except (ValueError, UnicodeDecodeError):
                err = {}
            kind = err.get("error_type", "")
            msg = err.get("message") or f"Kite answered HTTP {e.code}"
            if e.code == 403 and kind == "TokenException":
                with self.lock:
                    self.access_token, self.user = "", {}
                msg = "Your Kite session has expired (sessions end daily). Log in again."
            elif e.code == 403 and kind == "PermissionException":
                msg += " Live quotes and history need the paid Kite Connect plan; the free Personal plan covers only funds and positions."
            self.last_error = msg
            raise KiteError(msg, 401 if kind == "TokenException" else 502, kind) from None
        except urllib.error.URLError as e:
            raise KiteError(f"Could not reach Kite: {e.reason}", 502) from None
        if raw or "csv" in ctype:
            return payload.decode("utf-8")
        data = json.loads(payload.decode("utf-8"))
        if data.get("status") == "error":
            raise KiteError(data.get("message", "Kite error"), 502, data.get("error_type", ""))
        return data.get("data")

    # ---- instruments
    def instruments(self, exchange: str) -> list[dict]:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        cached = self._instruments.get(exchange)
        if cached and cached[0] == today:
            return cached[1]
        text = self._call("GET", f"/instruments/{exchange}", raw=True)
        rows = []
        for r in csv.DictReader(io.StringIO(text)):
            try:
                rows.append({
                    "instrument_token": int(r["instrument_token"]),
                    "tradingsymbol": r["tradingsymbol"],
                    "name": r.get("name", "").strip('"'),
                    "expiry": r.get("expiry", ""),
                    "strike": float(r.get("strike") or 0),
                    "lot_size": int(float(r.get("lot_size") or 0)),
                    "instrument_type": r.get("instrument_type", ""),
                    "segment": r.get("segment", ""),
                    "exchange": r.get("exchange", exchange),
                })
            except (KeyError, ValueError):
                continue
        self._instruments[exchange] = (today, rows)
        return rows

    def quote(self, keys: list[str]) -> dict:
        out: dict = {}
        for i in range(0, len(keys), 500):   # Kite allows up to 500 instruments per call
            out.update(self._call("GET", "/quote", params=[("i", k) for k in keys[i:i + 500]]) or {})
        return out

    # ---- account (free Personal plan)
    def profile(self) -> dict:
        return self._call("GET", "/user/profile")

    def margins(self) -> dict:
        return self._call("GET", "/user/margins")

    def positions(self) -> dict:
        data = self._call("GET", "/portfolio/positions") or {}
        index = {}
        for exch in {p.get("exchange") for p in data.get("net", [])} & {"NFO", "BFO"}:
            try:
                for r in self.instruments(exch):
                    index[(exch, r["tradingsymbol"])] = r
            except KiteError:
                pass
        for p in data.get("net", []):
            meta = index.get((p.get("exchange"), p.get("tradingsymbol")))
            if meta:
                p.update(underlying=meta["name"], strike=meta["strike"], option_type=meta["instrument_type"],
                         expiry=meta["expiry"], lot_size=meta["lot_size"])
        return data

    def account(self) -> dict:
        m = self.margins() or {}
        eq = m.get("equity") or {}
        pos = self.positions()
        return {
            "user": self.user,
            "margins": {
                "net": eq.get("net"),
                "available": (eq.get("available") or {}).get("live_balance"),
                "cash": (eq.get("available") or {}).get("cash"),
                "used": (eq.get("utilised") or {}).get("debits"),
                "span": (eq.get("utilised") or {}).get("span"),
                "exposure": (eq.get("utilised") or {}).get("exposure"),
            },
            "positions": pos.get("net", []),
        }

    # ---- option chain (needs paid plan)
    def chain(self, underlying: str, expiry: str | None = None, width: int = 40) -> dict:
        u = underlying.upper()
        if u not in UNDERLYINGS:
            raise KiteError(f"Unsupported underlying {underlying!r}. Choose one of {', '.join(UNDERLYINGS)}.", 400)
        exch, index_key = UNDERLYINGS[u]
        rows = self.instruments(exch)
        today = datetime.now(IST).strftime("%Y-%m-%d")
        opts = [r for r in rows if r["name"] == u and r["instrument_type"] in ("CE", "PE") and r["expiry"] >= today]
        if not opts:
            raise KiteError(f"No live {u} options found in the {exch} instrument list.", 502)
        expiries = sorted({r["expiry"] for r in opts})
        exp = expiry if expiry in expiries else expiries[0]
        futs = sorted((r for r in rows if r["name"] == u and r["instrument_type"] == "FUT" and r["expiry"] >= exp), key=lambda r: r["expiry"])
        fut = futs[0] if futs else None

        spot_q = self.quote([index_key]).get(index_key) or {}
        spot = spot_q.get("last_price")
        if not spot:
            raise KiteError(f"No quote for {index_key}. Live quotes need the paid Kite Connect plan.", 502)
        in_exp = [r for r in opts if r["expiry"] == exp]
        strikes = sorted({r["strike"] for r in in_exp})
        atm_i = min(range(len(strikes)), key=lambda i: abs(strikes[i] - spot))
        keep = set(strikes[max(0, atm_i - width): atm_i + width + 1])
        chosen = [r for r in in_exp if r["strike"] in keep]
        keys = [f"{exch}:{r['tradingsymbol']}" for r in chosen]
        if fut:
            keys.append(f"{exch}:{fut['tradingsymbol']}")
        q = self.quote(keys)

        t = years_to_expiry(exp)
        by_strike: dict[float, dict] = {}
        for r in chosen:
            d = q.get(f"{exch}:{r['tradingsymbol']}") or {}
            ltp = d.get("last_price")
            iv = implied_vol(r["instrument_type"], ltp, spot, r["strike"], t) if ltp and t > 0 else None
            g = greeks(r["instrument_type"], spot, r["strike"], t, iv) if iv else {}
            by_strike.setdefault(r["strike"], {"strike": r["strike"]})[r["instrument_type"]] = {
                "ltp": ltp, "oi": d.get("oi"), "volume": d.get("volume"), "iv": iv,
                "delta": g.get("delta"), "gamma": g.get("gamma"), "theta": g.get("theta"), "vega": g.get("vega"),
                "tradingsymbol": r["tradingsymbol"],
            }
        atm = strikes[atm_i]
        atm_row = by_strike.get(atm, {})
        ivs = [x["iv"] for x in (atm_row.get("CE"), atm_row.get("PE")) if x and x.get("iv")]
        fut_q = q.get(f"{exch}:{fut['tradingsymbol']}") if fut else None
        return {
            "underlying": u,
            "spot": spot,
            "updated_at": datetime.now(IST).isoformat(),
            "lot_size": chosen[0]["lot_size"] if chosen else None,
            "expiry_list": expiries,
            "expiries": [{
                "expiry": exp,
                "future": (fut_q or {}).get("last_price"),
                "atm_strike": atm,
                "atm_iv": sum(ivs) / len(ivs) if ivs else None,
                "strikes": [by_strike[k] for k in sorted(by_strike)],
            }],
            "greeks_source": "computed by the bridge (Black-Scholes, r=6%) from Kite last prices",
        }

    # ---- history (needs paid plan)
    def token_for(self, key: str) -> int:
        exch, sym = key.split(":", 1)
        for r in self.instruments(exch):
            if r["tradingsymbol"] == sym:
                return r["instrument_token"]
        raise KiteError(f"Instrument {key} not found", 502)

    def daily_closes(self, token: int, years: int) -> dict[str, float]:
        end = datetime.now(IST).date()
        start = end - timedelta(days=int(years * 365.25))
        out: dict[str, float] = {}
        cur = start
        while cur <= end:   # Kite returns at most 2000 days of daily candles per request
            stop = min(cur + timedelta(days=1999), end)
            data = self._call("GET", f"/instruments/historical/{token}/day",
                              params=[("from", f"{cur} 00:00:00"), ("to", f"{stop} 23:59:59")]) or {}
            for c in data.get("candles", []):
                out[str(c[0])[:10]] = float(c[4])
            cur = stop + timedelta(days=1)
        return out

    def history(self, underlying: str = "NIFTY", years: int = 15) -> dict:
        key = HISTORY_KEYS.get(underlying.upper())
        if not key:
            raise KiteError(f"History is available for {', '.join(HISTORY_KEYS)}.", 400)
        px = self.daily_closes(self.token_for(key), years)
        try:
            vix = self.daily_closes(self.token_for(VIX_KEY), years)
        except KiteError:
            vix = {}
        dates = sorted(px)
        return {
            "symbol": key, "iv_symbol": VIX_KEY if vix else None, "source": "Zerodha Kite",
            "dates": dates, "close": [px[d] for d in dates],
            "iv": [(vix[d] / 100.0 if d in vix else None) for d in dates],
        }


def today_ist() -> date:
    return datetime.now(IST).date()
