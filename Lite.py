import streamlit as st
import folium
import googlemaps
import os
import polyline
import datetime
from dotenv import load_dotenv
from streamlit_folium import st_folium
from fleet_optimizer import solve_vrp
from functools import lru_cache

# --- CONFIGURATION ---
st.set_page_config(page_title="FleetRoute Lite", page_icon="🚚", layout="wide")

# --- HEADER: Logo + Title + Beta Tag ---
col1, col2 = st.columns([1, 6])
with col1:
    st.image("assets/fleetroute_logo.png", width=70)
with col2:
    st.markdown("""
    <div style='display: flex; align-items: center; justify-content: space-between;'>
        <h1 style='margin-bottom: 0;'>🚛 FleetRoute Lite</h1>
        <span style='background-color:#1f77b4; color:white; padding:4px 12px; border-radius:6px;'>BETA</span>
    </div>
    """, unsafe_allow_html=True)

# --- Welcome Alert ---
st.info(
    "🚧 FleetRoute Lite is currently in **BETA**. You may encounter bugs or limitations. "
    "I welcome your feedback at 📩 [cyrus738@gmail.com](mailto:cyrus738@gmail.com).",
    icon="🧪"
)

# --- User Guide ---
with st.expander("📘 How to Use FleetRoute Lite (User Guide)", expanded=True):
    st.markdown("""
    1. **Set the number of vehicles** and **depot address** in the sidebar.
    2. For each vehicle:
       - Enter the **driver's name**
       - Add **delivery stop labels** and **addresses**
    3. Click **Optimize Now** to generate the most efficient route.
    4. View your route map and download a route summary.

    ⚠️ This version doesn’t support time windows or cost analysis. Try **FleetRoute Pro** for advanced features.
    """)

# --- Load Google Maps API ---
load_dotenv()
API_KEY = os.getenv("GOOGLE_API_KEY")
if not API_KEY:
    st.error("❌ GOOGLE_API_KEY not found. Please check your .env file.")
    st.stop()
gmaps = googlemaps.Client(key=API_KEY)

# --- Helpers ---
@lru_cache(maxsize=100)
def geocode_address(address):
    try:
        if not address or not isinstance(address, str) or address.strip() == "":
            return None
        result = gmaps.geocode(address)
        if result:
            loc = result[0]['geometry']['location']
            return (loc['lat'], loc['lng'])
    except Exception as e:
        st.warning(f"⚠️ Geocoding error for '{address}': {e}")
    return None

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
    except Exception as e:
        st.error(f"Directions API error: {e}")
    return None

# --- Sidebar Settings ---
st.sidebar.header("⚙️ Fleet Settings")
num_vehicles = st.sidebar.slider("Number of Vehicles", 1, 10, 2)
return_to_depot = st.sidebar.checkbox("Return to Depot After Route", value=True)
depot_address = st.sidebar.text_input("Depot Address", value="100 W Pender St, Vancouver, BC")

# --- Reset or Load Sample ---
if st.sidebar.button("🔄 Reset All"):
    for v in range(1, num_vehicles + 1):
        st.session_state[f"vehicle_{v}_stops"] = []
    st.session_state.route_paths = []
    st.session_state.route_addresses = []
    st.session_state.route_stats = []
    st.rerun()

if st.sidebar.button("🧪 Load Sample Data"):
    st.session_state["vehicle_1_stops"] = [("Stop 1", "BCIT Burnaby"), ("Stop 2", "Metrotown")]
    st.session_state["vehicle_2_stops"] = [("Stop 1", "Stanley Park"), ("Stop 2", "UBC Vancouver")]
    st.session_state["driver_name_1"] = "Alice"
    st.session_state["driver_name_2"] = "Bob"
    st.rerun()

# --- Geocode Depot ---
depot_coords = geocode_address(depot_address)
if not depot_coords:
    st.stop()

# --- Session Initialization ---
for v in range(1, num_vehicles + 1):
    st.session_state.setdefault(f"vehicle_{v}_stops", [])

# --- Step 1: Enter Stops ---
st.subheader("📍 Step 1: Enter Delivery Stops")
for v in range(1, num_vehicles + 1):
    with st.expander(f"🚐 Vehicle {v}"):
        driver_name = st.text_input(f"👤 Driver Name", key=f"driver_name_{v}")
        stops = st.session_state[f"vehicle_{v}_stops"]

        for i, (label, address) in enumerate(stops):
            col1, col2 = st.columns([1, 3])
            with col1:
                label = st.text_input(f"Label V{v}-{i+1}", value=label, key=f"label_{v}_{i}")
            with col2:
                address = st.text_input(f"Address V{v}-{i+1}", value=address, key=f"addr_{v}_{i}")
            stops[i] = (label, address)

        col_add, col_remove = st.columns(2)
        with col_add:
            if st.button(f"➕ Add Stop to Vehicle {v}", key=f"add_{v}"):
                stops.append((f"Stop {len(stops) + 1}", ""))
        with col_remove:
            if st.button(f"➖ Remove Last Stop from Vehicle {v}", key=f"remove_{v}") and stops:
                stops.pop()

        st.session_state[f"vehicle_{v}_stops"] = stops

