# Deployment

This project supports a minimal deployment configuration driven by environment variables and named JSON config files.

## Environment Variables

### `UHDC_LOG_LEVEL`
- **Purpose**: Controls logging verbosity for the UHDC/decision CLIs.
- **Default**: `INFO`
- **Examples**:

```bash
export UHDC_LOG_LEVEL=DEBUG
PYTHONPATH=src python -m branitz_heat_decision.cli.decision --cluster-id ST010_HEINRICH_ZILLE_STRASSE --format json
```

### `UHDC_TEMPLATE_DIR`
- **Purpose**: Override the directory used to load the Jinja HTML template `uhdc_report.html`.
  - If the template is not found, the system falls back to the embedded HTML template.
- **Default**: `src/branitz_heat_decision/templates`
- **Examples**:

```bash
export UHDC_TEMPLATE_DIR=/opt/branitz/templates
PYTHONPATH=src python -m branitz_heat_decision.cli.uhdc --cluster-id ST010_HEINRICH_ZILLE_STRASSE --out-dir results/decision/ST010/report --format html
```

---

## Named Decision Config Files

The decision thresholds can be supplied via `--config <path>` on the decision CLI.

Included configs:
- `config/decision_config_2023.json`
- `config/decision_config_2030.json`

### Example usage

```bash
PYTHONPATH=src python -m branitz_heat_decision.cli.decision \
  --cluster-id ST010_HEINRICH_ZILLE_STRASSE \
  --config config/decision_config_2023.json \
  --format all
```

