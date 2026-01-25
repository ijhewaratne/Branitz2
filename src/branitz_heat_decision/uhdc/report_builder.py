"""
Report Builder
- Render reports in multiple formats (HTML, Markdown, PDF)
- Include graphs and tables
- Embed interactive maps
"""

import base64
from io import BytesIO
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Dict, Any, Union, Optional, Mapping, List

import matplotlib.pyplot as plt
import seaborn as sns
from jinja2 import Environment, BaseLoader, TemplateNotFound, FileSystemLoader

logger = logging.getLogger(__name__)

# Standards references (for auditability + explicit compliance mentions)
STANDARDS_REFERENCES = {
    "EN_13941_1": {
        "name": "DIN EN 13941-1:2023",
        "url": "https://cdn.standards.iteh.ai/samples/63107/9679243e93d447d8b7fff49c655c8eba/EN-13941-1-2023.pdf",
        "description": "District heating pipes - Design and installation",
    },
    "VDE_AR_N_4100": {
        "name": "VDE-AR-N 4100:2022",
        "url": "https://www.vde.com/resource/blob/951050/aa29e1e9b568a3d9e59b83006b00e4bf/vde-ar-n-4100-2022-06-data.pdf",
        "description": "Technical connection rules for low-voltage grids",
    },
}

