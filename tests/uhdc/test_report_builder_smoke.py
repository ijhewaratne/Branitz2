from __future__ import annotations

import json
from pathlib import Path

from branitz_heat_decision.uhdc.report_builder import save_reports


def test_save_reports_writes_html_and_md(tmp_path: Path):
    # Minimal report payload shape expected by report_builder templates.
    report = {
        "cluster_id": "ST_TEST",
        "contract": {
            "cluster_id": "ST_TEST",
            "district_heating": {
                "feasible": True,
                "reasons": ["DH_OK"],
                "lcoh": {"median": 70.0, "p05": 60.0, "p95": 90.0},
                "co2": {"median": 80.0, "p05": 60.0, "p95": 120.0},
                "hydraulics": {"v_max_ms": 1.2, "velocity_ok": True},
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

    out_dir = tmp_path / "out"
    out_dir.mkdir(parents=True, exist_ok=True)

    # write a map placeholder; report_builder can embed/link it in HTML
    map_path = out_dir / "interactive_map.html"
    map_path.write_text("<html></html>", encoding="utf-8")

    save_reports(report, out_dir=out_dir, map_path=map_path)

    html_path = out_dir / "uhdc_report_ST_TEST.html"
    md_path = out_dir / "uhdc_explanation_ST_TEST.md"
    json_path = out_dir / "uhdc_report_ST_TEST.json"

    assert html_path.exists()
    assert md_path.exists()
    assert json_path.exists()
    # Ensure JSON is readable
    json.loads(json_path.read_text(encoding="utf-8"))

    # Auditability: key metrics should include JSON source-path tooltips in HTML
    html = html_path.read_text(encoding="utf-8")
    assert 'data-source="district_heating.lcoh.median"' in html
    assert 'data-source="heat_pumps.lcoh.median"' in html
    assert 'data-source="district_heating.co2.median"' in html
    assert 'data-source="heat_pumps.co2.median"' in html

    # Standards references: EN 13941-1 ×3 and VDE-AR-N 4100 ×2 in the HTML footer
    assert html.count("DIN EN 13941-1:2023") == 3
    assert html.count("VDE-AR-N 4100:2022") == 2

    md = md_path.read_text(encoding="utf-8")
    assert md.count("DIN EN 13941-1:2023") == 3
    assert md.count("VDE-AR-N 4100:2022") == 2
