import geopandas as gpd
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Union, Dict, Any, List, Optional
import json
import logging

logger = logging.getLogger(__name__)

class DataValidationError(Exception):
    """Custom exception for data validation failures."""
    pass

def filter_residential_buildings_with_heat_demand(
    buildings: gpd.GeoDataFrame,
    min_heat_demand_kwh_a: float = 0.0
) -> gpd.GeoDataFrame:
    """
    Filter buildings to only include residential buildings with heat demand.
    
    Args:
        buildings: GeoDataFrame with building data
        min_heat_demand_kwh_a: Minimum annual heat demand in kWh/a (default: 0.0)
        
    Returns:
        Filtered GeoDataFrame containing only residential buildings with heat demand
        
    Filters by:
    - use_type: Must be 'residential_sfh' or 'residential_mfh' (or contains 'residential')
    - annual_heat_demand_kwh_a: Must be > min_heat_demand_kwh_a
    """
    logger.info(f"Filtering buildings: Starting with {len(buildings)} buildings")
    
    # Work on copy
    filtered = buildings.copy()
    
    # Filter 1: Residential buildings only
    #
    # Legacy-aligned behavior: if we cannot reliably determine residential-ness,
    # we must NOT silently drop everything. We warn and skip this filter.
    residential_filter_applied = False
    if 'use_type' in filtered.columns:
        use_series = filtered['use_type'].astype(str)
        # If everything is unknown-ish, skip filtering (data is incomplete)
        unknownish = use_series.str.lower().isin(['unknown', 'nan', 'none', ''])
        if unknownish.mean() > 0.95:
            logger.warning(
                "use_type column exists but is mostly 'unknown'. "
                "Skipping residential filter (will rely on other sources/steps)."
            )
        else:
            residential_mask = (
                use_series.str.contains('residential', case=False, na=False) |
                use_series.str.contains('wohn', case=False, na=False) |
                use_series.isin(['residential_sfh', 'residential_mfh'])
            )
            if residential_mask.sum() == 0:
                logger.warning(
                    "use_type present but no rows matched residential patterns. "
                    "Skipping residential filter to avoid dropping all buildings."
                )
            else:
                filtered = filtered[residential_mask].copy()
                residential_filter_applied = True
                logger.info(f"After residential filter (use_type): {len(filtered)} buildings")
    elif 'building_function' in filtered.columns:
        func_series = filtered['building_function'].astype(str)
        residential_mask = (
            func_series.str.contains('wohn', case=False, na=False) |
            func_series.str.contains('residential', case=False, na=False) |
            func_series.str.contains('mfh', case=False, na=False) |
            func_series.str.contains('mehrfam', case=False, na=False)
        )
        if residential_mask.sum() == 0:
            logger.warning(
                "building_function present but no rows matched residential patterns. "
                "Skipping residential filter to avoid dropping all buildings."
            )
        else:
            filtered = filtered[residential_mask].copy()
            residential_filter_applied = True
            logger.info(f"After residential filter (building_function): {len(filtered)} buildings")
    else:
        logger.warning("No use_type or building_function column found. Skipping residential filter.")
    
    # Filter 2: Buildings with heat demand
    if 'annual_heat_demand_kwh_a' in filtered.columns:
        before_count = len(filtered)
        filtered = filtered[filtered['annual_heat_demand_kwh_a'] > min_heat_demand_kwh_a]
        after_count = len(filtered)
        logger.info(f"After heat demand filter (>{min_heat_demand_kwh_a} kWh/a): {after_count} buildings (removed {before_count - after_count})")
    else:
        logger.warning("No annual_heat_demand_kwh_a column found. Skipping heat-demand filter.")
    
    logger.info(f"Final filtered count: {len(filtered)} buildings after filtering")
    logger.info(f"Removed {len(buildings) - len(filtered)} buildings during filtering")
    
    return filtered


