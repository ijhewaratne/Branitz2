import streamlit as st
import pandas as pd
import geopandas as gpd
import pydeck as pdk
import os
import time
import sys
from pathlib import Path
import json

# Ensure src is in path - must be done BEFORE imports
# Calculate src path: app.py is at src/branitz_heat_decision/ui/app.py
# parents[0] = ui/, parents[1] = branitz_heat_decision/, parents[2] = src/
src_path = str(Path(__file__).parents[2])
if src_path not in sys.path:
    sys.path.insert(0, src_path)

from branitz_heat_decision.ui.services import ClusterService, JobService, ResultService
from branitz_heat_decision.ui.llm import LLMRouter
from branitz_heat_decision.ui.registry import SCENARIO_REGISTRY
from branitz_heat_decision.ui.env import bootstrap_env

# Load environment variables (API keys)
bootstrap_env()

st.set_page_config(page_title="Branitz Street Explorer", layout="wide", initial_sidebar_state="expanded")



# Initialize Services in Session State
if "services" not in st.session_state:
    cluster_service = ClusterService()
    job_service = JobService()
    result_service = ResultService()
    llm_router = LLMRouter(job_service)
    
    st.session_state.services = {
        "cluster": cluster_service,
        "job": job_service,
        "result": result_service,
        "llm": llm_router
    }

services = st.session_state.services

# --- Sidebar ---
st.sidebar.title("🏙️ Branitz Explorer")

# Load Cluster Index
try:
    cluster_index = services["cluster"].get_cluster_index()
except Exception as e:
    st.error(f"Failed to load cluster index: {e}")
    cluster_index = pd.DataFrame()

selected_cluster_id = None
if not cluster_index.empty:
    # Format for dropdown: "Name (ID)"
    # Sort by name
    cluster_index = cluster_index.sort_values("cluster_name")
    cluster_options = cluster_index.apply(lambda row: f"{row['cluster_name']} ({row['cluster_id']})", axis=1).tolist()
    
    # Use session state to persist selection if needed, but selectbox handles it
    selection = st.sidebar.selectbox("Select Street Cluster", cluster_options)
    
    if selection:
        selected_cluster_id = selection.split(" (")[-1].strip(")")
else:
    st.sidebar.warning("No clusters found. Run data preparation first.")

# Scenario Catalog
st.sidebar.markdown("---")
with st.sidebar.expander("🚀 Scenario Catalog", expanded=True):
    st.caption("Launch analysis workflows:")
    for key, spec in SCENARIO_REGISTRY.items():
        # Only show run buttons if a cluster is selected
        if selected_cluster_id:
            if st.button(spec["title"], key=f"btn_{key}", help=spec["description"]):
                job_id = services["job"].start_job(key, selected_cluster_id)
                st.toast(f"Started: {spec['title']}")
                time.sleep(0.5)
                st.rerun()
        else:
            st.button(spec["title"], disabled=True, key=f"btn_dis_{key}")

# Chat Interface in Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("💬 AI Assistant")

# Check connectivity
if services["llm"].model:
    st.sidebar.caption("🟢 Connected")
else:
    st.sidebar.caption("🔴 Offline (Keyword Fallback Mode)")

if "chat_history" not in st.session_state:

    st.session_state.chat_history = []

# Display chat history (limited to last few)
for msg in st.session_state.chat_history[-4:]:
    with st.sidebar.chat_message(msg["role"]):
        st.write(msg["content"])

# Example prompts
st.sidebar.caption("Try asking:")
example_prompts = [
    "Is District Heating feasible here?",
    "Compare DH vs Heat Pump costs",
    "Generate a status report"
]
current_prompt = None

for ex in example_prompts:
    if st.sidebar.button(ex, key=f"ex_{ex[:10]}"):
        current_prompt = ex

# Chat Input
user_input = st.sidebar.chat_input("Ask about this street...")
if user_input:
    current_prompt = user_input

if current_prompt and selected_cluster_id:
    # User message
    st.session_state.chat_history.append({"role": "user", "content": current_prompt})
    
    # Process with LLM Router (Plan -> Confirm -> Execute flow)
    with st.spinner("Thinking..."):
        try:
             response = services["llm"].route_intent(current_prompt, selected_cluster_id)
             st.session_state.chat_history.append({"role": "assistant", "content": response["message"]})
             
             if response.get("plan"):
                 st.session_state.pending_plan = response["plan"]
                 st.rerun()
                 
        except Exception as e:
             st.error(f"AI Error: {e}")

# Plan Confirmation UI
if "pending_plan" in st.session_state and st.session_state.pending_plan:
    st.sidebar.markdown("### 📋 Proposed Plan")
    plan = st.session_state.pending_plan
    
    for i, step in enumerate(plan):
        st.sidebar.info(f"**Step {i+1}**: {SCENARIO_REGISTRY[step['tool']]['title']}\n\n_{step['reason']}_")
        
    c1, c2 = st.sidebar.columns(2)
    if c1.button("✅ Execute", type="primary"):
        for step in plan:
            services["job"].start_job(step['tool'], selected_cluster_id)
            st.toast(f"Started: {step['tool']}")
        del st.session_state.pending_plan
        time.sleep(1)
        st.rerun()
        
    if c2.button("❌ Cancel"):
        del st.session_state.pending_plan
        st.rerun()


# --- Main Content ---

def render_stepper(current_stage: str):
    stages = ["Explore", "Feasibility", "Economics", "Decide", "Report"]
    # Simple CSS styled bubbles
    st.markdown("""
    <style>
    .step-container { display: flex; justify-content: space-between; margin-bottom: 20px; }
    .step { background-color: #f0f2f6; padding: 10px 20px; border-radius: 20px; color: #555; font-weight: bold; }
    .step.active { background-color: #ff4b4b; color: white; }
    </style>
    """, unsafe_allow_html=True)
    
    cols = st.columns(len(stages))
    for i, stage in enumerate(stages):
        is_active = (stage == current_stage)
        # We can't easily inject classes into st.columns, so we use markdown
        with cols[i]:
            if is_active:
                st.markdown(f":red-background[**{i+1}. {stage}**]")
            else:
                st.markdown(f"**{i+1}. {stage}**")



