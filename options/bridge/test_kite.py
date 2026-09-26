"""Offline tests for the Kite client. Run: python3 -m unittest options/bridge/test_kite.py

A fake opener stands in for api.kite.trade, returning the response shapes documented for
Kite Connect v3 (JSON envelope {"status": "success", "data": ...}, CSV instrument dumps)."""
import hashlib
import io
import json
import os
import sys
import unittest
import urllib.error
import urllib.parse
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(__file__))
import kite as K  # noqa: E402

EXP1 = (datetime.now(K.IST).date() + timedelta(days=5)).isoformat()
EXP2 = (datetime.now(K.IST).date() + timedelta(days=12)).isoformat()
PAST = (datetime.now(K.IST).date() - timedelta(days=3)).isoformat()
SPOT = 25040.0


def instruments_csv():
    rows = ["instrument_token,exchange_token,tradingsymbol,name,last_price,expiry,strike,tick_size,lot_size,instrument_type,segment,exchange"]
    tok = 1000
    for exp in (PAST, EXP1, EXP2):
        for k in range(24500, 25650, 50):
            for t in ("CE", "PE"):
                tok += 1
                rows.append(f'{tok},{tok},NIFTY{exp.replace("-", "")}{k}{t},"NIFTY",0,{exp},{k},0.05,75,{t},NFO-OPT,NFO')
    rows.append(f'9001,9001,NIFTYFUT1,"NIFTY",0,{EXP2},0,0.1,75,FUT,NFO-FUT,NFO')
    rows.append('9100,9100,BANKNIFTYX,"BANKNIFTY",0,' + EXP1 + ',55000,0.05,35,CE,NFO-OPT,NFO')
    return "\n".join(rows)


class FakeResp(io.BytesIO):
    def __init__(self, body: bytes, ctype: str):
        super().__init__(body)
        self.headers = {"Content-Type": ctype}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeKite:
    def __init__(self):
        self.calls = []
        self.expired = False

    def __call__(self, req, timeout=None):
        u = urllib.parse.urlsplit(req.full_url)
        q = urllib.parse.parse_qs(u.query)
        self.calls.append((req.get_method(), u.path, q, dict(req.header_items()), req.data))
        ok = lambda d: FakeResp(json.dumps({"status": "success", "data": d}).encode(), "application/json")
        if self.expired and u.path != "/session/token":
            body = json.dumps({"status": "error", "message": "Incorrect `api_key` or `access_token`.", "error_type": "TokenException"}).encode()
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(body))
        if u.path == "/session/token" and req.get_method() == "DELETE":
            return ok(True)
        if u.path == "/session/token" and req.get_method() == "POST":
            form = urllib.parse.parse_qs(req.data.decode())
            expect = hashlib.sha256(b"key123" + b"reqtok" + b"sec456").hexdigest()
            assert form["checksum"][0] == expect, "bad checksum"
            return ok({"access_token": "acc789", "user_id": "AB1234", "user_name": "Test User", "broker": "ZERODHA"})
        if u.path == "/instruments/NFO":
            return FakeResp(instruments_csv().encode(), "text/csv")
        if u.path == "/quote":
            out = {}
            for key in q["i"]:
                if key == "NSE:NIFTY 50":
                    out[key] = {"last_price": SPOT}
                elif key.endswith("FUT1"):
                    out[key] = {"last_price": SPOT + 60}
                else:
                    sym = key.split(":")[1]
                    k = float(sym[-7:-2]); t = sym[-2:]
                    T = K.years_to_expiry(EXP1)
                    px = round(K.bs_price(t, SPOT, k, T, 0.13 if t == "CE" else 0.135), 2)
                    out[key] = {"last_price": px, "oi": 100000, "volume": 500000}
            return ok(out)
        if u.path == "/user/margins":
            return ok({"equity": {"net": 250000.0, "available": {"live_balance": 180000.0, "cash": 200000.0}, "utilised": {"debits": 70000.0, "span": 50000.0, "exposure": 20000.0}}})
        if u.path == "/portfolio/positions":
            return ok({"net": [{"tradingsymbol": f"NIFTY{EXP1.replace('-', '')}25000PE", "exchange": "NFO", "quantity": -75, "average_price": 90.5, "last_price": 80.0, "pnl": 787.5}], "day": []})
        if u.path.startswith("/instruments/historical/"):
            start = datetime.strptime(q["from"][0][:10], "%Y-%m-%d")
            candles = [[(start + timedelta(days=i)).strftime("%Y-%m-%dT00:00:00+0530"), 1, 1, 1, 20000 + i, 0] for i in range(3)]
            return ok({"candles": candles})
        raise AssertionError("unexpected call " + u.path)