def load_branitzer_siedlung_attributes(path: Union[str, Path]) -> pd.DataFrame:
    """
    Load enriched building attributes from `output_branitzer_siedlungV11.json`.

    The file structure is:
      { "<GebaeudeID>": { "GebaeudeID": ..., "Gebaeudefunktion": ..., "Adressen": [...], ... }, ... }

    Returns a DataFrame with at least:
      - building_id (matches DEBBAL... ids used elsewhere)
      - building_function (German string like 'Wohnhaus', 'Garage', ...)
      - street_name (from Adressen[].strasse when present)
      - floor_area_m2 (Gesamtnettonutzflaeche)
      - volume_m3 (Gesamtvolumen)
      - footprint_m2 (Gesamtgrundflaeche)
      - wall_area_m2 (Gesamtwandflaeche)  # needed for TABULA/U-value heat loss model
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    rows: List[Dict[str, Any]] = []
    for building_id, rec in data.items():
        if not isinstance(rec, dict):
            continue
        addrs = rec.get("Adressen")
        street_name = None
        if isinstance(addrs, list) and len(addrs) > 0 and isinstance(addrs[0], dict):
            street_name = addrs[0].get("strasse") or addrs[0].get("str") or addrs[0].get("street")
        rows.append({
            "building_id": str(building_id),
            "building_function": rec.get("Gebaeudefunktion"),
            "building_code": rec.get("Gebaeudecode"),
            "FLURID": rec.get("FLURID"),
            "street_name": street_name,
            "floor_area_m2": rec.get("Gesamtnettonutzflaeche"),
            "footprint_m2": rec.get("Gesamtgrundflaeche"),
            "volume_m3": rec.get("Gesamtvolumen"),
            "wall_area_m2": rec.get("Gesamtwandflaeche"),
        })

    df = pd.DataFrame(rows)
    return df


def load_gebaeudeanalyse(path: Union[str, Path]) -> pd.DataFrame:
    """
    Load building renovation state and heat density from `gebaeudeanalyse.json`.

    Structure:
      { "gebaeude": [ {"gebaeude_id": "...", "sanierungszustand": "...", "waermedichte": ...}, ... ] }
    """
    path = Path(path)
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    recs = data.get("gebaeude") if isinstance(data, dict) else data
    if not isinstance(recs, list):
        raise ValueError("gebaeudeanalyse.json has unexpected structure (expected key 'gebaeude' -> list)")

    rows = []
    for rec in recs:
        if not isinstance(rec, dict):
            continue
        rows.append({
            "building_id": str(rec.get("gebaeude_id")),
            "sanierungszustand": rec.get("sanierungszustand"),
            "waermedichte": rec.get("waermedichte"),
        })
    return pd.DataFrame(rows)


def load_processed_buildings(
    cluster_buildings: Optional[List[str]] = None,
    force_reload: bool = False
) -> gpd.GeoDataFrame:
    """
    Load processed buildings, automatically filtering if needed.
    
    This is the preferred way to load buildings for the pipeline.
    It ensures buildings are filtered to residential with heat demand,
    and caches the result for faster subsequent loads.
    
    Args:
        cluster_buildings: Optional list of building IDs to filter to a specific cluster
        force_reload: If True, reload from raw even if processed file exists
    
    Returns:
        GeoDataFrame of filtered buildings (residential with heat demand)
        If cluster_buildings provided, only returns buildings in that cluster
    
    Behavior:
        - Checks if processed/buildings.parquet exists and is already filtered
        - If yes: loads and returns (fast path)
        - If no: loads raw data, filters, saves processed version, returns
        - If force_reload=True: always loads raw and filters
    """
    from branitz_heat_decision.config import BUILDINGS_PATH, DATA_RAW
    
    # NOTE:
    # GeoPandas `.attrs` are NOT reliably preserved through parquet round-trips.
    # We therefore detect "already filtered" primarily by required columns + an optional sidecar metadata file.
    meta_path = BUILDINGS_PATH.with_suffix(".meta.json")

    def _looks_like_filtered(df: gpd.GeoDataFrame) -> bool:
        required = {"use_type", "annual_heat_demand_kwh_a"}
        return required.issubset(set(df.columns)) and (len(df) > 0)

    # Check if processed file exists and is up-to-date
    if not force_reload and BUILDINGS_PATH.exists():
        try:
            buildings = gpd.read_parquet(BUILDINGS_PATH)
            
            # Check if already filtered (column-based; robust across parquet)
            if _looks_like_filtered(buildings):
                meta_info = {}
                if meta_path.exists():
                    try:
                        meta_info = json.loads(meta_path.read_text(encoding="utf-8"))
                    except Exception:
                        meta_info = {}
                logger.info(
                    f"Loaded {len(buildings)} pre-filtered buildings from {BUILDINGS_PATH} "
                    f"(meta date: {meta_info.get('filter_date', 'unknown')})"
                )
                # Filter to cluster if requested
                if cluster_buildings:
                    before = len(buildings)
                    buildings = buildings[buildings['building_id'].isin(cluster_buildings)].copy()
                    logger.info(f"Filtered to cluster: {before} -> {len(buildings)} buildings")
                return buildings
            else:
                logger.info("Processed file exists but not marked as filtered, will filter now...")
        except Exception as e:
            logger.warning(f"Error reading processed buildings file: {e}. Will reload from raw.")
    
    # Need to filter: load from raw
    raw_path = DATA_RAW / "hausumringe_mit_adressenV3.geojson"
    if not raw_path.exists():
        # Try alternative names
        alternative_paths = [
            DATA_RAW / "buildings.geojson",
            DATA_RAW / "gebaeude.geojson",
        ]
        for alt_path in alternative_paths:
            if alt_path.exists():
                raw_path = alt_path
                break
        else:
            raise FileNotFoundError(
                f"Raw buildings file not found. Tried: {raw_path} and alternatives. "
                f"Please ensure raw buildings data is in {DATA_RAW}"
            )
    
    logger.info(f"Loading and filtering buildings from {raw_path}")
    buildings = load_buildings_geojson(raw_path)
    buildings = filter_residential_buildings_with_heat_demand(buildings)
    
    # Write metadata sidecar (more reliable than GeoPandas attrs through parquet)
    try:
        meta_path.write_text(
            json.dumps(
                {
                    "filtered": True,
                    "filter_criteria": "residential_with_heat_demand_min_0_kwh_a",
                    "filter_date": pd.Timestamp.now().isoformat(),
                    "source_file": str(raw_path),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    except Exception:
        pass
    
    # Save processed version for future use
    BUILDINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    buildings.to_parquet(BUILDINGS_PATH, index=False)
    logger.info(f"Saved {len(buildings)} filtered buildings to {BUILDINGS_PATH}")
    
    # Filter to cluster if requested
    if cluster_buildings:
        before = len(buildings)
        buildings = buildings[buildings['building_id'].isin(cluster_buildings)].copy()
        logger.info(f"Filtered to cluster: {before} -> {len(buildings)} buildings")
    
    return buildings


def load_buildings_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame:
    """
    Load buildings from GeoJSON with comprehensive validation.
    
    Args:
        path: Path to buildings.geojson
        
    Returns:
        GeoDataFrame with validated and standardized columns
        
    Raises:
        DataValidationError: If validation fails
        FileNotFoundError: If file doesn't exist
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Buildings file not found: {path}")
    
    logger.info(f"Loading buildings from {path}")
    gdf = gpd.read_file(path)
    
    # --- VALIDATION RULES ---
    
    # 1. Must have building_id column
    #
    # IMPORTANT:
    # The raw dataset commonly contains a `gebaeude` column which is a list/dict-like
    # structure (not a scalar ID). Renaming `gebaeude` -> `building_id` directly
    # creates unstable/non-scalar IDs like "{'oi': ...}" and breaks:
    # - hourly profile alignment (columns are building_id)
    # - cluster mapping joins
    # - reproducibility across runs
    #
    # We therefore extract a stable scalar id from `gebaeude` if present.
    def _extract_building_id_from_gebaeude(val: Any) -> Optional[str]:
        """Extract stable building_id from legacy-like `gebaeude` structures."""
        if val is None or (isinstance(val, float) and np.isnan(val)):
            return None
        try:
            # Some datasets store `gebaeude` as a JSON string like:
            # '{ "oi": "DEBBAL...", "ags": "...", ... }'
            if isinstance(val, str):
                s = val.strip()
                if (s.startswith("{") and s.endswith("}")) or (s.startswith("[") and s.endswith("]")):
                    try:
                        parsed = json.loads(s)
                        return _extract_building_id_from_gebaeude(parsed)
                    except Exception:
                        # fall through to treat as scalar string
                        pass
            # list of dicts
            if isinstance(val, list) and len(val) > 0:
                first = val[0]
                if isinstance(first, dict):
                    # Prefer explicit IDs if present
                    for key in ("gebaeude_id", "building_id", "id", "oi", "objectid"):
                        if key in first and first[key] is not None:
                            return str(first[key])
                    # Fallback: stringify the first dict deterministically
                    return json.dumps(first, sort_keys=True, ensure_ascii=False)
                return str(first)
            # dict
            if isinstance(val, dict):
                for key in ("gebaeude_id", "building_id", "id", "oi", "objectid"):
                    if key in val and val[key] is not None:
                        return str(val[key])
                return json.dumps(val, sort_keys=True, ensure_ascii=False)
            # scalar
            return str(val)
        except Exception:
            return None

    if 'building_id' not in gdf.columns:
        # Try to infer from other common scalar ID column names (exclude 'gebaeude' here!)
        id_candidates = ['id', 'gid', 'objectid', 'building_id']
        found = False
        for candidate in id_candidates:
            if candidate in gdf.columns:
                gdf = gdf.rename(columns={candidate: 'building_id'})
                found = True
                logger.info(f"Renamed '{candidate}' to 'building_id'")
                break

        if not found and 'gebaeude' in gdf.columns:
            # Extract stable building_id from gebaeude structure
            gdf['building_id'] = gdf['gebaeude'].apply(_extract_building_id_from_gebaeude)
            missing = gdf['building_id'].isna().sum()
            if missing > 0:
                logger.warning(
                    f"Extracted building_id from 'gebaeude' for {len(gdf) - missing}/{len(gdf)} buildings. "
                    f"{missing} missing; will fill with synthetic IDs."
                )
                # Fill missing with synthetic IDs
                gdf.loc[gdf['building_id'].isna(), 'building_id'] = (
                    gdf.index[gdf['building_id'].isna()]
                    .astype(str)
                    .map(lambda x: f"B{x.zfill(6)}")
                )
            logger.info("Created 'building_id' from 'gebaeude' structure")
            found = True

        if not found:
            # Generate building IDs from index
            logger.warning(
                f"No building ID column found. Tried: {id_candidates} (+ 'gebaeude' extraction if present). "
                f"Available columns: {list(gdf.columns)}. Generating IDs from index."
            )
            gdf['building_id'] = gdf.index.astype(str).map(lambda x: f"B{x.zfill(6)}")
            logger.info(f"Generated {len(gdf)} building IDs from index (e.g., {gdf['building_id'].iloc[0]})")
    
    # 2. building_id must be unique
    if gdf['building_id'].duplicated().any():
        dups = gdf['building_id'][gdf['building_id'].duplicated()].unique()
        raise DataValidationError(
            f"Duplicate building_id found: {dups[:5]}"
        )
    
    # 3. Must have geometry column
    if gdf.geometry is None:
        raise DataValidationError("No geometry column found")
    
    # 4. Geometry must be Polygon or MultiPolygon (not points)
    invalid_geom_types = gdf.geometry.type[~gdf.geometry.type.isin(['Polygon', 'MultiPolygon'])]
    if not invalid_geom_types.empty:
        raise DataValidationError(
            f"Invalid geometry types found: {invalid_geom_types.unique()}. "
            "Expected only Polygon or MultiPolygon for building footprints."
        )
    
    # 5. CRS must be projected (not geographic)
    if gdf.crs is None:
        logger.warning("No CRS defined. Assuming EPSG:25833 (UTM Zone 33N)")
        gdf.set_crs("EPSG:25833", inplace=True)
    elif gdf.crs.is_geographic:
        logger.warning(
            f"Geographic CRS detected ({gdf.crs}). Converting to EPSG:25833 (UTM Zone 33N) "
            "for distance calculations."
        )
        gdf = gdf.to_crs("EPSG:25833")
    
    # 6. Standardize column names
    column_mapping = {
        'floor_area': 'floor_area_m2',
        'area': 'floor_area_m2',
        'heated_area': 'floor_area_m2',
        'year_built': 'year_of_construction',
        'baujahr': 'year_of_construction',
        'construction_year': 'year_of_construction',
        'heat_demand': 'annual_heat_demand_kwh_a',
        'wärmebedarf': 'annual_heat_demand_kwh_a',
    }
    
    gdf = gdf.rename(columns={k: v for k, v in column_mapping.items() if k in gdf.columns})
    
    # 7. Ensure required numeric columns exist and are valid
    required_numerics = ['floor_area_m2', 'year_of_construction', 'annual_heat_demand_kwh_a']
    for col in required_numerics:
        if col in gdf.columns:
            # Check for NaN/inf
            if gdf[col].isna().any() or np.isinf(gdf[col]).any():
                raise DataValidationError(f"Invalid values (NaN/inf) in {col}")
            
            # Check for negative values
            if (gdf[col] < 0).any():
                raise DataValidationError(f"Negative values found in {col}")
    
    # 8. Add metadata
    gdf.attrs['source_file'] = str(path)
    gdf.attrs['validated_at'] = pd.Timestamp.now().isoformat()
    gdf.attrs['validation_rules'] = 'phase1_buildings_v1'
    
    logger.info(f"Successfully loaded {len(gdf)} buildings")
    return gdf


