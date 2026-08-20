import streamlit as st
from google.cloud import firestore
import time
import pandas as pd

st.set_page_config(page_title="Helix Street | Fleet Command", layout="wide", page_icon="🧬")

# Custom CSS for better styling
st.markdown("""
<style>
    .stApp {
        background-color: #f8f9fa;
    }
    .main-header {
        color: #1E3A8A;
        font-family: 'Helvetica Neue', sans-serif;
    }
    .metric-card {
        background-color: white;
        padding: 20px;
        border-radius: 10px;
        box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
        margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

st.markdown('<h1 class="main-header">🧬 Helix Street: Autonomous Digital Twin</h1>', unsafe_allow_html=True)

@st.cache_resource
def get_db():
    return firestore.Client(project="helixstreet-agent")

db = get_db()

# Sidebar for navigation and controls
with st.sidebar:
    st.header("Control Panel")
    refresh_rate = st.slider("Auto-refresh rate (seconds)", min_value=1, max_value=10, value=3)
    auto_refresh = st.checkbox("Enable Auto-refresh", value=True)
    st.divider()
    st.subheader("Simulate Agent Action")
    test_user_id = st.text_input("User ID", value="user_777")
    if st.button("Trigger Mock Upload"):
        st.info(f"Simulated GCS upload for {test_user_id}. Agent should process in background.")

# Main layout
col1, col2 = st.columns([1, 2])

with col1:
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("Enterprise Drop-Zone")
    st.info("Upload VCF/PDF to Google Cloud Storage to trigger background agent.")
    st.markdown("*(Listening to Eventarc webhook...)*")
    st.markdown('</div>', unsafe_allow_html=True)
    
    st.markdown('<div class="metric-card">', unsafe_allow_html=True)
    st.subheader("Fleet Status")
    st.metric(label="Active Agents", value="1 (Antigravity)")
    st.metric(label="System Load", value="Nominal")
    st.markdown('</div>', unsafe_allow_html=True)

with col2:
    st.subheader("Persistent Memory Bank (Live View)")
    
    # Fetch all digital twins
    twins_ref = db.collection("digital_twins")
    docs = twins_ref.stream()
    
    twins_data = []
    for doc in docs:
        data = doc.to_dict()
        data['id'] = doc.id
        # Format timestamp if present
        if 'last_updated' in data and data['last_updated']:
            try:
                data['last_updated'] = data['last_updated'].strftime("%Y-%m-%d %H:%M:%S")
            except:
                pass
        twins_data.append(data)
        
    if twins_data:
        st.success(f"✅ Found {len(twins_data)} Digital Twins in Memory Bank")
        
        # Display as a dataframe for better overview
        df = pd.DataFrame(twins_data)
        st.dataframe(df, use_container_width=True)
        
        # Details expander
        st.subheader("Twin Details")
        selected_twin = st.selectbox("Select User ID to view details:", [t['id'] for t in twins_data])
        
        if selected_twin:
            twin_details = next((t for t in twins_data if t['id'] == selected_twin), None)
            if twin_details:
                st.json(twin_details)
    else:
        st.warning("No digital twins found in the database. Awaiting agent execution...")
        st.info(f"Waiting for agent to process data for user_777 or others...")

if auto_refresh:
    time.sleep(refresh_rate)
    st.rerun()