# Default Jinja2 templates (embedded for portability)
# In production, these would be in src/branitz_heat_decision/templates/
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>UHDC Report - {{ cluster_id }}</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <script src="https://cdn.plot.ly/plotly-latest.min.js"></script>
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css">
    <!-- DataTables (Bootstrap 5 theme) -->
    <link rel="stylesheet" href="https://cdn.datatables.net/1.13.6/css/dataTables.bootstrap5.min.css">
    <script src="https://code.jquery.com/jquery-3.7.1.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/jquery.dataTables.min.js"></script>
    <script src="https://cdn.datatables.net/1.13.6/js/dataTables.bootstrap5.min.js"></script>
    <style>
        /* Glassmorphism metric cards + visual hierarchy */
        .metric-card {
            border: none;
            border-radius: 16px;
            background: rgba(255, 255, 255, 0.85);
            backdrop-filter: blur(10px);
            box-shadow: 0 4px 30px rgba(0, 0, 0, 0.1);
            transition: transform 0.2s ease, box-shadow 0.2s ease;
        }
        .metric-card:hover {
            transform: translateY(-4px);
            box-shadow: 0 8px 40px rgba(0, 0, 0, 0.15);
        }
        .metric-icon {
            width: 48px;
            height: 48px;
            border-radius: 12px;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 1.5rem;
            margin-bottom: 12px;
        }
        .dh-icon { background: linear-gradient(135deg, #28a745, #20c997); color: white; }
        .hp-icon { background: linear-gradient(135deg, #dc3545, #fd7e14); color: white; }
        .metric-value {
            font-size: 2rem;
            font-weight: 700;
            line-height: 1;
            margin-bottom: 4px;
        }
        .metric-label {
            font-size: 0.875rem;
            color: #6c757d;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }
        .metric-ci {
            font-size: 0.75rem;
            color: #6c757d;
        }
        .robust-badge { background-color: #28a745; }
        .sensitive-badge { background-color: #ffc107; color: #000; }
        .uncertain-badge { background-color: #6c757d; }
        .chart-container { max-width: 600px; margin: auto; }
        .map-container {
            position: relative;
            min-height: 500px;
        }
        .map-iframe {
            width: 100%;
            height: 500px;
            border: none;
            opacity: 0;
            transition: opacity 0.5s ease;
        }
        .map-loading-spinner {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            z-index: 10;
        }
        @media (max-width: 768px) {
            .map-iframe { height: 400px; }
            .nav-tabs .nav-link { font-size: 0.875rem; padding: 0.5rem 0.75rem; }
        }
        /* Hover tooltips for auditability: show contract JSON path */
        .source-hint {
            position: relative;
            cursor: help;
            border-bottom: 1px dotted #999;
        }
        .source-hint:hover::after {
            content: attr(data-source);
            position: absolute;
            bottom: 120%;
            left: 0;
            background: #222;
            color: #fff;
            padding: 4px 8px;
            border-radius: 4px;
            font-size: 12px;
            white-space: nowrap;
            z-index: 1000;
        }
    </style>
</head>
<body>
    <div class="container-fluid py-4">
        <!-- Header -->
        <div class="row mb-4">
            <div class="col-12 d-flex justify-content-between align-items-start gap-3 flex-wrap">
                <div>
                <h1 class="h2 mb-0">Urban Heat Decision Report</h1>
                <small class="text-muted">Cluster: {{ cluster_id }} | Generated: {{ metadata.timestamp }}</small>
                </div>
                <div class="btn-group ms-3" role="group" aria-label="Export options">
                    <button type="button" class="btn btn-sm btn-outline-primary" onclick="downloadJSON()">📥 JSON</button>
                    <button type="button" class="btn btn-sm btn-outline-primary" onclick="downloadCSV()">📊 CSV</button>
                    <button type="button" class="btn btn-sm btn-outline-primary" onclick="window.print()">🖨️ Print</button>
                </div>
            </div>
        </div>

        <!-- Decision Banner -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="alert alert-{{ 'success' if decision.choice == 'DH' else 'info' if decision.choice == 'HP' else 'warning' }}">
                    <h2 class="h4 mb-0">
                        Recommendation: <strong>{{ decision.choice }}</strong>
                        <span class="badge {{ 'robust-badge' if decision.robust else 'sensitive-badge' }} ms-2">
                            {{ 'Robust' if decision.robust else 'Sensitive' }}
                        </span>
                    </h2>
                </div>
            </div>
        </div>

        <!-- Executive Summary Dashboard (at-a-glance) -->
        <div class="row mb-5">
            <div class="col-md-3">
                <div class="card text-center metric-card border-0 bg-light">
                    <div class="card-body">
                        <div class="metric-value text-{{ 'success' if decision.choice == 'DH' else 'danger' if decision.choice == 'HP' else 'warning' }}">
                            <strong>{{ decision.choice }}</strong>
                        </div>
                        <div class="metric-label">Recommendation</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center metric-card border-0 bg-light">
                    <div class="card-body">
                        <div class="metric-value">
                            {% if decision.robust %}
                                <span class="badge bg-success">✓ Robust</span>
                            {% elif 'SENSITIVE_DECISION' in decision.reason_codes %}
                                <span class="badge bg-warning text-dark">⚠ Sensitive</span>
                            {% else %}
                                <span class="badge bg-secondary">N/A</span>
                            {% endif %}
                        </div>
                        <div class="metric-label">Confidence</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center metric-card border-0 bg-light">
                    <div class="card-body">
                        <div class="metric-value">
                            {% set dh_lcoh = contract.district_heating.lcoh.median %}
                            {% set hp_lcoh = contract.heat_pumps.lcoh.median %}
                            {% if dh_lcoh is not none and hp_lcoh is not none and dh_lcoh != 0 %}
                                {% set cost_diff = ((dh_lcoh - hp_lcoh) / dh_lcoh * 100) %}
                                {% if cost_diff > 5 %}
                                    <span class="text-success">{{ cost_diff|round(0) }}% cheaper</span>
                                {% elif cost_diff < -5 %}
                                    <span class="text-danger">{{ (-cost_diff)|round(0) }}% more expensive</span>
                                {% else %}
                                    Within 5%
                                {% endif %}
                            {% else %}
                                <span class="text-muted">N/A</span>
                            {% endif %}
                        </div>
                        <div class="metric-label">Cost Impact</div>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-center metric-card border-0 bg-light">
                    <div class="card-body">
                        <div class="metric-value">
                            {% set dh_co2 = contract.district_heating.co2.median %}
                            {% set hp_co2 = contract.heat_pumps.co2.median %}
                            {% if dh_co2 is not none and hp_co2 is not none %}
                                {% if dh_co2 < hp_co2 %}
                                    <span class="text-success">DH better</span>
                                {% elif hp_co2 < dh_co2 %}
                                    <span class="text-success">HP better</span>
                                {% else %}
                                    <span class="text-muted">Tie</span>
                                {% endif %}
                            {% else %}
                                <span class="text-muted">N/A</span>
                            {% endif %}
                        </div>
                        <div class="metric-label">CO₂ Advantage</div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Summary -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">Executive Summary</h5>
                        <p class="card-text">{{ explanation|safe }}</p>
                    </div>
                </div>
            </div>
        </div>

        <!-- Key Metrics -->
        <div class="row mb-4">
            <!-- DH Metrics -->
            <div class="col-md-6">
                <div class="card metric-card">
                    <div class="card-body">
                        <div class="metric-icon dh-icon">🔥</div>
                        <div class="metric-label">LCOH (median)</div>
                        <div class="metric-value">
                            <span class="source-hint" data-source="district_heating.lcoh.median">
                                {{ contract.district_heating.lcoh.median|round(1) }}
                            </span> <span style="font-size: 1rem; font-weight: 600;">€/MWh</span>
                        </div>
                        <small class="metric-ci">
                            95% CI:
                            <span class="source-hint" data-source="district_heating.lcoh.p05">{{ contract.district_heating.lcoh.p05|round(1) }}</span>
                            -
                            <span class="source-hint" data-source="district_heating.lcoh.p95">{{ contract.district_heating.lcoh.p95|round(1) }}</span>
                            €/MWh
                        </small>
                        <hr>
                        <div class="row text-center g-2">
                            <div class="col-4">
                                <div class="metric-label">Feasible</div>
                                <div class="h4 mb-0">{{ '✓' if contract.district_heating.feasible else '✗' }}</div>
                            </div>
                            <div class="col-4">
                                <div class="metric-label">Max Velocity</div>
                                <div class="h5 mb-0">
                                    <span class="source-hint" data-source="district_heating.hydraulics.v_max_ms">
                                        {{ contract.district_heating.hydraulics.v_max_ms|round(2) }}
                                    </span> m/s
                                </div>
                            </div>
                            <div class="col-4">
                                <div class="metric-label">Losses</div>
                                <div class="h5 mb-0">
                                    <span class="source-hint" data-source="district_heating.losses.loss_share_pct">
                                        {{ contract.district_heating.losses.loss_share_pct|round(1) }}
                                    </span>%
                                </div>
                            </div>
                        </div>
                        <hr>
                        <div class="metric-label">CO₂ (median)</div>
                        <div class="h5 mb-0">
                            <span class="source-hint" data-source="district_heating.co2.median">
                                {{ contract.district_heating.co2.median|round(0) }}
                            </span> kg/MWh
                        </div>
                    </div>
                </div>
            </div>

            <!-- HP Metrics -->
            <div class="col-md-6">
                <div class="card metric-card">
                    <div class="card-body">
                        <div class="metric-icon hp-icon">⚡</div>
                        <div class="metric-label">LCOH (median)</div>
                        <div class="metric-value">
                            <span class="source-hint" data-source="heat_pumps.lcoh.median">
                                {{ contract.heat_pumps.lcoh.median|round(1) }}
                            </span> <span style="font-size: 1rem; font-weight: 600;">€/MWh</span>
                        </div>
                        <small class="metric-ci">
                            95% CI:
                            <span class="source-hint" data-source="heat_pumps.lcoh.p05">{{ contract.heat_pumps.lcoh.p05|round(1) }}</span>
                            -
                            <span class="source-hint" data-source="heat_pumps.lcoh.p95">{{ contract.heat_pumps.lcoh.p95|round(1) }}</span>
                            €/MWh
                        </small>
                        <hr>
                        <div class="row text-center g-2">
                            <div class="col-4">
                                <div class="metric-label">Feasible</div>
                                <div class="h4 mb-0">{{ '✓' if contract.heat_pumps.feasible else '✗' }}</div>
                            </div>
                            <div class="col-4">
                                <div class="metric-label">Max Loading</div>
                                <div class="h5 mb-0">
                                    <span class="source-hint" data-source="heat_pumps.lv_grid.max_feeder_loading_pct">
                                        {{ contract.heat_pumps.lv_grid.max_feeder_loading_pct|round(0) }}
                                    </span>%
                                </div>
                            </div>
                            <div class="col-4">
                                <div class="metric-label">Violations</div>
                                <div class="h5 mb-0">
                                    {% set v_viol = contract.heat_pumps.lv_grid.voltage_violations_total or 0 %}
                                    {% set l_viol = contract.heat_pumps.lv_grid.line_violations_total or 0 %}
                                    {% set total_viol = v_viol + l_viol %}
                                    <span class="source-hint" data-source="heat_pumps.lv_grid">
                                        {{ total_viol }}
                                        {% if v_viol > 0 or l_viol > 0 %}
                                            <small class="d-block text-muted" style="font-size: 0.7rem;">
                                                ({{ v_viol }} voltage, {{ l_viol }} line)
                                            </small>
                                        {% endif %}
                                    </span>
                                </div>
                            </div>
                        </div>
                        <hr>
                        <div class="metric-label">CO₂ (median)</div>
                        <div class="h5 mb-0">
                            <span class="source-hint" data-source="heat_pumps.co2.median">
                                {{ contract.heat_pumps.co2.median|round(0) }}
                            </span> kg/MWh
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Charts -->
        <div class="row mb-4">
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">LCOH Comparison</h5>
                        <div class="chart-container">
                            {{ lcoh_chart_html|safe }}
                        </div>
                    </div>
                </div>
            </div>
            <div class="col-md-6">
                <div class="card">
                    <div class="card-body">
                        <h5 class="card-title">Monte Carlo Robustness</h5>
                        <div class="chart-container">
                            {{ robustness_chart_html|safe }}
                        </div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Technical Details Table -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Detailed Feasibility Assessment</h5>
                    </div>
                    <div class="card-body p-0">
                        <table class="table table-sm mb-0" id="tech-details-table">
                            <thead>
                                <tr>
                                    <th>Criteria</th>
                                    <th>Standard</th>
                                    <th>District Heating</th>
                                    <th>Heat Pumps</th>
                                    <th>Status</th>
                                </tr>
                            </thead>
                            <tbody>
                                <tr class="{{ 'table-success' if contract.district_heating.hydraulics.velocity_ok else 'table-danger' }}">
                                    <td>Velocity</td>
                                    <td>EN 13941-1 (≤1.5 m/s)</td>
                                    <td><span class="source-hint" data-source="district_heating.hydraulics.v_max_ms">{{ contract.district_heating.hydraulics.v_max_ms|round(2) }} m/s</span></td>
                                    <td>N/A</td>
                                    <td>{{ '✓ Pass' if contract.district_heating.hydraulics.velocity_ok else '✗ Fail' }}</td>
                                </tr>
                                <tr class="{{ 'table-success' if contract.district_heating.hydraulics.dp_ok else 'table-danger' }}">
                                    <td>Pressure Drop</td>
                                    <td>EN 13941-1 (≤0.3 bar/100m)</td>
                                    <td>{{ '≤0.3' if contract.district_heating.hydraulics.dp_ok else '>0.3' }} bar/100m</td>
                                    <td>N/A</td>
                                    <td>{{ '✓ Pass' if contract.district_heating.hydraulics.dp_ok else '✗ Fail' }}</td>
                                </tr>
                                <tr class="{{ 'table-success' if (contract.heat_pumps.lv_grid.voltage_violations_total or 0) == 0 else 'table-danger' }}">
                                    <td>Voltage Band</td>
                                    <td>VDE-AR-N 4100 (0.95-1.05 pu)</td>
                                    <td>N/A</td>
                                    <td><span class="source-hint" data-source="heat_pumps.lv_grid.voltage_violations_total">{{ contract.heat_pumps.lv_grid.voltage_violations_total or 0 }}</span> violations</td>
                                    <td>{{ '✓ Pass' if (contract.heat_pumps.lv_grid.voltage_violations_total or 0) == 0 else '✗ Fail' }}</td>
                                </tr>
                                <tr class="{{ 'table-success' if (contract.heat_pumps.lv_grid.line_violations_total or 0) == 0 else 'table-danger' }}">
                                    <td>Line Loading</td>
                                    <td>VDE-AR-N 4100 (≤100% operation)</td>
                                    <td>{{ contract.heat_pumps.lv_grid.max_feeder_loading_pct|round(1) }}%</td>
                                    <td><span class="source-hint" data-source="heat_pumps.lv_grid.line_violations_total">{{ contract.heat_pumps.lv_grid.line_violations_total or 0 }}</span> violations</td>
                                    <td>{{ '✓ Pass' if (contract.heat_pumps.lv_grid.line_violations_total or 0) == 0 else '✗ Fail' }}</td>
                                </tr>
                                <tr class="{{ 'table-success' if contract.heat_pumps.lv_grid.max_feeder_loading_pct <= 80 else 'table-warning' }}">
                                    <td>Feeder Loading</td>
                                    <td>VDE-AR-N 4100 (≤80% planning)</td>
                                    <td>N/A</td>
                                    <td><span class="source-hint" data-source="heat_pumps.lv_grid.max_feeder_loading_pct">{{ contract.heat_pumps.lv_grid.max_feeder_loading_pct|round(0) }}%</span></td>
                                    <td>{{ '✓ Pass' if contract.heat_pumps.lv_grid.max_feeder_loading_pct <= 80 else '⚠ Warning' }}</td>
                                </tr>
                            </tbody>
                        </table>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // DataTables: sortable + filterable technical details table (compact: no paging).
            $(document).ready(function() {
                if ($.fn && $.fn.DataTable) {
                    $('#tech-details-table').DataTable({
                        paging: false,
                        searching: true,
                        info: false,
                        order: []
                    });
                }
            });
        </script>

        <script>
            // Export helpers: full report JSON + quick metrics CSV.
            // JSON is embedded as base64 to avoid relying on Jinja tojson support.
            function downloadJSON() {
                try {
                    const b64 = "{{ report_json_b64 }}";
                    const bytes = Uint8Array.from(atob(b64), c => c.charCodeAt(0));
                    const jsonText = new TextDecoder('utf-8').decode(bytes);
                    const blob = new Blob([jsonText], {type: 'application/json'});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = 'uhdc_report_{{ cluster_id }}.json';
                    a.click();
                    URL.revokeObjectURL(url);
                } catch (e) {
                    console.error("downloadJSON failed", e);
                }
            }

            function downloadCSV() {
                const dhLcoh = {{ contract.district_heating.lcoh.median if contract.district_heating.lcoh.median is not none else 'null' }};
                const hpLcoh = {{ contract.heat_pumps.lcoh.median if contract.heat_pumps.lcoh.median is not none else 'null' }};
                const dhCo2 = {{ contract.district_heating.co2.median if contract.district_heating.co2.median is not none else 'null' }};
                const hpCo2 = {{ contract.heat_pumps.co2.median if contract.heat_pumps.co2.median is not none else 'null' }};
                const lines = [];
                lines.push("Metric,DH,HP");
                lines.push("LCOH_median," + (dhLcoh ?? "") + "," + (hpLcoh ?? ""));
                lines.push("CO2_median," + (dhCo2 ?? "") + "," + (hpCo2 ?? ""));
                const csv = lines.join("\\n") + "\\n";
                const blob = new Blob([csv], {type: 'text/csv'});
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = 'uhdc_metrics_{{ cluster_id }}.csv';
                a.click();
                URL.revokeObjectURL(url);
            }
        </script>

        <!-- Interactive Maps Section -->
        <div class="row mb-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Interactive Network Maps</h5>
                    </div>
                    <div class="card-body">
                        {% if map_specs and map_specs|length > 0 %}
                            <ul class="nav nav-tabs mb-3" id="mapTabs" role="tablist">
                                {% for m in map_specs %}
                                <li class="nav-item" role="presentation">
                                    <button class="nav-link {% if loop.first %}active{% endif %}" id="{{ m.key }}-tab"
                                            data-bs-toggle="tab" data-bs-target="#{{ m.key }}" type="button" role="tab">
                                        {% if m.icon %}
                                            <i class="bi {{ m.icon }} me-2"></i>
                                        {% endif %}
                                        {{ m.label }}
                                    </button>
                                </li>
                                {% endfor %}
                            </ul>

                            <div class="tab-content" id="mapTabsContent">
                                {% for m in map_specs %}
                                <div class="tab-pane fade {% if loop.first %}show active{% endif %}" id="{{ m.key }}" role="tabpanel">
                                    <div class="map-container">
                                        <iframe src="{{ m.src }}" class="map-iframe" id="{{ m.key }}-frame"
                                                onload="this.style.opacity=1; hideSpinner('{{ m.key }}');"
                                                onerror="handleMapError('{{ m.key }}')"></iframe>
                                        <div class="map-loading-spinner" id="{{ m.key }}-spinner">
                                            <div class="spinner-border {{ m.spinner_class or 'text-primary' }}" role="status">
                                                <span class="visually-hidden">Loading map...</span>
                                            </div>
                                        </div>
                                    </div>
                                </div>
                                {% endfor %}
                            </div>
                        {% else %}
                            <div class="text-center py-5 text-muted">
                                <div style="font-size: 4rem;">🗺️</div>
                                <p class="mt-3 mb-0">Interactive maps not available.</p>
                                <small>Run CHA/DHA pipelines with <code>--interactive-map</code> to generate maps.</small>
                            </div>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>

        <script>
            function hideSpinner(key) {
                const sp = document.getElementById(key + '-spinner');
                if (sp) sp.style.display = 'none';
            }
            function handleMapError(key) {
                const iframe = document.getElementById(key + '-frame');
                if (!iframe) return;
                const container = iframe.parentElement;
                if (!container) return;
                container.innerHTML = `
                    <div class="text-center py-5 text-danger">
                        <div style="font-size: 3rem;">⚠️</div>
                        <p class="mt-2 mb-0">Failed to load map.</p>
                        <small>Check file path: ${iframe.src}</small>
                    </div>
                `;
            }
        </script>

        <!-- DHA Violations Table (if available) -->
        {% if violations_table %}
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header d-flex justify-content-between align-items-center">
                        <h5 class="mb-0">DHA Violations Detail</h5>
                        <small class="text-muted">{{ violations_table|length }} violations total</small>
                    </div>
                    <div class="card-body">
                        <p class="text-muted small mb-3">
                            Voltage violations: {{ contract.heat_pumps.lv_grid.voltage_violations_total or 0 }} | 
                            Line violations: {{ contract.heat_pumps.lv_grid.line_violations_total or 0 }}
                        </p>
                        <div class="table-responsive" style="max-height: 400px; overflow-y: auto;">
                            <table id="violations-table" class="table table-sm table-hover table-striped">
                                <thead class="table-light sticky-top">
                                    <tr>
                                        <th>Hour</th>
                                        <th>Type</th>
                                        <th>Element</th>
                                        <th>Value</th>
                                        <th>Limit</th>
                                        <th>Severity</th>
                                    </tr>
                                </thead>
                                <tbody>
                                {% for v in violations_table[:100] %}
                                    <tr class="{{ 'table-danger' if v.severity == 'error' else 'table-warning' if v.severity == 'warning' else '' }}">
                                        <td>{{ v.hour }}</td>
                                        <td><code>{{ v.type }}</code></td>
                                        <td>{{ v.element }}</td>
                                        <td><strong>{{ v.value }}</strong></td>
                                        <td>{{ v.limit }}</td>
                                        <td>
                                            {% if v.severity == 'error' %}
                                                <span class="badge bg-danger">Error</span>
                                            {% elif v.severity == 'warning' %}
                                                <span class="badge bg-warning text-dark">Warning</span>
                                            {% else %}
                                                <span class="badge bg-secondary">{{ v.severity }}</span>
                                            {% endif %}
                                        </td>
                                    </tr>
                                {% endfor %}
                                </tbody>
                            </table>
                        </div>
                        {% if violations_table|length > 100 %}
                            <p class="text-muted small mt-2">
                                Showing first 100 violations. See violations.csv for complete list.
                            </p>
                        {% endif %}
                    </div>
                </div>
            </div>
        </div>
        {% endif %}

        <!-- Reason Codes -->
        <div class="row">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Decision Reason Codes</h5>
                    </div>
                    <div class="card-body">
                        <ol>
                        {% for code in decision.reason_codes %}
                            <li><strong>{{ code }}</strong>: {{ reason_descriptions.get(code, "Unknown reason code") }}</li>
                        {% endfor %}
                        </ol>
                    </div>
                </div>
            </div>
        </div>

        <!-- Standards Footer -->
        <div class="row mt-4">
            <div class="col-12">
                <div class="card">
                    <div class="card-header">
                        <h5 class="mb-0">Standards Referenced</h5>
                    </div>
                    <div class="card-body">
                        <ul class="mb-0">
                        {% for s in standards_refs %}
                            <li>
                                <a href="{{ s.url }}" target="_blank" rel="noopener noreferrer">{{ s.name }}</a>
                                <span class="text-muted">— {{ s.description }}</span>
                            </li>
                        {% endfor %}
                        </ul>
                    </div>
                </div>
            </div>
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/@popperjs/core@2.11.6/dist/umd/popper.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.min.js"></script>
</body>
</html>
"""

def render_html_report(
    report_data: Dict[str, Any],
    map_path: Optional[Path] = None,
    map_paths: Optional[Mapping[str, Path]] = None,
    map_specs: Optional[List[Dict[str, Any]]] = None,
    reason_descriptions: Optional[Dict[str, str]] = None,
    violations_csv_path: Optional[Path] = None,
) -> str:
    """
    Render complete HTML report.
    
    Args:
        report_data: Dictionary from build_uhdc_report()
        map_path: Optional path to interactive map HTML
        reason_descriptions: Mapping of reason codes to descriptions
    
    Returns:
        HTML string
    """
    
    if reason_descriptions is None:
        from ..decision.schemas import REASON_CODES
        reason_descriptions = REASON_CODES
    
    # Prepare template data
    en = STANDARDS_REFERENCES["EN_13941_1"]
    vde = STANDARDS_REFERENCES["VDE_AR_N_4100"]

    # Preferred: pass fully-resolved `map_specs` from save_reports/CLI
    resolved_map_specs: List[Dict[str, Any]] = map_specs or []

    # Load violations CSV if provided
    violations_table: List[Dict[str, Any]] = []
    if violations_csv_path and violations_csv_path.exists():
        try:
            import pandas as pd
            df = pd.read_csv(violations_csv_path)
            violations_table = df.to_dict('records')
            logger.debug(f"Loaded {len(violations_table)} violations from {violations_csv_path}")
        except Exception as e:
            logger.warning(f"Failed to load violations CSV {violations_csv_path}: {e}")

    template_data = {
        'cluster_id': report_data['cluster_id'],
        'contract': DictObject(report_data['contract']),
        'decision': DictObject(report_data['decision']),
        'explanation': report_data['explanation'],
        'metadata': DictObject(report_data['metadata']),
        'reason_descriptions': reason_descriptions,
        'map_path': str(map_path) if map_path else None,  # legacy-only; avoid breaking older custom templates
        'map_paths': None,  # no longer used by embedded template
        'map_specs': [DictObject(m) for m in resolved_map_specs],
        'violations_table': violations_table,
        'lcoh_chart_html': _render_lcoh_chart(report_data),
        'robustness_chart_html': _render_robustness_chart(report_data),
        'report_json_b64': base64.b64encode(
            json.dumps(report_data, ensure_ascii=False, default=str).encode("utf-8")
        ).decode("ascii"),
        # Repeat counts are intentional for Phase 5 checklist (EN×3, VDE×2)
        'standards_refs': [
            en,
            en,
            en,
            vde,
            vde,
        ],
    }
    
    # Render template
    try:
        # Try to load from file system templates
        template_dir = os.getenv("UHDC_TEMPLATE_DIR", "src/branitz_heat_decision/templates")
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template('uhdc_report.html')
    except TemplateNotFound:
        # Fallback to embedded template
        logger.warning("Template file not found, using embedded HTML template")
        env = Environment(loader=BaseLoader())
        template = env.from_string(HTML_TEMPLATE)
    
    return template.render(template_data)

def _render_lcoh_chart(report_data: Dict[str, Any]) -> str:
    """Render interactive LCOH comparison using Plotly.js (CDN, no Python plotly dependency)."""
    try:
        dh = report_data["contract"]["district_heating"]["lcoh"]
        hp = report_data["contract"]["heat_pumps"]["lcoh"]
        choice = str(report_data.get("decision", {}).get("choice", "")).upper()

        # Unique ID to avoid collisions if multiple charts exist on one page.
        cluster_id = str(report_data.get("cluster_id", "cluster")).replace(" ", "_")
        chart_id = f"lcoh-chart-{cluster_id}"

        # Per-bar outline to highlight the chosen option.
        line_width = [2, 2]
        if choice == "DH":
            line_width = [3, 0]
        elif choice == "HP":
            line_width = [0, 3]

        fig = {
            "data": [
                {
                    "x": ["District Heating", "Heat Pumps"],
                    "y": [dh["median"], hp["median"]],
                    "error_y": {
                        "type": "data",
                        "symmetric": False,
                        "array": [dh["p95"] - dh["median"], hp["p95"] - hp["median"]],
                        "arrayminus": [dh["median"] - dh["p05"], hp["median"] - hp["p05"]],
                    },
                    "type": "bar",
                    "marker": {
                        "color": ["#28a745", "#dc3545"],
                        "opacity": 0.8,
                        "line": {"color": ["black", "black"], "width": line_width},
                    },
                    "hovertemplate": (
                        "<b>%{x}</b><br>"
                        "LCOH: %{y:.1f} €/MWh<br>"
                        "95% CI: [%{customdata[0]:.1f}, %{customdata[1]:.1f}] €/MWh"
                        "<extra></extra>"
                    ),
                    "customdata": [
                        [dh["p05"], dh["p95"]],
                        [hp["p05"], hp["p95"]],
                    ],
                }
            ],
            "layout": {
                "title": {"text": "Levelized Cost of Heat (95% CI)", "x": 0.5},
                "yaxis": {"title": "LCOH (€/MWh)"},
                "showlegend": False,
                "margin": {"l": 60, "r": 20, "t": 60, "b": 60},
                "height": 400,
            },
        }

        return (
            f'<div id="{chart_id}" style="width:100%;height:400px;"></div>'
            "<script>"
            f"Plotly.newPlot('{chart_id}', {json.dumps(fig['data'])}, {json.dumps(fig['layout'])}, {{responsive: true}});"
            "</script>"
        )
    except Exception as e:
        logger.warning(f"Failed to render LCOH chart: {e}")
        return "<p class='text-muted'>LCOH chart unavailable</p>"

def _render_robustness_chart(report_data: Dict[str, Any]) -> str:
    """Render Monte Carlo win fractions as animated Bootstrap progress bars."""
    try:
        mc = report_data.get("contract", {}).get("monte_carlo", {}) or {}
        if not mc or mc.get("dh_wins_fraction") is None:
            return "<p class='text-muted'>Monte Carlo data not available</p>"
    
        dh_frac = float(mc.get("dh_wins_fraction", 0.0) or 0.0)
        hp_frac = mc.get("hp_wins_fraction")
        if hp_frac is None:
            hp_frac = 1.0 - dh_frac
        hp_frac = float(hp_frac or 0.0)

        # Clamp for safety.
        dh_pct = max(0.0, min(100.0, dh_frac * 100.0))
        hp_pct = max(0.0, min(100.0, hp_frac * 100.0))
        n_samples = mc.get("n_samples")

        return f"""
        <style>
            .mc-progress .progress-bar {{
                transition: width 1.0s ease;
            }}
        </style>

        <div class="mc-progress">
            <div class="d-flex align-items-center mb-3">
                <div class="flex-grow-1 me-3">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span><strong>District Heating</strong></span>
                        <span>{dh_pct:.0f}%</span>
                    </div>
                    <div class="progress" style="height: 24px;">
                        <div class="progress-bar bg-success" role="progressbar"
                             data-target-width="{dh_pct:.3f}%"
                             style="width: 0%;"
                             aria-valuenow="{dh_pct:.3f}"
                             aria-valuemin="0" aria-valuemax="100">
                        </div>
                    </div>
                </div>
            </div>

            <div class="d-flex align-items-center">
                <div class="flex-grow-1 me-3">
                    <div class="d-flex justify-content-between align-items-center mb-1">
                        <span><strong>Heat Pumps</strong></span>
                        <span>{hp_pct:.0f}%</span>
                    </div>
                    <div class="progress" style="height: 24px;">
                        <div class="progress-bar bg-danger" role="progressbar"
                             data-target-width="{hp_pct:.3f}%"
                             style="width: 0%;"
                             aria-valuenow="{hp_pct:.3f}"
                             aria-valuemin="0" aria-valuemax="100">
                        </div>
                    </div>
                </div>
            </div>

            <small class="text-muted">Monte Carlo samples: {n_samples if n_samples is not None else "N/A"}</small>
        </div>

        <script>
            (function () {{
                function animateMcBars() {{
                    document.querySelectorAll('.mc-progress .progress-bar[data-target-width]').forEach(function (el) {{
                        var w = el.getAttribute('data-target-width') || '0%';
                        setTimeout(function () {{ el.style.width = w; }}, 50);
                    }});
                }}
                if (document.readyState === 'loading') {{
                    document.addEventListener('DOMContentLoaded', animateMcBars);
                }} else {{
                    animateMcBars();
                }}
            }})();
        </script>
        """
    except Exception as e:
        logger.warning(f"Failed to render robustness chart: {e}")
        return "<p class='text-muted'>Robustness chart unavailable</p>"

class DictObject(dict):
    """Dictionary with dot notation access for templates."""
    def __getattr__(self, key: str) -> Any:
        try:
            value = self[key]
            if isinstance(value, dict):
                return DictObject(value)
            return value
        except KeyError:
            raise AttributeError(f"'Dict' object has no attribute '{key}'")

def render_markdown_report(report_data: Dict[str, Any]) -> str:
    """
    Render Markdown report (simpler than HTML).
    
    Args:
        report_data: Dictionary from build_uhdc_report()
    
    Returns:
        Markdown string
    """
    
    dh = report_data['contract']['district_heating']
    hp = report_data['contract']['heat_pumps']
    decision = report_data['decision']
    
    lines = [
        f"# UHDC Report: {report_data['cluster_id']}",
        f"**Generated:** {report_data['metadata'].get('timestamp', 'N/A')}",
        "",
        f"## Recommendation: **{decision['choice']}**",
        f"Robust: {'✓' if decision['robust'] else '✗'}",
        "",
        "## Executive Summary",
        "",
        f"{report_data['explanation']}",
        "",
        "## Key Metrics",
        "",
        "### District Heating",
        f"- LCOH: {dh['lcoh']['median']:.1f} €/MWh (95% CI: {dh['lcoh']['p05']:.1f}-{dh['lcoh']['p95']:.1f})",
        f"- CO₂: {dh['co2']['median']:.0f} kg/MWh",
        f"- Feasible: {'✓' if dh['feasible'] else '✗'}",
        f"- Max Velocity: {dh['hydraulics'].get('v_max_ms', 'N/A')} m/s",
        "",
        "### Heat Pumps",
        f"- LCOH: {hp['lcoh']['median']:.1f} €/MWh (95% CI: {hp['lcoh']['p05']:.1f}-{hp['lcoh']['p95']:.1f})",
        f"- CO₂: {hp['co2']['median']:.0f} kg/MWh",
        f"- Feasible: {'✓' if hp['feasible'] else '✗'}",
        f"- Max Loading: {hp['lv_grid'].get('max_feeder_loading_pct', 'N/A')}%",
        "",
        "## Decision Rationale",
        "",
    ]
    
    for code in decision['reason_codes']:
        from ..decision.schemas import REASON_CODES
        desc = REASON_CODES.get(code, "Unknown")
        lines.append(f"- **{code}**: {desc}")
    
    lines.extend([
        "",
        "## Data Sources",
        "",
    ])
    
    for source_type, path in report_data['sources'].items():
        lines.append(f"- **{source_type}**: `{path or 'N/A'}`")

    # Standards references footer (Phase 5 checklist: EN×3, VDE×2)
    en = STANDARDS_REFERENCES["EN_13941_1"]
    vde = STANDARDS_REFERENCES["VDE_AR_N_4100"]
    lines.extend(
        [
            "",
            "---",
            "**Standards Referenced:**",
            f"- [{en['name']}]({en['url']})",
            f"- [{en['name']}]({en['url']})",
            f"- [{en['name']}]({en['url']})",
            f"- [{vde['name']}]({vde['url']})",
            f"- [{vde['name']}]({vde['url']})",
        ]
    )
    
    return "\n".join(lines)

def save_reports(
    report_data: Dict[str, Any],
    out_dir: Path,
    include_html: bool = True,
    include_markdown: bool = True,
    include_json: bool = True,
    map_path: Optional[Path] = None,
    map_paths: Optional[Mapping[str, Path]] = None,
    map_specs: Optional[List[Dict[str, Any]]] = None,
    violations_csv_path: Optional[Path] = None,
) -> None:
    """
    Save all report formats to disk.
    
    Args:
        report_data: Dictionary from build_uhdc_report()
        out_dir: Output directory
        include_html: Generate HTML report
        include_markdown: Generate Markdown
        include_json: Generate JSON report
        map_path: Path to interactive map file
    """
    
    out_dir.mkdir(parents=True, exist_ok=True)
    
    # JSON report (complete data)
    if include_json:
        json_path = out_dir / f'uhdc_report_{report_data["cluster_id"]}.json'
        with open(json_path, 'w') as f:
            json.dump(report_data, f, indent=2)
        logger.info(f"Saved JSON: {json_path}")
    
    # Markdown report
    if include_markdown:
        md_path = out_dir / f'uhdc_explanation_{report_data["cluster_id"]}.md'
        md = render_markdown_report(report_data)
        md_path.write_text(md)
        logger.info(f"Saved Markdown: {md_path}")
    
    # HTML report
    if include_html:
        effective_specs: List[Dict[str, Any]] = []
        if map_specs:
            # Bundle maps into the report folder to avoid browser restrictions with file:// iframes
            # (Chrome often blocks local iframes pointing outside the current directory tree).
            bundle_dir = out_dir / "_maps"
            bundle_dir.mkdir(parents=True, exist_ok=True)
            for spec in map_specs:
                spec = dict(spec)
                src: Optional[str] = None

                path_val = spec.get("path")
                if path_val:
                    try:
                        p = Path(str(path_val))
                        if p.exists() and p.is_file():
                            dest = bundle_dir / f"{spec.get('key', 'map')}.html"
                            shutil.copyfile(p, dest)
                            src = os.path.relpath(str(dest), start=str(out_dir))
                    except Exception:
                        src = None

                if not src:
                    # Fallback: keep provided src if any
                    src_val = spec.get("src")
                    if src_val:
                        src = str(src_val)

                if not src:
                    continue

                spec["src"] = src
                spec.pop("path", None)
                effective_specs.append(spec)
        elif map_paths:
            # Backward compatible conversion: map_paths -> specs with relative paths
            for key, p in map_paths.items():
                try:
                    src = os.path.relpath(str(p), start=str(out_dir))
                except Exception:
                    src = str(p)
                label = "District Heating Network" if key == "dh" else "Heat Pump Layout" if key == "hp" else key
                icon = "bi-thermometer-sun" if key == "dh" else "bi-lightning-charge" if key == "hp" else "bi-map"
                spinner_class = "text-primary" if key == "dh" else "text-danger" if key == "hp" else "text-primary"
                effective_specs.append(
                    {"key": f"map-{key}", "label": label, "src": src, "icon": icon, "spinner_class": spinner_class}
                )
        elif map_path:
            try:
                src = os.path.relpath(str(map_path), start=str(out_dir))
            except Exception:
                src = str(map_path)
            effective_specs = [{"key": "map", "label": "Interactive Map", "src": src, "icon": "bi-map", "spinner_class": "text-primary"}]

        html_path = out_dir / f'uhdc_report_{report_data["cluster_id"]}.html'
        html = render_html_report(report_data, map_path=map_path, map_paths=map_paths, map_specs=effective_specs, violations_csv_path=violations_csv_path)
        html_path.write_text(html)
        logger.info(f"Saved HTML: {html_path}")