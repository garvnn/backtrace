"""
Pair universe selection, and whether it reports its own provenance honestly.

pairs_config used to open with "Pre-validated stock pairs" above a dictionary
of sector groupings that nothing had tested, while pairs_finder - which runs a
real Engle-Granger test - was imported by nothing.
"""

import json
import os
import sys

import pytest

LIVE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LIVE_DIR)
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, LIVE_DIR)

import pairs_config


@pytest.fixture
def no_finder_output(monkeypatch, tmp_path):
    """pairs_finder has never been run."""
    monkeypatch.setattr(pairs_config, "PAIRS_OUTPUT", str(tmp_path / "absent.json"))
    monkeypatch.setattr(pairs_config, "_cache", None)
    yield
    pairs_config._cache = None


@pytest.fixture
def with_finder_output(monkeypatch, tmp_path):
    """pairs_finder has produced tested pairs."""
    path = tmp_path / "pairs_output.json"
    path.write_text(json.dumps([
        {"ticker_a": "KO", "ticker_b": "PEP", "pvalue": 0.001,
         "beta": 0.82, "spread_mean": 0.1, "spread_std": 0.05},
        {"ticker_a": "AMD", "ticker_b": "NVDA", "pvalue": 0.031,
         "beta": 1.4, "spread_mean": 0.2, "spread_std": 0.09},
    ]))
    monkeypatch.setattr(pairs_config, "PAIRS_OUTPUT", str(path))
    monkeypatch.setattr(pairs_config, "_cache", None)
    yield
    pairs_config._cache = None


# --- fallback behaviour -------------------------------------------------------

def test_falls_back_to_sector_candidates(no_finder_output):
    assert pairs_config.get_available_pairs("MCD") == ["YUM", "SBUX"]


def test_fallback_is_labelled_untested(no_finder_output):
    """The bug was claiming otherwise."""
    universe = pairs_config.validated_pairs()
    assert universe["source"] == "sector_candidates"
    assert "NOT tested" in universe["note"]


def test_untested_pairs_report_no_evidence(no_finder_output):
    assert pairs_config.pair_evidence("MCD", "YUM") is None
    details = pairs_config.get_pair_details("MCD")
    assert all(d["validated"] is False and d["pvalue"] is None for d in details)


# --- validated behaviour ------------------------------------------------------

def test_tested_pairs_take_precedence(with_finder_output):
    assert pairs_config.get_available_pairs("KO") == ["PEP"]
    assert pairs_config.validated_pairs()["source"] == "cointegration"


def test_evidence_travels_with_the_pair(with_finder_output):
    evidence = pairs_config.pair_evidence("KO", "PEP")
    assert evidence is not None
    assert evidence["pvalue"] == pytest.approx(0.001)
    assert evidence["beta"] == pytest.approx(0.82)


def test_cointegration_is_symmetric_but_beta_is_not(with_finder_output):
    """Both directions are tradable; only the tested direction carries a hedge ratio."""
    assert "KO" in pairs_config.get_available_pairs("PEP")
    assert pairs_config.pair_evidence("PEP", "KO")["beta"] is None
    assert pairs_config.pair_evidence("KO", "PEP")["beta"] is not None


def test_pairs_sorted_by_strength(with_finder_output, monkeypatch, tmp_path):
    path = tmp_path / "multi.json"
    path.write_text(json.dumps([
        {"ticker_a": "KO", "ticker_b": "WEAK", "pvalue": 0.049, "beta": 1.0},
        {"ticker_a": "KO", "ticker_b": "STRONG", "pvalue": 0.0001, "beta": 1.0},
    ]))
    monkeypatch.setattr(pairs_config, "PAIRS_OUTPUT", str(path))
    monkeypatch.setattr(pairs_config, "_cache", None)
    assert pairs_config.get_available_pairs("KO") == ["STRONG", "WEAK"]


def test_untested_ticker_still_falls_back(with_finder_output):
    """A ticker absent from the finder output keeps its sector candidates."""
    assert pairs_config.get_available_pairs("JPM") == ["BAC", "WFC", "C"]


# --- validation ---------------------------------------------------------------

def test_is_valid_pair_follows_the_active_universe(with_finder_output):
    assert pairs_config.is_valid_pair("KO", "PEP")
    assert not pairs_config.is_valid_pair("KO", "MSFT")


def test_a_ticker_is_not_a_pair_with_itself(no_finder_output):
    assert not pairs_config.is_valid_pair("KO", "KO")


def test_empty_input_is_not_valid(no_finder_output):
    assert not pairs_config.is_valid_pair("", "PEP")
    assert not pairs_config.is_valid_pair(None, None)
    assert pairs_config.get_available_pairs(None) == []


def test_case_and_whitespace_tolerated(with_finder_output):
    assert pairs_config.is_valid_pair(" ko ", "pep")


def test_corrupt_output_falls_back_rather_than_raising(monkeypatch, tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not json")
    monkeypatch.setattr(pairs_config, "PAIRS_OUTPUT", str(path))
    monkeypatch.setattr(pairs_config, "_cache", None)
    try:
        assert pairs_config.get_available_pairs("MCD") == ["YUM", "SBUX"]
        assert pairs_config.validated_pairs()["source"] == "sector_candidates"
    finally:
        pairs_config._cache = None
