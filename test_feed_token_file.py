"""Tests for the .feed_token file handling."""
from __future__ import annotations

import os

import modem


def test_load_feed_token_reads_file(tmp_path):
    cfg = tmp_path / "modem.conf"
    cfg.write_text("port = 5055\n")
    token_file = tmp_path / ".feed_token"
    token_file.write_text("sekrit\n")
    assert modem.load_feed_token(str(cfg)) == "sekrit"


def test_load_feed_token_missing_file_means_no_token(tmp_path):
    cfg = tmp_path / "modem.conf"
    cfg.write_text("port = 5055\n")
    assert modem.load_feed_token(str(cfg)) == ""


def test_load_feed_token_empty_file_means_no_token(tmp_path):
    cfg = tmp_path / "modem.conf"
    cfg.write_text("port = 5055\n")
    (tmp_path / ".feed_token").write_text("\n")
    assert modem.load_feed_token(str(cfg)) == ""


def test_load_feed_token_ignores_extra_lines_and_spaces(tmp_path):
    cfg = tmp_path / "modem.conf"
    cfg.write_text("port = 5055\n")
    (tmp_path / ".feed_token").write_text("  spaced secret  \nsecond line\n")
    assert modem.load_feed_token(str(cfg)) == "spaced secret"
