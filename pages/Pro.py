import streamlit as st
import folium
import googlemaps
import os
import random
import polyline
from dotenv import load_dotenv
from streamlit_folium import st_folium
from datetime import datetime, timedelta
from fleet_optimizer import solve_vrp

# --- CONFIG ---
st.set_page_config(page_title="FleetRoute Pro", page_icon="🚛", layout="wide")

load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    st.error("❌ GOOGLE_API_KEY not found in your .env file.")
    st.stop()

gmaps = googlemaps.Client(key=API_KEY)

# --- HELPERS ---
def geocode(address):
    try:
        result = gmaps.geocode(address)
        if result:
            return result[0]['geometry']['location']
    except:
        return None

def get_distance_matrix(addresses):
    matrix = gmaps.distance_matrix(addresses, addresses, mode="driving")
    return [[e['distance']['value'] / 1000 for e in row['elements']] for row in matrix['rows']]

def get_route_polyline(addresses):
    try:
        result = gmaps.directions(
            origin=addresses[0],
            destination=addresses[-1],
            waypoints=addresses[1:-1] if len(addresses) > 2 else None,
            mode="driving"
        )
        if result:
            return polyline.decode(result[0]['overview_polyline']['points'])
    except:
        return None

# --- HEADER ---
col_logo, col_title, col_tag = st.columns([1, 6, 1])
with col_logo:
    st.image("assets/fleetroute_logo.png", width=75)
with col_title:
    st.title("🚛 FleetRoute Pro")
with col_tag:
    st.markdown("### 🧪 PRO")

# --- Welcome Alert ---
st.info(
    "🚧 FleetRoute Lite is currently in **BETA**. You may encounter bugs or limitations. "
    "I welcome your feedback at 📩 [cyrus738@gmail.com](mailto:cyrus738@gmail.com).",
    icon="🧪"
)

# --- User Guide ---
with st.expander("📘 How to Use FleetRoute Pro (User Guide)", expanded=True):
    st.markdown("""
    1. **Enter the number of routes** and the **depot address** in the sidebar.
    2. Input **driver names** and **delivery stop details** (address, time window, load).
    3. Click **➕ Add New Route** to create a route and start adding stops.
    4. Once all stops are added, click **🚀 Optimize Now** to calculate the best routes.
    5. View the optimized map and metrics below.
    6. Use the **Download Summary** button to save results.

    🛠 *Advanced features like fuel cost estimation and route visualization are included.*

    ⚠️ This version is still in **BETA**. If you spot any bugs or have ideas, contact me at 📩 [cyrus738@gmail.com](mailto:cyrus738@gmail.com).
    """)

# --- SIDEBAR ---
st.sidebar.header("⚙️ Fleet Settings")
num_vehicles = st.sidebar.slider("Number of Routes", 1, 10, 2)
depot_address = st.sidebar.text_input("Depot Address", "100 W Pender St, Vancouver, BC")
return_to_depot = st.sidebar.checkbox("Return to Depot", True)
fuel_cost = st.sidebar.number_input("Fuel Cost per km ($)", min_value=0.0, value=0.25, step=0.01)
drivers = [st.sidebar.text_input(f"Driver {i+1} Name", key=f"driver_{i}") for i in range(num_vehicles)]

# --- SAMPLE DATA LOADING ---
if st.sidebar.button("🧪 Load Sample Data"):
    st.session_state.routes = {
        "Route 1": [
            {"address": "BCIT Burnaby", "time": "9:00–11:00", "load": 12, "driver": drivers[0] if drivers else ""},
            {"address": "Metrotown", "time": "11:00–13:00", "load": 8, "driver": drivers[0] if drivers else ""}
        ],
        "Route 2": [
            {"address": "Stanley Park", "time": "9:00–11:00", "load": 6, "driver": drivers[1] if len(drivers) > 1 else ""},
            {"address": "UBC Vancouver", "time": "11:00–13:00", "load": 9, "driver": drivers[1] if len(drivers) > 1 else ""}
        ]
    }
    st.rerun()

# --- STATE INIT ---
if "routes" not in st.session_state:
    st.session_state.routes = {}
if "optimized_map" not in st.session_state:
    st.session_state.optimized_map = None
if "metrics" not in st.session_state:
    st.session_state.metrics = {}

# --- MAIN CONTENT ---
st.markdown("### 📍 Step 1: Add Delivery Stops")

if st.button("➕ Add New Route"):
    new_id = len(st.session_state.routes) + 1
    st.session_state.routes[f"Route {new_id}"] = [{
        "address": "",
        "time": "9:00–11:00",
        "load": 10,
        "driver": drivers[0] if drivers else ""
    }]
    st.rerun()

