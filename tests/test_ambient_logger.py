"""SwitchBot API の署名と .env 読み込みのテスト。"""

import base64
import hashlib
import hmac
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import ambient_logger as al  # noqa: E402


def test_sign_matches_spec():
    h = al.auth_headers("tok", "sec", t_ms=1700000000000, nonce="abc")
    expect = base64.b64encode(hmac.new(b"sec", b"tok1700000000000abc", hashlib.sha256).digest()).decode()
    assert h["sign"] == expect
    assert h["Authorization"] == "tok" and h["t"] == "1700000000000" and h["nonce"] == "abc"


def test_load_env(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# comment\nSWITCHBOT_TOKEN=abc\nSWITCHBOT_SECRET='x=y'\n\n")
    assert al.load_env(p) == {"SWITCHBOT_TOKEN": "abc", "SWITCHBOT_SECRET": "x=y"}