class KiteTest(unittest.TestCase):
    def setUp(self):
        self.fake = FakeKite()
        self.k = K.Kite("key123", "sec456")
        self.k.opener = self.fake

    def login(self):
        url = self.k.login_url()
        state = urllib.parse.parse_qs(urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)["redirect_params"][0])["state"][0]
        return self.k.complete_login("reqtok", state)

    def test_login_url_and_session(self):
        url = self.k.login_url()
        self.assertTrue(url.startswith("https://kite.zerodha.com/connect/login?"))
        self.assertIn("api_key=key123", url)
        self.assertIn("v=3", url)
        user = self.login()
        self.assertEqual(user["user_id"], "AB1234")
        self.assertTrue(self.k.logged_in())

    def test_login_state_mismatch_rejected(self):
        self.k.login_url()
        with self.assertRaises(K.KiteError):
            self.k.complete_login("reqtok", "forged")
        self.assertFalse(self.k.logged_in())

    def test_callback_without_pending_login_rejected(self):
        with self.assertRaises(K.KiteError):
            self.k.complete_login("reqtok", None)

    def test_auth_header(self):
        self.login()
        self.k.margins()
        _, path, _, headers, _ = self.fake.calls[-1]
        self.assertEqual(path, "/user/margins")
        self.assertEqual(headers.get("Authorization"), "token key123:acc789")
        self.assertEqual(headers.get("X-kite-version"), "3")

    def test_chain(self):
        self.login()
        c = self.k.chain("NIFTY")
        self.assertEqual(c["spot"], SPOT)
        self.assertEqual(c["expiry_list"], [EXP1, EXP2])          # past expiry dropped
        (e,) = c["expiries"]
        self.assertEqual(e["expiry"], EXP1)
        self.assertEqual(e["future"], SPOT + 60)
        self.assertEqual(e["atm_strike"], 25050.0)
        row = next(s for s in e["strikes"] if s["strike"] == 25000.0)
        self.assertAlmostEqual(row["CE"]["iv"], 0.13, places=2)    # IV recovered from price
        self.assertAlmostEqual(row["PE"]["iv"], 0.135, places=2)
        self.assertGreater(row["CE"]["delta"], 0.5)
        self.assertLess(row["PE"]["delta"], 0)
        self.assertEqual(row["CE"]["oi"], 100000)
        self.assertEqual(c["lot_size"], 75)
        c2 = self.k.chain("NIFTY", EXP2)
        self.assertEqual(c2["expiries"][0]["expiry"], EXP2)

    def test_account_enriches_positions(self):
        self.login()
        a = self.k.account()
        self.assertEqual(a["margins"]["available"], 180000.0)
        (p,) = a["positions"]
        self.assertEqual((p["underlying"], p["strike"], p["option_type"], p["expiry"]), ("NIFTY", 25000.0, "PE", EXP1))

    def test_expired_session_clears_token(self):
        self.login()
        self.fake.expired = True
        with self.assertRaises(K.KiteError) as cm:
            self.k.margins()
        self.assertEqual(cm.exception.kind, "TokenException")
        self.assertFalse(self.k.logged_in())

    def test_history_chunks(self):
        self.login()
        self.k._instruments["NSE"] = (datetime.now(K.IST).strftime("%Y-%m-%d"), [
            {"tradingsymbol": "NIFTY 50", "instrument_token": 256265}, {"tradingsymbol": "INDIA VIX", "instrument_token": 264969}])
        h = self.k.history("NIFTY", years=12)
        hist_calls = [c for c in self.fake.calls if c[1].startswith("/instruments/historical/256265/")]
        self.assertGreaterEqual(len(hist_calls), 3)                # 12 years > 2000-day limit
        self.assertEqual(len(h["dates"]), len(h["close"]))
        self.assertTrue(all(v is not None for v in h["iv"]))

    def test_logout_clears_session_even_if_kite_errors(self):
        self.login()
        self.k.opener = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("network down"))
        self.k.logout()
        self.assertFalse(self.k.logged_in())

    def test_iv_roundtrip(self):
        T = 20 / 365
        p = K.bs_price("PE", 25000, 24500, T, 0.18)
        self.assertAlmostEqual(K.implied_vol("PE", p, 25000, 24500, T), 0.18, places=4)


if __name__ == "__main__":
    unittest.main()