def load_streets_geojson(path: Union[str, Path]) -> gpd.GeoDataFrame:
    """
    Load streets from GeoJSON with validation.
    
    Args:
        path: Path to streets.geojson
        
    Returns:
        GeoDataFrame with validated LineString geometries
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Streets file not found: {path}")
    
    logger.info(f"Loading streets from {path}")
    # The streets GeoJSON contains fields (notably `name`) that can be lists.
    # Some GDAL/pyogrio readers drop such columns entirely ("unsupported OGR type: 5"),
    # which causes us to lose real street names and create synthetic clusters (STREET_0, ...).
    #
    # To be robust and match the Legacy behavior, we parse GeoJSON manually, normalize
    # name fields, and explode list-names into multiple features.
    if str(path).lower().endswith(".geojson"):
        try:
            import json as _json
            with open(path, "r", encoding="utf-8") as f:
                data = _json.load(f)

            features = data.get("features", [])
            cleaned_features = []
            for ft in features:
                props = ft.get("properties") or {}
                name_val = props.get("name")

                # If name is a list, explode into multiple features
                if isinstance(name_val, list) and len(name_val) > 0:
                    for n in name_val:
                        ft2 = dict(ft)
                        props2 = dict(props)
                        props2["name"] = n
                        ft2["properties"] = props2
                        cleaned_features.append(ft2)
                else:
                    cleaned_features.append(ft)

            # Build GeoDataFrame
            gdf = gpd.GeoDataFrame.from_features(cleaned_features)

            # Set CRS from GeoJSON if available
            crs = (data.get("crs") or {}).get("properties", {}).get("name")
            if crs:
                try:
                    gdf.set_crs(crs, inplace=True, allow_override=True)
                except Exception:
                    pass
        except Exception as e:
            logger.warning(f"Manual GeoJSON parsing failed ({e}); falling back to geopandas.read_file")
            gdf = gpd.read_file(path)
    else:
        gdf = gpd.read_file(path)
    
    # --- VALIDATION RULES ---
    
    # 1. Standardize column names
    # Ensure street_name is a scalar string column
    if 'name' in gdf.columns and 'street_name' not in gdf.columns:
        gdf = gdf.rename(columns={'name': 'street_name'})

    if 'street_name' in gdf.columns:
        # Coerce list/dict values to strings (should be rare after manual parsing)
        def _coerce_street_name(v: Any) -> str:
            if v is None:
                return ""
            if isinstance(v, list):
                # prefer first non-empty string
                for item in v:
                    if item:
                        return str(item)
                return ""
            if isinstance(v, dict):
                return json.dumps(v, sort_keys=True, ensure_ascii=False)
            return str(v)
        gdf['street_name'] = gdf['street_name'].apply(_coerce_street_name)
    
    if 'id' in gdf.columns:
        gdf = gdf.rename(columns={'id': 'street_id'})
    
    # 2. Must have either street_name or street_id
    # If neither exists, create synthetic street_id
    if not ('street_name' in gdf.columns or 'street_id' in gdf.columns):
        # Check for other common column names
        if 'strasse' in gdf.columns:
            gdf = gdf.rename(columns={'strasse': 'street_name'})
        elif 'street' in gdf.columns:
            gdf = gdf.rename(columns={'street': 'street_name'})
        else:
            # Create synthetic street_id if no identifier found
            gdf['street_id'] = [f"street_{i:06d}" for i in range(len(gdf))]
            logger.warning("No street identifier column found. Generated synthetic street_id.")
    
    # 3. All geometries must be LineString (not Polygon, not Point)
    if not gdf.geometry.type.isin(['LineString', 'MultiLineString']).all():
        invalid = gdf.geometry.type[~gdf.geometry.type.isin(['LineString', 'MultiLineString'])].unique()
        raise DataValidationError(
            f"Invalid street geometry types: {invalid}. Expected LineString or MultiLineString."
        )
    
    # 4. Explode MultiLineString to LineString
    if (gdf.geometry.type == 'MultiLineString').any():
        logger.info("Exploding MultiLineString geometries to LineString")
        gdf = gdf.explode(index_parts=True).reset_index(drop=True)
    
    # 5. CRS must be projected and match buildings
    # Some GeoJSONs omit CRS. Use a simple heuristic to infer CRS from coordinate magnitudes.
    if gdf.crs is None:
        try:
            # get one coordinate from first geometry
            geom0 = gdf.geometry.iloc[0]
            x0, y0 = float(geom0.coords[0][0]), float(geom0.coords[0][1])
            # Heuristic: UTM 33N coordinates for Germany ~ (200k..800k, 5e6..7e6)
            if 200_000 <= abs(x0) <= 900_000 and 5_000_000 <= abs(y0) <= 7_500_000:
                gdf.set_crs("EPSG:25833", inplace=True)
                logger.warning("No CRS defined for streets. Inferred EPSG:25833 from coordinate magnitudes.")
            else:
                gdf.set_crs("EPSG:4326", inplace=True)
                logger.warning("No CRS defined for streets. Inferred EPSG:4326 from coordinate magnitudes.")
        except Exception:
            gdf.set_crs("EPSG:4326", inplace=True)
            logger.warning("No CRS defined for streets. Defaulting to EPSG:4326.")
    
    if gdf.crs.is_geographic:
        raise DataValidationError(f"Geographic CRS detected for streets: {gdf.crs}")
    
    # 6. Compute and validate length
    gdf['length_m'] = gdf.geometry.length
    if (gdf['length_m'] <= 0).any():
        raise DataValidationError("Streets with zero or negative length found")
    
    # 7. Add unique street_id if missing
    if 'street_id' not in gdf.columns:
        gdf['street_id'] = [f"street_{i:06d}" for i in range(len(gdf))]
        logger.warning("Generated synthetic street_id")
    
    # 8. Add metadata
    gdf.attrs['source_file'] = str(path)
    gdf.attrs['validated_at'] = pd.Timestamp.now().isoformat()
    gdf.attrs['validation_rules'] = 'phase1_streets_v1'
    
    logger.info(f"Successfully loaded {len(gdf)} street segments")
    return gdf


def load_power_grid(
    lines_path: Union[str, Path],
    substations_path: Union[str, Path]
) -> Dict[str, gpd.GeoDataFrame]:
    """
    Load LV power grid from GeoJSON files.
    
    Args:
        lines_path: Path to power_lines.geojson
        substations_path: Path to power_substations.geojson
        
    Returns:
        Dict with 'lines' and 'substations' GeoDataFrames
    """
    lines_path = Path(lines_path)
    substations_path = Path(substations_path)
    
    if not lines_path.exists():
        raise FileNotFoundError(f"Power lines file not found: {lines_path}")
    if not substations_path.exists():
        raise FileNotFoundError(f"Substations file not found: {substations_path}")
    
    logger.info(f"Loading power grid from {lines_path} and {substations_path}")
    
    # Load lines
    lines = gpd.read_file(lines_path)
    if 'voltage_kv' not in lines.columns:
        lines['voltage_kv'] = 0.4  # Default LV
        logger.warning("No voltage_kv column, defaulting to 0.4 kV")
    
    # Load substations
    substations = gpd.read_file(substations_path)
    if 'capacity_kva' not in substations.columns:
        substations['capacity_kva'] = 630  # Default
        logger.warning("No capacity_kva column, defaulting to 630 kVA")
    
    # Validate CRS
    if lines.crs != substations.crs:
        logger.warning(f"CRS mismatch: lines={lines.crs}, substations={substations.crs}")
        # Reproject substations to match lines
        substations = substations.to_crs(lines.crs)
    
    # Add metadata
    lines.attrs['source_file'] = str(lines_path)
    substations.attrs['source_file'] = str(substations_path)
    
    return {
        'lines': lines,
        'substations': substations
    }