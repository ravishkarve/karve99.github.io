"""Offline tests for the Sensibull bridge. Run: python3 -m unittest options/bridge/test_bridge.py

The fixture mirrors the response shapes read by the open-source sensibull-quotes
package (instrument_metacache + live_derivative_prices)."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(__file__))
import sensibull_bridge as sb  # noqa: E402

META = {
    "derivatives": {
        "NIFTY": {
            "derivatives": {
                "2026-09-29": {
                    "FUT": {"instrument_token": 9001, "tradingsymbol": "NIFTY26SEPFUT"},
                    "options": {
                        "25000": {
                            "CE": {"instrument_token": 111, "tradingsymbol": "NIFTY2692925000CE", "lot_size": 75},
                            "PE": {"instrument_token": 112, "tradingsymbol": "NIFTY2692925000PE", "lot_size": 75},
                        },
                        "25100": {
                            "CE": {"instrument_token": 121, "tradingsymbol": "NIFTY2692925100CE", "lot_size": 75},
                            "PE": {"instrument_token": 122, "tradingsymbol": "NIFTY2692925100PE", "lot_size": 75},
                        },
                    },
                }
            }
        }
    }
}

LIVE = {
    "status": True,
    "data": {
        "underlying_token": 256265,
        "underlying_price": 25040.5,
        "last_updated_at": "2026-09-25T10:15:00+05:30",
        "per_expiry_data": {
            "2026-09-29": {
                "atm_strike": 25000, "atm_iv": 11.8, "future_price": 25061.0, "max_oi": 1e6,
                "options": [
                    {"token": 111, "last_price": 120.5, "oi": 900000, "volume": 5e6, "is_liquid": True,
                     "greeks_with_iv": {"delta": 0.55, "theta": -18.2, "gamma": 0.0012, "vega": 9.1, "iv": 11.9}},
                    {"token": 112, "last_price": 80.2, "oi": 1100000, "volume": 6e6, "is_liquid": True,
                     "greeks_with_iv": {"delta": -0.45, "theta": -16.0, "gamma": 0.0012, "vega": 9.0, "iv": 12.4}},
                    {"token": 121, "last_price": 72.0, "oi": 700000, "volume": 3e6, "is_liquid": True,
                     "greeks_with_iv": {"delta": 0.40, "theta": -17.0, "gamma": 0.0011, "vega": 8.8, "iv": 11.6}},
                    {"token": 999, "last_price": 1.0, "oi": 1, "volume": 1, "is_liquid": False, "greeks_with_iv": None},
                ],
            }
        },
    },
}


class NormaliseTest(unittest.TestCase):
    def setUp(self):
        sb._META.update(at=0.0, data=None, tokens={})

    def test_chain_is_normalised(self):
        def fake(url, **_):
            return META if "metacache" in url else LIVE
        with mock.patch.object(sb, "http_json", side_effect=fake) as m:
            chain = sb.live_chain("nifty")
        self.assertTrue(any(str(sb.FALLBACK_TOKENS["NIFTY"]) in c.args[0] for c in m.call_args_list))
        self.assertEqual(chain["underlying"], "NIFTY")
        self.assertEqual(chain["spot"], 25040.5)
        self.assertEqual(chain["lot_size"], 75)
        (exp,) = chain["expiries"]
        self.assertEqual(exp["expiry"], "2026-09-29")
        self.assertEqual([s["strike"] for s in exp["strikes"]], [25000.0, 25100.0])
        k0 = exp["strikes"][0]
        self.assertEqual(k0["CE"]["ltp"], 120.5)
        self.assertEqual(k0["PE"]["iv"], 12.4)
        self.assertEqual(k0["CE"]["tradingsymbol"], "NIFTY2692925000CE")
        self.assertNotIn("PE", exp["strikes"][1])   # only the CE was quoted
        # unknown token 999 without strike info is dropped

    def test_unknown_underlying_needs_token(self):
        with self.assertRaises(sb.BridgeError):
            sb.underlying_token("NOTANINDEX", {})

    def test_session_token_parsing(self):
        self.assertEqual(sb.parse_token("abc"), {"access_token": "abc"})
        self.assertEqual(sb.parse_token("a=1; b=2"), {"a": "1", "b": "2"})

    def test_mask(self):
        self.assertEqual(sb.mask("9876543210"), "98******10")


if __name__ == "__main__":
    unittest.main()
