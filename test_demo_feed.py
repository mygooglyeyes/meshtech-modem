"""Tests for the demo feed: signed advert packet construction."""
from __future__ import annotations

import time

import pytest

from modem import DEMO_NAME, DEMO_SEED, make_demo_advert

nacl = pytest.importorskip("nacl")


def test_demo_advert_shape():
    rssi, snr, sig, data = modem_advert(1)
    assert -50 <= rssi <= -40
    assert snr == 9.5
    assert sig == -50
    # header + path_len + 32B pubkey + 4B ts + 64B sig + appdata
    assert len(data) == 2 + 32 + 4 + 64 + 1 + len(DEMO_NAME)
    assert data[0] == 0x11          # flood route, payload type 4, ver 0
    assert data[1] == 0x00          # path_len 0
    assert data.endswith(bytes([0x81]) + DEMO_NAME.encode())


def modem_advert(n):
    return make_demo_advert(n)


def test_demo_adverts_differ_and_timestamp_advances():
    _, _, _, a = make_demo_advert(1)
    _, _, _, b = make_demo_advert(2)
    assert a != b
    # timestamp sits at bytes 34..38 (little-endian u32) and must advance
    ts_a = int.from_bytes(a[34:38], "little")
    ts_b = int.from_bytes(b[34:38], "little")
    assert ts_b > ts_a


def test_demo_advert_signature_verifies():
    from nacl.signing import VerifyKey

    _, _, _, data = make_demo_advert(7)
    pubkey = data[2:34]
    ts = data[34:38]
    appdata = data[102:]
    signature = data[38:102]
    VerifyKey(pubkey).verify(pubkey + ts + appdata, signature)


def test_demo_identity_stable_across_restarts():
    from nacl.signing import SigningKey

    expected = bytes(SigningKey(DEMO_SEED).verify_key.encode())
    _, _, _, data = make_demo_advert(3)
    assert data[2:34] == expected