if selected_cluster_id:
    # Load details
    summary = services["cluster"].get_cluster_summary(selected_cluster_id)
    
    # Title
    st.title(f"{summary.get('cluster_name', selected_cluster_id)}")
    
    # Determine active stage based on artifacts? Or just let user click tabs.
    # Tabs are the navigation now.
    
    tabs = st.tabs(["Overview", "Feasibility", "Economics", "Compare & Decide", "Portfolio", "Jobs"])
    tab_overview, tab_feasibility, tab_economics, tab_decide, tab_portfolio, tab_jobs = tabs
    
    # Pre-loading data for shared use (Overview mostly)
    buildings_gdf = services["cluster"].get_buildings_for_cluster(selected_cluster_id)
    street_geom = services["cluster"].get_cluster_geometry(selected_cluster_id)
      
    # Load profile data for overview
    hourly_profile = services["cluster"].get_hourly_load(selected_cluster_id)
    design_info = services["cluster"].get_design_topn(selected_cluster_id)
    
    # -- Tab: Overview --
    with tab_overview:
        render_stepper("Explore")
        
        # Calculate annual demand from buildings if available (source of truth)
        if not buildings_gdf.empty and "annual_heat_demand_kwh_a" in buildings_gdf.columns:
            total_kwh = buildings_gdf["annual_heat_demand_kwh_a"].sum()
        else:
            total_kwh = summary.get('total_annual_heat_demand_kwh_a', 0)

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Buildings", summary.get("building_count", "N/A"))
        c2.metric("Annual Heat Demand", f"{total_kwh/1000:.1f} MWh/a", help="Sum of hourly kW over the year converted to MWh/a")
        c3.metric("Design Load", f"{summary.get('design_load_kw', 0):.1f} kW", help="Maximum hourly demand in the year")
        c4.metric("Coordinates", f"{summary.get('centroid_lat', 0):.4f}, {summary.get('centroid_lon', 0):.4f}")
        
        # --- Preflight Data Check ---
        readiness = services["cluster"].check_data_readiness(selected_cluster_id)
        if not readiness["ready"]:
            st.error("🚨 **Data Issues Detected**")
            for issue in readiness["issues"]:
                st.markdown(f"- {issue}")
            st.warning("Simulations (CHA/DHA) will likely fail until these data issues are resolved.")
        else:
            # Check for warnings in stats (e.g. partial profiles)
            stats = readiness.get("stats", {})
            if "fraction_with_profile" in stats and stats["fraction_with_profile"] < 1.0:
                 st.warning(f"⚠️ Partial Data: Only {stats['fraction_with_profile']:.1%} of buildings have hourly profiles.")
        
        with st.expander("📊 Data Completeness & Health"):
             st.json(readiness)

        # Sanity Check Banner
        if summary.get('design_load_kw', 0) > 0 and total_kwh == 0:
             st.warning("⚠️ **Data Inconsistency**: Annual demand is zero but Design Load is positive. Check if building profiles are correctly linked.")

        
        with st.expander("ℹ️ About Metrics"):
            st.markdown("""
            - **Annual Heat Demand**: Total thermal energy required by all buildings in the cluster over a standard year (MWh/a).
            - **Design Load**: The maximum hourly heat load (kW) occurring during the year ("Peak Load"). Used for pipe sizing.
            - **Design Hour**: The specific hour (0-8760) when the design load occurs.
            - **Building Types**: Categorization based on function (e.g., Residential, Commercial). Mixed clusters may have different load profiles.
            """)
        
        st.markdown("### Building Types & Demand")
        
        if not buildings_gdf.empty and "building_function" in buildings_gdf.columns:
             # Ensure annual heat is float
             buildings_gdf["annual_heat_demand_kwh_a"] = buildings_gdf.get("annual_heat_demand_kwh_a", 0.0).astype(float)
             
             # Group by type
             grouped = buildings_gdf.groupby("building_function").agg(
                 count=("building_id", "count"),
                 total_mwh=("annual_heat_demand_kwh_a", lambda x: x.sum() / 1000.0),
                 avg_mwh=("annual_heat_demand_kwh_a", lambda x: x.mean() / 1000.0)
             ).reset_index()
             
             # Table
             st.dataframe(grouped, use_container_width=True, hide_index=True)

        else:
             st.info("Building type data not available.")

        st.markdown("---")
        st.subheader("Aggregated Heat Demand Visualization")
        
        if hourly_profile is not None:
             # 1. Hourly Profile Chart
             st.markdown("#### Hourly Load Profile")
             import altair as alt
             
             chart_data = pd.DataFrame({
                 "Hour": hourly_profile.index,
                 "Load (kW)": hourly_profile.values
             })
             
             design_load = design_info.get("design_load_kw", 0)
             d_hour = design_info.get("design_hour", -1)
             
             # Base line chart
             base = alt.Chart(chart_data).encode(
                 x=alt.X("Hour", axis=alt.Axis(title="Hour of Year")),
                 y=alt.Y("Load (kW)", axis=alt.Axis(title="Heat Load (kW)")),
                 tooltip=["Hour", "Load (kW)"]
             )
             
             line = base.mark_line()
             
             # Design hour annotation
             if d_hour >= 0:
                 rule = alt.Chart(pd.DataFrame({'Hour': [d_hour]})).mark_rule(color='red').encode(x='Hour')
                 text = alt.Chart(pd.DataFrame({
                     'Hour': [d_hour], 
                     'Load (kW)': [design_load]
                 })).mark_text(
                     align='left', 
                     dx=5, 
                     dy=-5, 
                     color='red', 
                     text='Design Hour'
                 ).encode(x='Hour', y='Load (kW)')
                 
                 chart = (line + rule + text).interactive()
             else:
                 chart = line.interactive()
                 
             st.altair_chart(chart, use_container_width=True)
             
             # Show Design info text
             st.info(f"**Design Hour**: {d_hour} | **Design Load**: {design_load:.2f} kW", icon="🔥")
             
             # 2. Top-N Analysis
             st.markdown("#### Top-N Peak Hours")
             top_n_count = st.selectbox("Number of Top Hours", [10, 50, 100, 200], index=0)
             
             top_n_indices = hourly_profile.nlargest(top_n_count).index
             top_n_values = hourly_profile.nlargest(top_n_count).values
             
             top_n_df = pd.DataFrame({
                 "Rank": range(1, top_n_count + 1),
                 "Hour Index": top_n_indices,
                 "Load (kW)": top_n_values
             })
             st.dataframe(top_n_df, use_container_width=True)
        else:
             st.info("Hourly profiles not available. Ensure 'hourly_heat_profiles.parquet' exists.")

        st.markdown("### Interactive Map")
        if street_geom is not None and not buildings_gdf.empty:
            # Map Style Selector
            c1, c2 = st.columns([1, 3])
            with c1:
                map_style_name = st.selectbox(
                    "Map Background",
                    ["Light", "Dark", "Satellite", "OpenStreetMap"],
                    index=0
                )

            # Map Tiles Mapping
            TILE_PROVIDERS = {
                "Light": "https://a.basemaps.cartocdn.com/light_all/{z}/{x}/{y}@2x.png",
                "Dark": "https://a.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}@2x.png",
                "Satellite": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
                "OpenStreetMap": "https://c.tile.openstreetmap.org/{z}/{x}/{y}.png"
            }
            
            # Prepare PyDeck Layers
            
            # Background Tile Layer
            tile_layer = pdk.Layer(
                "TileLayer",
                data=TILE_PROVIDERS[map_style_name],
                get_line_color=[0, 0, 0],
                min_zoom=0,
                max_zoom=19,
                opacity=1.0,
                render_sub_layers=True
            )

            # Reproject to WGS84
            street_wgs84 = gpd.GeoSeries([street_geom], crs="EPSG:25833").to_crs("EPSG:4326")
            buildings_wgs84 = buildings_gdf.to_crs("EPSG:4326")
            
            # View state centered on street - convert to native Python types
            centroid_geom = street_wgs84.centroid.iloc[0]
            centroid_y = float(centroid_geom.y)
            centroid_x = float(centroid_geom.x)
            view_state = pdk.ViewState(
                latitude=centroid_y,
                longitude=centroid_x,
                zoom=16,
                pitch=45,
            )
            
            # Street Layer - Streets are LineString/MultiLineString, not Polygon
            # Convert to GeoJSON FeatureCollection format
            street_features = []
            for geom in street_wgs84:
                feature = {
                    "type": "Feature",
                    "geometry": geom.__geo_interface__,
                    "properties": {}
                }
                street_features.append(feature)
            
            # Use GeoJsonLayer for LineString geometry with visible line styling
            street_layer = pdk.Layer(
                "GeoJsonLayer",
                data=street_features,
                get_line_color=[100, 100, 100, 255],  # Dark gray lines
                line_width_min_pixels=3,               # Thick lines for visibility
                line_width_max_pixels=6,
                stroked=True,                          # Draw line outlines
                filled=False,                          # No fill for LineString
                pickable=True,
            )
            
            # Buildings Layer - Convert to GeoJSON with proper serialization
            def get_color(func):
                # Return as list (not numpy array) and ensure integers
                if "Wohn" in str(func):
                    return [255, 100, 100]  # Residential red
                return [100, 100, 255]  # Other blue
            
            # Prepare building features as GeoJSON
            building_features = []
            for idx, row in buildings_wgs84.iterrows():
                color = get_color(row.get("building_function", "Other"))
                feature = {
                    "type": "Feature",
                    "geometry": row.geometry.__geo_interface__,
                    "properties": {
                        "building_id": str(row.get("building_id", "")),
                        "building_function": str(row.get("building_function", "Other")),
                        "floor_area_m2": float(row.get("floor_area_m2", 0)) if pd.notna(row.get("floor_area_m2")) else 0.0,
                        "color": color
                    }
                }
                building_features.append(feature)
            
            building_layer = pdk.Layer(
                "GeoJsonLayer",
                data=building_features,
                get_fill_color="properties.color",
                get_line_color=[255, 255, 255],
                extruded=True,
                get_elevation=10,  # Default height if real height missing
                pickable=True,
                auto_highlight=True,
            )

            st.pydeck_chart(pdk.Deck(
                map_style=None, # Use TileLayer for background
                initial_view_state=view_state,
                layers=[tile_layer, street_layer, building_layer],
                tooltip={"html": "<b>Function:</b> {building_function}<br/><b>Area:</b> {floor_area_m2} m²"}
            ))
        else:
            st.warning("Geometry data not found. Ensure 'street_clusters.parquet' and 'buildings.parquet' exist in 'data/processed'.")



    # -- Tab: Feasibility --
    with tab_feasibility:
        render_stepper("Feasibility")
        st.info("Technical Feasibility Analysis")
        
        # Create sub-tabs for CHA and DHA
        cha_tab, dha_tab = st.tabs(["District Heating (CHA)", "Heat Pump Grid (DHA)"])
        
        with cha_tab:
            st.subheader("District Heating Network Analysis")
            cha_status = services["result"].get_result_status(selected_cluster_id)["cha"]
            if cha_status:
                st.success("Analysis Complete")
                
                # Show all 3 interactive maps sequentially
                map_types = ["velocity", "pressure", "temperature"]
                map_titles = {
                    "velocity": "🌊 Flow Velocity Map",
                    "pressure": "📊 Pressure Distribution Map",
                    "temperature": "🌡️ Temperature Map"
                }
                
                for map_type in map_types:
                    map_path = services["result"].get_cha_map_path(selected_cluster_id, map_type)
                    if map_path and map_path.exists():
                        st.markdown(f"### {map_titles.get(map_type, map_type.title())}")
                        with open(map_path, "r", encoding="utf-8") as f:
                            st.components.v1.html(f.read(), height=500, scrolling=True)
                        st.caption(f"{map_type.title()} visualization")
                        st.divider()
                
                # Show other CHA artifacts (JSON data)
                artifacts = services["result"].get_existing_artifacts(selected_cluster_id, "cha")
                json_artifacts = [art for art in artifacts if art.suffix == ".json"]
                if json_artifacts:
                    with st.expander("📄 CHA Data Files"):
                        for art in json_artifacts:
                            st.markdown(f"**{art.name}**")
                            st.json(json.load(open(art)))
            else:
                st.warning("CHA analysis not started")
                
                # Check for running job
                latest_job = services["job"].get_latest_job_for_cluster(selected_cluster_id)
                is_running = False
                if latest_job and latest_job.get("scenario") == "cha" and latest_job.get("status") == "running":
                    is_running = True

                if is_running:
                    st.info("⏳ CHA Analysis in progress...", icon="🏃")
                    if st.button("Analysis Running...", disabled=True, key="run_cha_feasibility_disabled"): pass
                    time.sleep(2)
                    st.rerun()
                else:
                    if st.button("Run CHA Analysis", key="run_cha_feasibility"):
                        services["job"].start_job("cha", selected_cluster_id)
                        st.rerun()

        with dha_tab:
            st.subheader("Heat Pump Grid Hosting Analysis")
            dha_status = services["result"].get_result_status(selected_cluster_id)["dha"]
            if dha_status:
                st.success("Analysis Complete")
                artifacts = services["result"].get_existing_artifacts(selected_cluster_id, "dha")
                
                # Load DHA KPIs for mitigation analysis
                dha_kpis = None
                for art in artifacts:
                    if art.suffix == ".json" and "dha_kpis" in art.name:
                        dha_kpis = json.load(open(art))
                        break
                
                # Display mitigation analysis if available (NEW)
                if dha_kpis and "mitigations" in dha_kpis:
                    mits = dha_kpis["mitigations"]
                    
                    st.divider()
                    st.markdown("### 🔧 Grid Mitigation Analysis")
                    
                    # Classification badge
                    class_colors = {
                        "none": ("🟢", "success"),
                        "operational": ("🟡", "info"),
                        "reinforcement": ("🟠", "warning"),
                        "expansion": ("🔴", "error")
                    }
                    
                    mit_class = mits.get("mitigation_class", "none")
                    emoji, badge_type = class_colors.get(mit_class, ("⚪", "info"))
                    
                    if badge_type == "success":
                        st.success(f"{emoji} **{mit_class.title()}**: {mits.get('summary', '')}")
                    elif badge_type == "error":
                        st.error(f"{emoji} **{mit_class.title()}**: {mits.get('summary', '')}")
                    else:
                        st.warning(f"{emoji} **{mit_class.title()}**: {mits.get('summary', '')}")
                    
                    # Recommendations
                    if mits.get("recommendations"):
                        st.markdown("#### 📋 Recommended Actions")
                        
                        for rec in mits["recommendations"]:
                            severity_emoji = {"low": "🟢", "moderate": "🟡", "high": "🔴"}.get(rec.get("severity", "moderate"), "⚪")
                            with st.expander(f"{severity_emoji} {rec.get('title', 'Recommendation')}", expanded=(rec.get('severity') == 'high')):
                                col1, col2 = st.columns([2, 1])
                                with col1:
                                    st.markdown(f"**Category:** {rec.get('category', '').title()}")
                                with col2:
                                    st.markdown(f"**Est. Cost:** {rec.get('estimated_cost_class', '').title()}")
                                
                                st.markdown("**Actions:**")
                                for action in rec.get("actions", []):
                                    st.markdown(f"- {action}")
                                
                                # Show evidence directly (cannot nest expanders)
                                if rec.get("evidence"):
                                    st.markdown("**🔍 Evidence:**")
                                    st.json(rec.get("evidence", {}))
                    
                    # Final verdict
                    st.divider()
                    if mits.get("feasible_with_mitigation"):
                        st.success("✅ Grid can host heat pumps with indicated mitigations")
                    else:
                        st.error("❌ Major grid expansion required - heat pumps not feasible without significant investment")
                
                # Display Fraunhofer Grid Planning Results (NEW)
                hc_art = next((a for a in artifacts if "dha_hosting_capacity" in a.name and a.suffix == ".json"), None)
                strat_art = next((a for a in artifacts if "dha_strategies" in a.name and a.suffix == ".json"), None)
                reinf_art = next((a for a in artifacts if "dha_reinforcement" in a.name and a.suffix == ".json"), None)

                if any([hc_art, strat_art, reinf_art]):
                    st.divider()
                    st.markdown("### ⚡ Advanced Grid Planning (Fraunhofer IWES)")
                    
                    # 1. Hosting Capacity
                    if hc_art:
                        try:
                            hc_data = json.load(open(hc_art))
                            st.markdown("#### 📊 Monte Carlo Hosting Capacity")
                            
                            c1, c2, c3 = st.columns(3)
                            c1.metric("Median Safe Capacity", f"{hc_data.get('safe_capacity_median_kw', 0):.1f} kW")
                            c2.metric("Median Penetration", f"{hc_data.get('safe_penetration_median_pct', 0):.1%}")
                            n_safe = hc_data.get('safe_scenarios', 0)
                            n_total = hc_data.get('scenarios_analyzed', 0)
                            c3.metric("Safe Scenarios", f"{n_safe}/{n_total}")
                            
                            score = n_safe / max(1, n_total)
                            if score > 0.9: st.success("✅ Grid is robust across most scenarios.")
                            elif score > 0.5: st.warning("⚠️ Grid has violations in some high-load scenarios.")
                            else: st.error("❌ Grid consistently violates constraints at high penetration.")
                        except Exception as e:
                            st.error(f"Error loading hosting capacity: {e}")

                    # 2. Smart Grid Strategies
                    if strat_art:
                        try:
                            strat_data = json.load(open(strat_art))
                            st.markdown("#### 🧠 Smart Grid Strategies")
                            
                            # Flatten for display
                            rows = []
                            for name, res in strat_data.items():
                                rows.append({
                                    "Strategy": name.replace('_', ' ').title(),
                                    "Feasible": "✅" if res.get('is_feasible') else "❌",
                                    "Load Red.": f"{res.get('loading_reduction_pct', 0.0):.1f}%",
                                    "Volt Imp.": f"{res.get('voltage_improvement_pu', 0.0):.4f} pu",
                                    "Est. Cost": f"€{res.get('cost_estimate_eur', 0):,.0f}"
                                })
                            st.dataframe(rows, use_container_width=True)
                        except Exception as e:
                            st.error(f"Error loading strategies: {e}")

                    # 3. Reinforcement Plan
                    if reinf_art:
                        try:
                            reinf_data = json.load(open(reinf_art))
                            st.markdown("#### 🛠️ Automated Reinforcement Plan")
                            
                            cost = reinf_data.get('total_cost_eur', 0)
                            sufficient = reinf_data.get('is_sufficient', False)
                            measures = reinf_data.get('measures', [])

                            rc1, rc2 = st.columns(2)
                            rc1.metric("Total Upgrade Cost", f"€{cost:,.2f}")
                            rc2.metric("Plan Outcome", "Sufficient ✅" if sufficient else "Violations Remain ⚠️")
                            
                            if measures:
                                with st.expander(f"Show {len(measures)} Upgrade Measures", expanded=False):
                                    for m in measures:
                                        m_type = m.get('measure_type', 'Upgrade').replace('_', ' ').title()
                                        desc = m.get('description', 'Unknown')
                                        m_cost = m.get('cost_eur', 0)
                                        st.markdown(f"- **{m_type}**: {desc} (Cost: €{m_cost:.2f})")
                            else:
                                st.info("No reinforcement measures required.")
                        except Exception as e:
                            st.error(f"Error loading reinforcement plan: {e}")

                # Display DHA map
                st.divider()
                st.markdown("### 📍 Grid Hosting Capacity Map")
                for art in artifacts:
                    if art.suffix == ".html":
                         with open(art, "r", encoding="utf-8") as f:
                             st.components.v1.html(f.read(), height=500, scrolling=True)
                         st.caption(f"Map: {art.name}")
                         break
                
                # Show DHA data files
                json_artifacts = [art for art in artifacts if art.suffix == ".json"]
                if json_artifacts:
                    with st.expander("📄 DHA Data Files"):
                        for art in json_artifacts:
                            st.markdown(f"**{art.name}**")
                            st.json(json.load(open(art)))
            else:
                st.warning("DHA analysis not started")
                
                # Check for running job
                latest_job = services["job"].get_latest_job_for_cluster(selected_cluster_id)
                is_running = False
                if latest_job and latest_job.get("scenario") == "dha" and latest_job.get("status") == "running":
                    is_running = True

                if is_running:
                    st.info("⏳ DHA Analysis in progress...", icon="🏃")
                    if st.button("Analysis Running...", disabled=True, key="run_dha_feasibility_disabled"): pass
                    time.sleep(2)
                    st.rerun()
                else:
                    if st.button("Run DHA Analysis", key="run_dha_feasibility"):
                        services["job"].start_job("dha", selected_cluster_id)
                        st.rerun()

    # -- Tab: Economics --
    with tab_economics:
        render_stepper("Economics")
        st.subheader("Economic Analysis & Robustness")

        def _build_capex_breakdown_for_ui(dh_breakdown: dict, hp_breakdown: dict) -> tuple:
            """Adapt economics_deterministic format to UI capex_breakdown structure."""
            dh_capex = {
                "network_pipes": dh_breakdown.get("capex_pipes", 0),
                "connection": 0.0,  # Included in capex_pipes when using CHA lengths
                "plant_allocated": dh_breakdown.get("capex_plant", 0),
                "pump": dh_breakdown.get("capex_pump", 0),
                "lv_upgrade": 0.0,  # DH has no LV upgrade
            }
            hp_capex = {
                "network_pipes": 0.0,
                "connection": 0.0,
                "plant_allocated": 0.0,
                "pump": 0.0,
                "lv_upgrade": hp_breakdown.get("capex_lv_upgrade", 0),
            }
            dh_data = {
                **dh_breakdown,
                "capex_breakdown": dh_capex,
                "capex_total": dh_breakdown.get("capex_total", 0),
                "opex_annual": dh_breakdown.get("opex_annual", 0),
                "plant_allocation": dh_breakdown.get("plant_allocation", {}),
            }
            hp_data = {
                **hp_breakdown,
                "capex_breakdown": hp_capex,
                "capex_hp": hp_breakdown.get("capex_hp", 0),
                "capex_total": hp_breakdown.get("capex_total", 0),
                "opex_annual": hp_breakdown.get("opex_annual", 0),
            }
            return dh_data, hp_data

        def render_detailed_cost_breakdown(econ_results: dict, system_type: str = "DH"):
            """Render expandable cost breakdown with correct marginal cost display."""
            prefix = "dh" if system_type == "DH" else "hp"
            data = econ_results.get(prefix, {})
            capex = data.get("capex_breakdown", {})

            title = "District Heating" if system_type == "DH" else "Heat Pump"
            with st.expander(f"💰 {title} - Detailed Breakdown", expanded=True):
                col1, col2 = st.columns(2)

                with col1:
                    st.subheader(title)
                    st.markdown("**Capital Costs (CAPEX)**")
                    c1, c2 = st.columns([3, 1])

                    if system_type == "DH":
                        c1.text("Network Pipes:")
                        c2.text(f"{capex.get('network_pipes', 0):,.0f} €")

                        c1.text("Connection to Plant:")
                        c2.text(f"{capex.get('connection', 0):,.0f} €")

                        c1.text("Street Pump:")
                        c2.text(f"{capex.get('pump', 0):,.0f} €")

                        plant_alloc = capex.get("plant_allocated", 0)
                        c1.markdown("**Plant Cost Allocation:**")
                        if plant_alloc > 0:
                            c2.markdown(f"**{plant_alloc:,.0f} €**", help="Marginal capacity expansion cost")
                        else:
                            c2.markdown("**0 €**", help="Utilizes existing plant capacity (sunk cost)")

                        lv_cost = capex.get("lv_upgrade", 0)
                        if lv_cost > 0:
                            c1.text("LV Grid Upgrade:")
                            c2.text(f"{lv_cost:,.0f} € ⚡")
                    else:
                        c1.text("Heat Pump Units:")
                        c2.text(f"{data.get('capex_hp', 0):,.0f} €")

                        lv_cost = capex.get("lv_upgrade", 0)
                        c1.text("LV Grid Upgrade:")
                        c2.text(f"{lv_cost:,.0f} € ⚡")

                    st.divider()
                    st.markdown(f"**Total CAPEX: {data.get('capex_total', 0):,.0f} €**")

                with col2:
                    st.markdown("**Operating Costs (OPEX)**")
                    opex = data.get("opex_annual", 0)
                    st.text(f"Annual OPEX: {opex:,.0f} €")

                    alloc_info = data.get("plant_allocation", {}) if system_type == "DH" else {}
                    if alloc_info:
                        st.info(
                            f"""
**Cost Method: {alloc_info.get('method', 'N/A').upper()}**

{alloc_info.get('rationale', 'No allocation info')}
"""
                        )
                        alloc_eur = alloc_info.get("allocated_eur", alloc_info.get("allocated_cost", 0))
                        if alloc_info.get("method") == "marginal" and alloc_eur == 0:
                            st.success(
                                "✅ **Marginal Cost Principle Applied**\n\nPlant is treated as shared infrastructure. Only network extension costs considered at cluster level.",
                                icon="💡",
                            )

                with st.expander("🔍 Raw Data"):
                    st.json(data)

        def render_comparison_with_lv_upgrade(dh_data: dict, hp_data: dict):
            """Side-by-side comparison including LV grid upgrade visibility."""
            col1, col2 = st.columns(2)

            with col1:
                st.header("🏭 District Heating")
                dh = dh_data.get("capex_breakdown", {})

                st.metric("Network Cost", f"{dh.get('network_pipes', 0):,.0f} €")
                st.metric(
                    "Plant Allocation",
                    f"{dh.get('plant_allocated', 0):,.0f} €",
                    help="Marginal cost: Only expansion capacity, not full plant",
                )

                if dh.get("network_pipes", 0) == 0:
                    st.error("⚠️ Network pipes showing 0€ - check geometry extraction")

            with col2:
                st.header("⚡ Heat Pump + LV Grid")
                hp = hp_data.get("capex_breakdown", {})

                st.metric("Heat Pump Units", f"{hp_data.get('capex_hp', 0):,.0f} €")

                lv_cost = hp.get("lv_upgrade", 0)
                if lv_cost > 0:
                    st.metric("LV Grid Upgrade", f"{lv_cost:,.0f} €", delta="Required", delta_color="inverse")
                    st.info("Grid reinforcement needed for HP electrification")
                else:
                    st.metric("LV Grid Upgrade", "0 €", delta="No upgrade needed", delta_color="normal")

                st.metric("Total HP CAPEX", f"{hp_data.get('capex_total', 0):,.0f} €")

        econ_status = services["result"].get_result_status(selected_cluster_id)["economics"]
        if econ_status:
            st.success("Economic Simulation Complete")
            artifacts = services["result"].get_existing_artifacts(selected_cluster_id, "economics")

            # Load files by matching names
            deterministic = None
            monte_carlo = None

            for art in artifacts:
                if "deterministic" in art.name:
                    deterministic = json.load(open(art))
                elif "monte_carlo" in art.name:
                    monte_carlo = json.load(open(art))

            if deterministic:
                # Build UI-friendly breakdown
                dh_breakdown = deterministic.get("lcoh_dh_breakdown", {})
                hp_breakdown = deterministic.get("lcoh_hp_breakdown", {})
                dh_data, hp_data = _build_capex_breakdown_for_ui(dh_breakdown, hp_breakdown)
                econ_for_ui = {"dh": dh_data, "hp": hp_data}

                # 1. LCOH COMPARISON
                st.markdown("### 💰 Levelized Cost of Heat (LCoH)")
                col1, col2 = st.columns(2)
                
                lcoh_dh = deterministic.get("lcoh_dh_eur_per_mwh", 0)
                lcoh_hp = deterministic.get("lcoh_hp_eur_per_mwh", 0)
                diff_pct = ((lcoh_hp - lcoh_dh) / lcoh_dh * 100) if lcoh_dh > 0 else 0
                
                with col1:
                    st.metric(
                        "District Heating",
                        f"{lcoh_dh:.2f} EUR/MWh",
                        delta=f"{-diff_pct:.1f}%" if diff_pct < 0 else None,
                        delta_color="inverse" if diff_pct < 0 else "normal"
                    )
                with col2:
                    st.metric(
                        "Heat Pump",
                        f"{lcoh_hp:.2f} EUR/MWh",
                        delta=f"+{diff_pct:.1f}%" if diff_pct > 0 else None,
                        delta_color="inverse"
                    )
                
                # Winner badge
                if lcoh_dh < lcoh_hp:
                    st.success(f"✅ District Heating is {diff_pct:.1f}% cheaper")
                elif lcoh_hp < lcoh_dh:
                    st.info(f"✅ Heat Pump is {-diff_pct:.1f}% cheaper")
                else:
                    st.warning("⚖️ Costs are equal")
                
                st.markdown("---")
                
                # 2. CO₂ COMPARISON
                st.markdown("### 🌍 CO₂ Emissions")
                col1, col2 = st.columns(2)
                
                co2_dh = deterministic.get("co2_dh_kg_per_mwh", 0)
                co2_hp = deterministic.get("co2_hp_kg_per_mwh", 0)
                co2_diff_pct = ((co2_hp - co2_dh) / co2_dh * 100) if co2_dh > 0 else 0
                
                with col1:
                    st.metric(
                        "District Heating",
                        f"{co2_dh:.1f} kg/MWh",
                        delta=f"{deterministic.get('co2_dh_t_per_a', 0):.1f} t/year"
                    )
                with col2:
                    st.metric(
                        "Heat Pump",
                        f"{co2_hp:.1f} kg/MWh",
                        delta=f"{deterministic.get('co2_hp_t_per_a', 0):.1f} t/year"
                    )
                
                if co2_dh < co2_hp:
                    st.success(f"🌱 District Heating emits {co2_diff_pct:.1f}% less CO₂")
                elif co2_hp < co2_dh:
                    st.info(f"🌱 Heat Pump emits {-co2_diff_pct:.1f}% less CO₂")
                
                st.markdown("---")
                
                # 3. MONTE CARLO ROBUSTNESS
                if monte_carlo:
                    st.markdown("### 📊 Monte Carlo Robustness Analysis")
                    st.markdown(f"**Simulations**: {int(monte_carlo.get('n', 0))} scenarios with varying economic parameters")
                    
                    col1, col2 = st.columns(2)
                    with col1:
                        prob_dh_cheaper = monte_carlo.get("prob_dh_cheaper", 0)
                        st.metric(
                            "DH Cheaper (Probability)",
                            f"{prob_dh_cheaper*100:.1f}%",
                            help="Probability that District Heating has lower LCoH across scenarios"
                        )
                    with col2:
                        prob_dh_co2 = monte_carlo.get("prob_dh_lower_co2", 0)
                        st.metric(
                            "DH Lower CO₂ (Probability)",
                            f"{prob_dh_co2*100:.1f}%",
                            help="Probability that District Heating has lower emissions"
                        )
                    
                    # Percentile ranges
                    st.markdown("**LCoH Uncertainty Ranges (10th - 90th percentile):**")
                    col1, col2 = st.columns(2)
                    with col1:
                        p10_dh = monte_carlo.get("lcoh_dh_p10", 0)
                        p50_dh = monte_carlo.get("lcoh_dh_p50", 0)
                        p90_dh = monte_carlo.get("lcoh_dh_p90", 0)
                        st.markdown(f"**DH**: {p10_dh:.1f} - **{p50_dh:.1f}** - {p90_dh:.1f} EUR/MWh")
                    with col2:
                        p10_hp = monte_carlo.get("lcoh_hp_p10", 0)
                        p50_hp = monte_carlo.get("lcoh_hp_p50", 0)
                        p90_hp = monte_carlo.get("lcoh_hp_p90", 0)
                        st.markdown(f"**HP**: {p10_hp:.1f} - **{p50_hp:.1f}** - {p90_hp:.1f} EUR/MWh")
                    
                    st.caption("Bold values are median (P50)")
                
                st.markdown("---")

                # 4. COST BREAKDOWN (with marginal cost display)
                st.markdown("### 💵 Cost Breakdown Comparison")
                render_comparison_with_lv_upgrade(dh_data, hp_data)
                st.divider()

                # DH and HP detailed breakdowns
                dh_col, hp_col = st.columns(2)
                with dh_col:
                    render_detailed_cost_breakdown(econ_for_ui, system_type="DH")
                with hp_col:
                    render_detailed_cost_breakdown(econ_for_ui, system_type="HP")
                
                # 5. SYSTEM INFO (expandable)
                with st.expander("ℹ️ System Configuration"):
                    st.markdown(f"**Annual Heat Demand**: {deterministic.get('annual_heat_mwh', 0):.1f} MWh/year")
                    st.markdown(f"**Design Capacity**: {deterministic.get('design_capacity_kw', 0):.1f} kW")
                    st.markdown(f"**Total Pipe Length**: {deterministic.get('total_pipe_length_m', 0):.1f} m")
                    if monte_carlo:
                        st.json(monte_carlo)
                
                # 6. ROBUSTNESS VALIDATION (if available)
                sensitivity_path = services["result"].get_existing_artifacts(selected_cluster_id, "economics")
                stress_path = services["result"].get_existing_artifacts(selected_cluster_id, "economics")
                
                validation_data = {}
                for art in services["result"].get_existing_artifacts(selected_cluster_id, "economics"):
                    if "sensitivity" in art.name:
                        validation_data["sensitivity"] = json.load(open(art))
                    elif "stress" in art.name:
                        validation_data["stress"] = json.load(open(art))
                
                if validation_data:
                    st.markdown("---")
                    with st.expander("🧪 Robustness Validation"):
                        # SENSITIVITY ANALYSIS
                        if "sensitivity" in validation_data:
                            sens = validation_data["sensitivity"]
                            st.markdown("#### 📐 Sensitivity Analysis (±5% Parameter Variations)")
                            
                            if sens.get("any_flip_detected"):
                                st.warning(f"⚠️ Decision flipped for {sum(1 for r in sens.get('results', {}).values() if r.get('flipped'))} parameter(s)")
                            else:
                                st.success("✅ Decision stable across all ±5% parameter variations")
                            
                            # Table of results
                            if sens.get("results"):
                                sens_table = []
                                for param, result in sens["results"].items():
                                    sens_table.append({
                                        "Parameter": param.replace("_", " ").title(),
                                        "Sensitivity Index": f"{result.get('sensitivity_index', 0):.3f}",
                                        "Decision Flipped?": "⚠️ Yes" if result.get("flipped") else "✅ No"
                                    })
                                st.dataframe(pd.DataFrame(sens_table), use_container_width=True)
                        
                        # STRESS TESTS
                        if "stress" in validation_data:
                            st.markdown("#### 🏋️ Stress Testing (Counterfactual Scenarios)")
                            stress = validation_data["stress"]
                            
                            if stress.get("robust"):
                                st.success(f"✅ Decision ROBUST: No flips across {stress.get('scenarios_tested', 0)} extreme scenarios")
                            else:
                                st.error(f"❌ {stress.get('flips_detected', 0)} scenario(s) caused decision flip")
                            
                            # Table of scenarios
                            if stress.get("results"):
                                stress_table = []
                                for scenario_id, result in stress["results"].items():
                                    stress_table.append({
                                        "Scenario": result.get("description", scenario_id),
                                        "Decision": result.get("decision", "N/A"),
                                        "Flipped?": "⚠️ Yes" if result.get("flipped") else "✅ No",
                                        "Cost Shift": f"{result.get('cost_shift_pct', 0):+.1f}%"
                                    })
                                st.dataframe(pd.DataFrame(stress_table), use_container_width=True)
                                
                                st.caption(f"Worst-case scenario: {stress.get('worst_case_scenario', 'N/A')}")
            else:
                st.error("Economic data found but could not be parsed.")
        else:
            st.warning("Economics not run.")
            if st.button("Run Economics", key="run_econ_tab"):
                services["job"].start_job("economics", selected_cluster_id)
                st.rerun()


    # -- Tab: Compare & Decide --
    with tab_decide:
        render_stepper("Decide")
        st.subheader("Final Decision")
        
        dec_status = services["result"].get_result_status(selected_cluster_id)["decision"]
        if dec_status:
            artifacts = services["result"].get_existing_artifacts(selected_cluster_id, "decision")
            if artifacts:
                res = json.load(open(artifacts[0]))
                
                # Extract key fields
                choice = res.get("choice", res.get("recommendation", "UNKNOWN"))
                robust = res.get("robust", None)
                reason_codes = res.get("reason_codes", [])
                metrics = res.get("metrics_used", {})
                
                # Map choice values to display names
                choice_display = {"DH": "DISTRICT_HEATING", "HP": "HEAT_PUMP", "UNDECIDED": "UNDECIDED"}.get(choice, choice)
                color = "green" if choice == "DH" else "blue" if choice == "HP" else "orange"
                
                # 1. SHOW RECOMMENDATION BADGE (prominent)
                st.markdown(f"## 🎯 Recommended Solution")
                st.markdown(f"# :{color}[{choice_display}]")
                
                # 2. ROBUSTNESS INDICATOR
                if robust is not None:
                    if robust:
                        st.success("✅ **Robust Decision**: High confidence (Monte Carlo win rate ≥70%)")
                    else:
                        st.warning("⚠️ **Sensitive Decision**: Moderate confidence (cost/benefits are close)")
                else:
                    st.info("ℹ️ Robustness data not available")
                
                st.markdown("---")
                
                # 3. LLM EXPLANATION (if available)
                explanation_md_path = services["result"].get_decision_explanation_path(selected_cluster_id, "md")
                explanation_html_path = services["result"].get_decision_explanation_path(selected_cluster_id, "html")
                
                if explanation_html_path:
                    st.subheader("🤖 AI Explanation")
                    with open(explanation_html_path, "r", encoding="utf-8") as f:
                        html_content = f.read()
                    st.components.v1.html(html_content, height=600, scrolling=True)
                    st.caption(f"Explanation: {explanation_html_path.name}")
                    st.markdown("---")
                elif explanation_md_path:
                    st.subheader("🤖 AI Explanation")
                    with open(explanation_md_path, "r", encoding="utf-8") as f:
                        md_content = f.read()
                    st.markdown(md_content)
                    st.caption(f"Explanation: {explanation_md_path.name}")
                    st.markdown("---")
                
                # VALIDATION REPORT DISPLAY (NEW - TNLI Logic Auditor)
                # Check for either 'validation' (new pipeline) or 'validation_report' (legacy)
                val_data = res.get("validation", res.get("validation_report"))
                
                if val_data:
                    st.subheader("🔍 Explanation Validation")
                    
                    # Status badge
                    status = val_data.get("validation_status", "unknown")
                    confidence = val_data.get("overall_confidence", 0.0)
                    
                    if status == "pass":
                        st.success(f"✅ **Validated** - All statements consistent with data (Confidence: {confidence:.1%})")
                    elif status == "warning":
                        st.warning(f"⚠️ **Warnings Detected** - Some statements have low confidence ({confidence:.1%})")
                    elif status == "fail":
                        num_contradictions = len(val_data.get("contradictions", []))
                        st.error(f"❌ **Contradictions Found** - {num_contradictions} statement(s) contradict the data")
                    else:
                        st.info(f"ℹ️ Validation status: {status}")
                    
                    # Detailed breakdown
                    with st.expander("📊 View Validation Details", expanded=(status == "fail")):
                        
                        # Summary stats
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            verified = val_data.get("verified_count", 0)
                            st.metric("✅ Verified", verified)
                        with col2:
                            unverified = val_data.get("unverified_count", 0)
                            st.metric("⚠️ Unverified", unverified)
                        with col3:
                            contradictions = val_data.get("contradiction_count", len(val_data.get("contradictions", [])))
                            st.metric("❌ Contradictions", contradictions)
                        
                        # Sentence-by-sentence results (NEW)
                        sentence_results = val_data.get("sentence_results", [])
                        if sentence_results:
                            st.markdown("#### 📋 Statement-by-Statement Validation")
                            for i, result in enumerate(sentence_results, 1):
                                result_status = result.get("status", "UNKNOWN")
                                statement = result.get("statement", "Unknown statement")
                                evidence = result.get("evidence", "")
                                confidence = result.get("confidence", 0.0)
                                label = result.get("label", "Unknown")
                                
                                # Determine display style based on status
                                if result_status == "ENTAILMENT":
                                    emoji = "✅"
                                    st.success(f"**[{i}/{len(sentence_results)}]** {emoji} **TRUE (ENTAILMENT)**: {statement}")
                                elif result_status == "CONTRADICTION":
                                    emoji = "❌"
                                    st.error(f"**[{i}/{len(sentence_results)}]** {emoji} **FALSE (CONTRADICTION)**: {statement}")
                                else:
                                    emoji = "⚠️"
                                    st.warning(f"**[{i}/{len(sentence_results)}]** {emoji} **NEUTRAL (UNVERIFIED)**: {statement}")
                                
                                # Show evidence and confidence
                                if evidence:
                                    st.caption(f"💡 **Evidence:** {evidence}")
                                st.caption(f"**Label:** {label} | **Confidence:** {confidence:.0%}")
                                st.divider()
                        elif val_data.get("statements_validated", 0) > 0:
                            # If statements were validated but sentence_results not available (old format)
                            st.markdown("#### 📋 Statement-by-Statement Validation")
                            st.info("ℹ️ Sentence-by-sentence results not available in this validation report. This may be an older format. Re-run the decision pipeline to get detailed sentence-by-sentence validation.")
                        
                        # Contradictions (additional details)
                        contradictions_list = val_data.get("contradictions", [])
                        if contradictions_list:
                            st.markdown("#### ❌ Contradictions Detected")
                            for i, contra in enumerate(contradictions_list, 1):
                                with st.container():
                                    st.markdown(f"**{i}. {contra.get('statement', 'Unknown statement')}**")
                                    st.caption(f"Context: {contra.get('context', 'N/A')}")
                                    # Show evidence directly (cannot nest expanders)
                                    if contra.get("evidence"):
                                        st.markdown("**🔍 Evidence:**")
                                        st.json(contra["evidence"])
                                    st.divider()
                        
                        # Warnings
                        warnings = val_data.get("warnings", [])
                        if warnings:
                            st.markdown("#### ⚠️ Warnings")
                            for warning in warnings:
                                st.warning(warning)
                        
                        # Feedback history
                        iterations = val_data.get("feedback_iterations", 0)
                        if iterations > 0:
                            st.markdown(f"#### 🔄 Feedback Loop History")
                            st.info(f"Explanation was automatically refined {iterations} time(s) to resolve contradictions.")
                    
                    st.markdown("---")
                
                # If no validation report, offer to run live validation
                if not val_data:
                    st.subheader("🔍 Explanation Validation")
                    st.info("ℹ️ **TNLI Logic Auditor** validates LLM-generated explanations against KPI data.")
                    
                    # Check if we have explanation to validate
                    explanation_text = res.get("explanation", "")
                    kpi_data = res.get("kpis", res.get("metrics_used", {}))
                    
                    if kpi_data or reason_codes:
                        if st.button("🚀 Run Live Validation", key="run_tnli_validation"):
                            with st.spinner("Running TNLI validation..."):
                                try:
                                    from branitz_heat_decision.validation import LogicAuditor
                                    
                                    auditor = LogicAuditor()
                                    
                                    # Issue A Fix: Build complete decision data for proper validation
                                    # This ensures choice/reason_codes are injected into KPIs
                                    # Note: If explanation is empty, still pass empty string (not None) to allow parsing
                                    decision_data = {
                                        "choice": choice,
                                        "reason_codes": reason_codes,
                                        "kpis": kpi_data,
                                        "cluster_id": selected_cluster_id,
                                        "robust": robust,
                                        "explanation": explanation_text if explanation_text else ""
                                    }
                                    
                                    # Use validate_decision_explanation for proper structured claims validation
                                    report = auditor.validate_decision_explanation(decision_data)
                                    
                                    # Display actual results
                                    st.markdown("### ✅ Validation Complete!")
                                    
                                    status = report.validation_status
                                    confidence = report.overall_confidence
                                    
                                    if status == "pass":
                                        st.success(f"✅ **Validated** - All statements consistent (Confidence: {confidence:.1%})")
                                    elif status == "warning":
                                        st.warning(f"⚠️ **Warnings** - Low confidence ({confidence:.1%})")
                                    else:
                                        st.error(f"❌ **Contradictions Found** ({len(report.contradictions)} issues)")
                                    
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        st.metric("Statements", report.statements_validated)
                                    with col2:
                                        st.metric("Pass Rate", f"{report.pass_rate:.0%}")
                                    with col3:
                                        st.metric("Confidence", f"{confidence:.0%}")
                                    
                                    # Edit C: Show proper scoring metrics
                                    st.markdown("#### 📊 Validation Breakdown")
                                    col1, col2, col3 = st.columns(3)
                                    with col1:
                                        verified = getattr(report, 'verified_count', 0)
                                        st.metric("✅ Verified", verified, 
                                            help="Statements confirmed by KPI data")
                                    with col2:
                                        unverified = getattr(report, 'unverified_count', 0)
                                        st.metric("⚠️ Unverified", unverified,
                                            help="Statements that could not be verified")
                                    with col3:
                                        contradictions = getattr(report, 'contradiction_count', len(report.contradictions))
                                        st.metric("❌ Contradictions", contradictions,
                                            help="Statements that contradict the data")
                                    
                                    # Show KPI data used for validation
                                    with st.expander("📊 KPI Data Used for Validation", expanded=False):
                                        st.json(kpi_data)
                                    
                                    # Show validated statements with results
                                    st.markdown("#### 📋 Statement-by-Statement Validation")
                                    
                                    # Debug: Check what we have
                                    has_entailment = hasattr(report, 'entailment_results')
                                    entailment_count = len(report.entailment_results) if has_entailment and report.entailment_results else 0
                                    
                                    # Check if we have sentence results
                                    if has_entailment and report.entailment_results and len(report.entailment_results) > 0:
                                        for i, result in enumerate(report.entailment_results, 1):
                                            if result.is_valid:
                                                emoji = "✅"
                                                status_text = "TRUE (ENTAILMENT)"
                                                st.success(f"**[{i}/{len(report.entailment_results)}]** {emoji} **{status_text}**: {result.statement}")
                                            elif result.is_contradiction:
                                                emoji = "❌"
                                                status_text = "FALSE (CONTRADICTION)"
                                                st.error(f"**[{i}/{len(report.entailment_results)}]** {emoji} **{status_text}**: {result.statement}")
                                            else:
                                                emoji = "⚠️"
                                                status_text = "NEUTRAL (UNVERIFIED)"
                                                st.warning(f"**[{i}/{len(report.entailment_results)}]** {emoji} **{status_text}**: {result.statement}")
                                            
                                            # Show reasoning/evidence
                                            reason = getattr(result, 'reason', '')
                                            if reason:
                                                st.caption(f"💡 **Evidence:** {reason}")
                                            
                                            label_value = getattr(result.label, 'value', str(result.label)) if hasattr(result, 'label') else 'Unknown'
                                            confidence = getattr(result, 'confidence', 0.0)
                                            st.caption(f"**Label:** {label_value} | **Confidence:** {confidence:.0%}")
                                            st.divider()
                                    else:
                                        # If no entailment_results, show debug info
                                        if report.statements_validated > 0:
                                            st.warning(f"⚠️ {report.statements_validated} statement(s) were validated, but sentence-by-sentence results are not displaying.")
                                            
                                            # Debug info to help diagnose
                                            with st.expander("🔍 Debug Info - Why results aren't showing", expanded=True):
                                                debug_info = {
                                                    "statements_validated": report.statements_validated,
                                                    "has_entailment_results_attr": hasattr(report, 'entailment_results'),
                                                    "entailment_results_is_list": isinstance(getattr(report, 'entailment_results', None), list),
                                                    "entailment_results_count": entailment_count,
                                                    "entailment_results_empty": not (has_entailment and report.entailment_results),
                                                    "has_explanation": bool(explanation_text),
                                                    "explanation_length": len(explanation_text) if explanation_text else 0,
                                                    "has_reason_codes": bool(reason_codes),
                                                    "reason_codes": reason_codes,
                                                    "validation_status": report.validation_status,
                                                    "verified_count": getattr(report, 'verified_count', 0),
                                                    "contradiction_count": getattr(report, 'contradiction_count', 0)
                                                }
                                                st.json(debug_info)
                                                
                                                # Try to show what we can
                                                if has_entailment and isinstance(report.entailment_results, list):
                                                    if len(report.entailment_results) == 0:
                                                        st.caption("⚠️ `entailment_results` is an empty list. This may be a bug in the validation code.")
                                                    else:
                                                        st.caption(f"✅ Found {len(report.entailment_results)} results, but they're not displaying. This may be a display issue.")
                                        else:
                                            st.warning("⚠️ No statements were validated. This may occur if the explanation is empty.")
                                            
                                            # Debug info
                                            with st.expander("🔍 Debug Info", expanded=False):
                                                st.json({
                                                    "has_explanation": bool(explanation_text),
                                                    "explanation_length": len(explanation_text) if explanation_text else 0,
                                                    "has_reason_codes": bool(reason_codes),
                                                    "reason_codes": reason_codes,
                                                    "statements_validated": report.statements_validated
                                                })
                                    
                                    # Show contradictions if any
                                    if report.contradictions:
                                        st.markdown("#### ❌ Contradictions Detected:")
                                        for c in report.contradictions:
                                            st.error(f"**{c.statement}**")
                                            st.caption(f"Context: {c.context}")
                                            if c.evidence:
                                                with st.expander("Evidence", expanded=False):
                                                    st.json(c.evidence)
                                    
                                    # Store in session for persistence
                                    st.session_state[f"validation_{selected_cluster_id}"] = report.to_dict()
                                    
                                except ImportError:
                                    st.error("❌ TNLI model not installed. Run: `pip install transformers torch`")
                                except Exception as e:
                                    st.error(f"❌ Validation failed: {str(e)}")
                        else:
                            st.caption("💡 Click 'Run Live Validation' to validate the decision explanation.")
                            
                            # Show cached results if available
                            cached = st.session_state.get(f"validation_{selected_cluster_id}")
                            if cached:
                                st.markdown("### 📊 Previous Validation Results")
                                status = cached.get("validation_status", "unknown")
                                if status == "pass":
                                    st.success(f"✅ Validated (Confidence: {cached.get('overall_confidence', 0):.1%})")
                                elif status == "fail":
                                    st.error(f"❌ {len(cached.get('contradictions', []))} Contradictions")
                    else:
                        st.warning("No KPI data available for validation.")
                    
                    st.markdown("---")
                
                st.subheader("📋 Decision Rationale")
                if reason_codes:
                    # Provide human-readable explanations
                    reason_explanations = {
                        "ONLY_DH_FEASIBLE": "Heat Pump grid capacity insufficient",
                        "ONLY_HP_FEASIBLE": "District Heating network not viable",
                        "COST_DOMINANT_DH": "District Heating has significantly lower costs (>5% difference)",
                        "COST_DOMINANT_HP": "Heat Pumps have significantly lower costs (>5% difference)",
                        "COST_CLOSE_USE_CO2": "Costs are close, used CO₂ emissions as tiebreaker",
                        "CO2_TIEBREAKER_DH": "District Heating has lower CO₂ emissions",
                        "CO2_TIEBREAKER_HP": "Heat Pumps have lower CO₂ emissions",
                        "ROBUST_DECISION": "Monte Carlo simulation shows ≥70% win rate",
                        "SENSITIVE_DECISION": "Monte Carlo simulation shows 55-70% win rate",
                        "MC_MISSING": "Monte Carlo robustness data not available",
                        "NONE_FEASIBLE": "Neither option is technically feasible",
                        "INVALID_LCOH_VALUES": "Cost data is missing or invalid"
                    }
                    for code in reason_codes:
                        explanation = reason_explanations.get(code, code)
                        st.markdown(f"- **{code}**: {explanation}")
                else:
                    st.caption("No reason codes provided")
                
                st.markdown("---")
                
                # 5. METRICS SUMMARY
                st.subheader("📊 Key Metrics Compared")
                if metrics:
                    col1, col2 = st.columns(2)
                    with col1:
                        st.metric(
                            "District Heating LCoH", 
                            f"{metrics.get('lcoh_dh_median', 0):.2f} EUR/MWh",
                            help="Levelized Cost of Heat (median)"
                        )
                        st.metric(
                            "DH CO₂ Emissions", 
                            f"{metrics.get('co2_dh_median', 0):.1f} kg/MWh"
                        )
                    with col2:
                        st.metric(
                            "Heat Pump LCoH", 
                            f"{metrics.get('lcoh_hp_median', 0):.2f} EUR/MWh",
                            help="Levelized Cost of Heat (median)"
                        )
                        st.metric(
                            "HP CO₂ Emissions", 
                            f"{metrics.get('co2_hp_median', 0):.1f} kg/MWh"
                        )
                    
                    # Monte Carlo win fractions if available
                    if 'dh_wins_fraction' in metrics or 'hp_wins_fraction' in metrics:
                        st.markdown("**Monte Carlo Win Fractions:**")
                        mccol1, mccol2 = st.columns(2)
                        if 'dh_wins_fraction' in metrics:
                            mccol1.metric("DH Win Rate", f"{metrics['dh_wins_fraction']*100:.1f}%")
                        if 'hp_wins_fraction' in metrics:
                            mccol2.metric("HP Win Rate", f"{metrics['hp_wins_fraction']*100:.1f}%")
                
                # 6. RAW DATA (expandable)
                with st.expander("🔍 View Raw Decision Data (JSON)"):
                    st.json(res)
            else:
                st.error("Decision file found but could not be read.")


    # -- Tab: Portfolio --
    with tab_portfolio:
        st.subheader("Cluster Portfolio Overview")
        if not cluster_index.empty:
            st.markdown("Overview of all street clusters and their status.")
            
            # Prepare portfolio table with status
            portfolio_data = []
            # Use a progress bar if many clusters
            prog_bar = st.progress(0)
            total = len(cluster_index)
            
            for i, (idx, row) in enumerate(cluster_index.iterrows()):
                cid = row["cluster_id"]
                # We can check quick status existence
                res_status = services["result"].get_result_status(cid)
                
                portfolio_data.append({
                    "Cluster": row["cluster_name"],
                    "ID": cid,
                    "Buildings": row["building_count"],
                    "MWh/a": round(row.get("total_annual_heat_demand_kwh_a", 0) / 1000.0, 1),
                    "Result: DH": "✅" if res_status["cha"] else "⬜",
                    "Result: HP": "✅" if res_status["dha"] else "⬜",
                    "Result: Econ": "✅" if res_status["economics"] else "⬜",
                    "Result: Decision": "✅" if res_status["decision"] else "⬜",
                })
                prog_bar.progress((i + 1) / total)
            
            prog_bar.empty()
            pdf = pd.DataFrame(portfolio_data)
            st.dataframe(pdf, use_container_width=True)
            
    # -- Tab: Jobs --
    with tab_jobs:
        st.subheader("Active & Recent Jobs")
        all_jobs = list(services["job"].jobs.values())
        if all_jobs:
            all_jobs.sort(key=lambda x: x["start_time"], reverse=True)
            for job in all_jobs:
                jid = job["id"]
                status_color = "green" if job["status"] == "completed" else "red" if job["status"] in ["failed", "error"] else "blue"
                label = f":{status_color}[{job['status'].upper()}] {job['scenario']} - {job['cluster_id']} ({job['start_time'].strftime('%H:%M:%S')})"
                
                with st.expander(label):
                    st.write(f"Job ID: {jid}")
                    
                    # Show structured error info if available
                    if job["status"] in ["failed", "error"]:
                        err_details = services["job"].get_job_error_details(jid)
                        if err_details:
                            st.error(f"**Error**: {err_details.get('message')}")
                            st.info(f"💡 **Suggestion**: {err_details.get('suggested_fix')}")
                        elif "error" in job:
                            st.error(job["error"])
                            
                    if Path(job["log_file"]).exists():
                        st.text("Log output (last 20 lines):")
                        with open(job["log_file"], "r") as f:
                            lines = f.readlines()
                            st.code("".join(lines[-20:]))

        else:
            st.info("No jobs recorded.")




else:
    st.info("Please select a cluster from the sidebar to begin.")