remove_index = None
for route, stops in st.session_state.routes.items():
    st.subheader(f"🚦 {route}")
    for i, stop in enumerate(stops):
        with st.expander(f"{route} – Stop {i+1}", expanded=True):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                stop["address"] = st.text_input("📍 Address", stop["address"], key=f"addr_{route}_{i}")
            with c2:
                stop["time"] = st.text_input("🕒 Time Window", stop["time"], key=f"time_{route}_{i}")
            with c3:
                stop["load"] = st.number_input("📦 Load (kg)", 0, 9999, stop["load"], key=f"load_{route}_{i}")

            stop["driver"] = st.selectbox(
                "🚚 Driver", drivers,
                index=drivers.index(stop["driver"]) if stop["driver"] in drivers else 0,
                key=f"drv_{route}_{i}"
            )

            col_a, col_b = st.columns(2)
            with col_a:
                if st.button("➕ Add Stop Below", key=f"add_{route}_{i}"):
                    st.session_state.routes[route].insert(i + 1, {
                        "address": "",
                        "time": "9:00–11:00",
                        "load": 10,
                        "driver": drivers[0] if drivers else ""
                    })
                    st.rerun()
            with col_b:
                if st.button("➖ Remove Stop", key=f"rm_{route}_{i}"):
                    remove_index = (route, i)

if remove_index:
    r, idx = remove_index
    st.session_state.routes[r].pop(idx)
    st.rerun()

# --- OPTIMIZE ---
st.markdown("### 🧠 Step 2: Optimize Routes")
summary_text = f"Fleet Summary - {datetime.today().date()}\n\n"
if st.button("🚀 Optimize Now"):
    depot_coords = geocode(depot_address)
    if not depot_coords:
        st.error("❌ Could not geocode depot address.")
        st.stop()

    fmap = folium.Map(location=(depot_coords["lat"], depot_coords["lng"]), zoom_start=12)
    st.session_state.metrics = {}

    for route, stops in st.session_state.routes.items():
        addresses = [depot_address] + [s["address"] for s in stops if s["address"].strip()]
        if len(addresses) < 2:
            continue

        matrix = get_distance_matrix(addresses)
        try:
            indices = solve_vrp(matrix, 1)[0]
        except:
            st.warning(f"⚠️ Optimization failed for {route}")
            continue

        ordered = [addresses[i] for i in indices]
        route_poly = get_route_polyline(ordered)
        coords = [geocode(addr) for addr in ordered]

        if route_poly:
            folium.PolyLine(route_poly, color=random.choice(["blue", "green", "red", "purple"]), weight=5, tooltip=route).add_to(fmap)

        for addr, c in zip(ordered, coords):
            if c:
                folium.Marker([c["lat"], c["lng"]], popup=addr).add_to(fmap)

        dist_km = sum(matrix[indices[i]][indices[i+1]] for i in range(len(indices)-1))
        cost = round(dist_km * fuel_cost, 2)
        duration_min = round(dist_km / 40 * 60, 1)

        st.session_state.metrics[route] = {
            "path": ordered,
            "distance": round(dist_km, 2),
            "cost": cost,
            "duration": duration_min
        }

        summary_text += f"Route: {route}\n"
        summary_text += f"Path: {' → '.join(ordered)}\n"
        summary_text += f"Distance: {round(dist_km,2)} km\nCost: ${cost:.2f}\nTotal Duration: {duration_min} min\n\n"

    st.session_state.optimized_map = fmap
    st.session_state.summary_text = summary_text
    st.success("✅ Optimization complete!")

# --- RESULT MAP ---
if st.session_state.optimized_map:
    st.markdown("### 🗺 Optimized Route Overview")
    st_folium(st.session_state.optimized_map, height=500)

    for route, data in st.session_state.metrics.items():
        st.markdown(f"#### 📦 {route}")
        st.code(" → ".join(data["path"]))
        col1, col2, col3 = st.columns(3)
        col1.metric("Distance (km)", data["distance"])
        col2.metric("Fuel Cost", f"${data['cost']:.2f}")
        col3.metric("Duration (min)", f"{data['duration']}")

    st.download_button(
        label="📄 Download Summary (TXT)",
        data=st.session_state.summary_text,
        file_name=f"fleet_summary_{datetime.today().date()}.txt",
        mime="text/plain"
    )

# --- RESET BUTTON ---
if st.button("🔄 Reset All Routes"):
    st.session_state.routes = {}
    st.session_state.optimized_map = None
    st.session_state.metrics = {}
    st.session_state.summary_text = ""
    st.rerun()

# --- FOOTER ---
st.markdown("---")
st.caption(f"© 2025 FleetRoute • Built with ❤️ by Cyrus Chu • Contact: cyrus738@gmail.com")