# --- Step 2: Optimize ---
st.markdown("---")
st.subheader("🧫 Step 2: Optimize Routes")
if st.button("🚀 Optimize Now"):
    st.session_state.route_paths = []
    st.session_state.route_addresses = []
    st.session_state.route_stats = []

    for v in range(1, num_vehicles + 1):
        stops = st.session_state[f"vehicle_{v}_stops"]
        address_list = [depot_address] + [addr for _, addr in stops if addr.strip()]
        label_list = ["Depot"] + [lbl for lbl, addr in stops if addr.strip()]

        if len(address_list) < 2:
            st.session_state.route_paths.append([])
            st.session_state.route_addresses.append([])
            st.session_state.route_stats.append({"distance": 0, "time": 0, "score": "⚠️ Underused"})
            continue

        coords = [geocode_address(addr) for addr in address_list]
        dist_matrix = [[0 if i == j else ((coords[i][0] - coords[j][0])**2 + (coords[i][1] - coords[j][1])**2)**0.5 * 111
                        for j in range(len(coords))] for i in range(len(coords))]

        routes = solve_vrp(dist_matrix, 1)
        if routes:
            path = routes[0]
            total_dist = sum(dist_matrix[path[i]][path[i+1]] for i in range(len(path)-1))
            est_time = round(total_dist / 40 * 60, 1)
            n_stops = len(path) - 2 if return_to_depot else len(path) - 1

            score = "🕦 Light" if n_stops <= 2 else "🟡 Medium" if n_stops <= 4 else "🔴 Heavy"

            st.session_state.route_paths.append([label_list[i] for i in path])
            st.session_state.route_addresses.append([address_list[i] for i in path])
            st.session_state.route_stats.append({
                "distance": round(total_dist, 2),
                "time": est_time,
                "score": score
            })
        else:
            st.session_state.route_paths.append([])
            st.session_state.route_addresses.append([])
            st.session_state.route_stats.append({"distance": 0, "time": 0, "score": "❌ No route"})

    st.success("✅ Routes optimized!")

# --- Step 3: Dashboard ---
if "route_paths" in st.session_state and len(st.session_state.route_paths) == num_vehicles:
    st.markdown("---")
    st.subheader("📊 Step 3: Route Overview")

    col_map, col_info = st.columns([2, 1])
    summary_text = f"Fleet Summary - {datetime.date.today()}\n\n"
    colors = ['blue', 'green', 'red', 'purple', 'orange', 'darkred', 'cadetblue', 'darkgreen', 'black', 'pink']

    with col_map:
        m = folium.Map(location=depot_coords, zoom_start=12)
        for v in range(1, num_vehicles + 1):
            labels = st.session_state.route_paths[v-1]
            addresses = st.session_state.route_addresses[v-1]
            driver = st.session_state.get(f"driver_name_{v}", f"Vehicle {v}")

            if not addresses:
                continue

            coords = [geocode_address(addr) for addr in addresses]
            route_poly = get_route_polyline(addresses)
            color = colors[(v - 1) % len(colors)]
            if route_poly:
                folium.PolyLine(route_poly, color=color, tooltip=driver, weight=5).add_to(m)

            for label, coord in zip(labels, coords):
                if coord:
                    folium.CircleMarker(
                        location=coord,
                        radius=5,
                        popup=label,
                        color=color,
                        fill=True,
                        fill_opacity=0.8
                    ).add_to(m)

        st_folium(m, height=500, width=900)

    with col_info:
        for v in range(1, num_vehicles + 1):
            labels = st.session_state.route_paths[v-1]
            stats = st.session_state.route_stats[v-1]
            driver = st.session_state.get(f"driver_name_{v}", f"Vehicle {v}")

            if not labels:
                st.warning(f"⚠️ {driver} has no route.")
                continue

            st.markdown(f"### 🚐 {driver}")
            st.code(" → ".join(labels))
            colA, colB, colC = st.columns(3)
            colA.metric("Distance (km)", stats["distance"])
            colB.metric("Duration (min)", stats["time"])
            colC.markdown(f"**Load:** {stats['score']}")

            summary_text += f"Driver: {driver}\nRoute: {' → '.join(labels)}\n"
            summary_text += f"Distance: {stats['distance']} km\nTime: {stats['time']} min\nLoad: {stats['score']}\n\n"

    st.download_button(
        label="📄 Download Fleet Summary",
        data=summary_text,
        file_name=f"fleet_summary_{datetime.date.today()}.txt",
        mime="text/plain"
    )

# --- Footer ---
st.markdown("---")
st.caption(f"© 2025 FleetRoute • Built with ❤️ by Cyrus Chu • Contact: cyrus738@gmail.com")
