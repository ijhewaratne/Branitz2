from __future__ import annotations

import json
from html.parser import HTMLParser
from pathlib import Path

import pytest

from branitz_heat_decision.uhdc.report_builder import save_reports

pytestmark = pytest.mark.integration


class _StrictHTMLParser(HTMLParser):
    """
    Minimal offline HTML sanity checker.
    - Ensures HTML is at least parseable by the stdlib parser (no catastrophic markup).
    Note: This is not a full W3C validator; it is designed to be CI-safe (no network).
    """

    def error(self, message: str) -> None:  # pragma: no cover
        raise AssertionError(message)


def _minimal_report_payload() -> dict:
    return {
        "cluster_id": "ST_TEST",
        "contract": {
            "cluster_id": "ST_TEST",
            "district_heating": {
                "feasible": True,
                "reasons": ["DH_OK"],
                "lcoh": {"median": 70.0, "p05": 60.0, "p95": 90.0},
                "co2": {"median": 80.0, "p05": 60.0, "p95": 120.0},
                "hydraulics": {"v_max_ms": 1.2, "velocity_ok": True, "dp_ok": True, "loss_share_pct": 3.0},
                "losses": {"pump_power_kw": 10.0, "loss_share_pct": 3.0},
            },
            "heat_pumps": {
                "feasible": True,
                "reasons": ["HP_OK"],
                "lcoh": {"median": 75.0, "p05": 65.0, "p95": 110.0},
                "co2": {"median": 120.0, "p05": 90.0, "p95": 200.0},
                "lv_grid": {"max_feeder_loading_pct": 80.0, "voltage_violations_total": 0},
            },
            "monte_carlo": {"dh_wins_fraction": 0.6, "hp_wins_fraction": 0.4, "n_samples": 500, "seed": 42},
        },
        "decision": {"choice": "DH", "robust": False, "reason_codes": ["COST_DOMINANT_DH"], "metrics_used": {}},
        "explanation": "Test explanation",
        "sources": {},
        "metadata": {"timestamp_utc": "2026-01-01T00:00:00Z"},
    }


def test_report_html_validates_offline(tmp_path: Path) -> None:
    """
    Offline HTML validation:
    - We avoid external W3C validators (network) and instead enforce parseability + minimal structure.
    """
    report = _minimal_report_payload()
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    map_path = out_dir / "interactive_map.html"
    map_path.write_text("<html></html>", encoding="utf-8")

    save_reports(report, out_dir=out_dir, map_path=map_path)
    html_path = out_dir / "uhdc_report_ST_TEST.html"
    assert html_path.exists()

    html = html_path.read_text(encoding="utf-8")
    # Case-insensitive doctype check (report uses <!DOCTYPE html>)
    assert "<!DOCTYPE" in html.upper()
    assert "<html" in html.lower()
    assert "<head" in html.lower()
    assert "<body" in html.lower()

    parser = _StrictHTMLParser()
    parser.feed(html)
    parser.close()


def test_report_json_roundtrip(tmp_path: Path) -> None:
    """
    Ensure JSON export/import fidelity: save_reports() should write a JSON file that round-trips identically.
    """
    report = _minimal_report_payload()
    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    save_reports(report, out_dir=out_dir, include_html=False, include_markdown=False, include_json=True)
    json_path = out_dir / "uhdc_report_ST_TEST.json"
    assert json_path.exists()

    loaded = json.loads(json_path.read_text(encoding="utf-8"))
    assert loaded == report

