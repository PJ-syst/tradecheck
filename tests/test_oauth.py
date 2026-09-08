import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.credentials import save, load
from backend.oauth import official_url, authorization_parameters, callback_code, ENDPOINT


class OAuthTests(unittest.TestCase):
    def test_pkce_challenge_matches_rfc_vector_and_binds_resource(self):
        params = authorization_parameters("state", "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk")
        self.assertEqual(params["code_challenge"], "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM")
        self.assertEqual(params["resource"], ENDPOINT)
        self.assertEqual(params["code_challenge_method"], "S256")

    def test_callback_requires_exact_state_and_single_code(self):
        self.assertEqual(callback_code("/callback?state=abc&code=xyz", "abc"), "xyz")
        for path in ["/callback?state=wrong&code=x", "/callback?state=abc&code=x&code=y", "/callback?state=abc&error=denied", "/other?state=abc&code=x", "/callback?state=abc&state=abc&code=x"]:
            with self.assertRaises(ValueError):
                callback_code(path, "abc")

    def test_metadata_cannot_redirect_credentials_off_binance(self):
        for value in ["http://accounts.binance.com/token", "https://binance.com.evil.test/token", "https://evil.test/token", "https://user:password@binance.com/token", "https://agent.binance.com:444/token"]:
            with self.assertRaises(ValueError):
                official_url(value)
        self.assertEqual(official_url("https://accounts.binance.com/oauth-agentic/token"), "https://accounts.binance.com/oauth-agentic/token")

    @unittest.skipUnless(os.name == "nt", "Windows user encryption")
    def test_credentials_are_encrypted_and_roundtrip_without_plaintext(self):
        with tempfile.TemporaryDirectory() as folder, patch("backend.credentials.ROOT", Path(folder)):
            save("openai", {"api_key": "synthetic-secret-value"})
            raw = (Path(folder) / "openai.credential").read_bytes()
            self.assertNotIn(b"synthetic-secret-value", raw)
            self.assertEqual(load("openai"), {"api_key": "synthetic-secret-value"})
            self.assertEqual(load("binance"), {})
            (Path(folder) / "openai.credential").write_bytes(b"corrupted")
            with self.assertRaises(ValueError):
                load("openai")
