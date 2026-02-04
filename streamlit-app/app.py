"""
Cialona Trade Fair Discovery - Main Dashboard
"""

import streamlit as st
from pathlib import Path
import data_manager as dm
from config import (
    CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, CIALONA_WHITE,
    DOCUMENT_TYPES, APP_TITLE, APP_ICON, get_status_html, get_doc_chip_html
)

# Page configuration
st.set_page_config(
    page_title=f"{APP_TITLE} | Cialona",
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Sidebar with logo and navigation
with st.sidebar:
    # Logo
    logo_path = Path(__file__).parent / "assets" / "logo.png"
    if logo_path.exists():
        st.image(str(logo_path), width=200)
    else:
        st.markdown(f"""
        <div style="text-align: center; padding: 1rem;">
            <h2 style="color: {CIALONA_ORANGE}; margin: 0;">CIALONA</h2>
            <p style="color: white; font-size: 0.8rem; margin: 0;">Eye for Attention</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Quick actions
    st.markdown("### ⚡ Snelle Acties")
    if st.button("🔍 Nieuwe Discovery", use_container_width=True):
        st.switch_page("pages/1_Discovery.py")

    if st.button("📧 Email Generator", use_container_width=True):
        st.switch_page("pages/3_Email_Generator.py")

    st.markdown("---")

    # Demo data loader
    st.markdown("### 🧪 Demo")
    if st.button("Laad Demo Data", use_container_width=True):
        dm.load_demo_data()
        st.success("Demo data geladen!")
        st.rerun()

# Main content area
# Header
st.markdown(f"""
<div class="main-header">
    <h1>{APP_ICON} Trade Fair Discovery</h1>
    <p class="tagline">Automatisch exhibitor documenten vinden voor standbouw projecten</p>
</div>
""", unsafe_allow_html=True)

# Load data
summary = dm.get_fairs_summary()
fairs = dm.get_fairs_for_display()

# Metrics row
col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{summary['total_fairs']}</div>
        <div class="metric-label">Totaal Beurzen</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="color: #10B981;">{summary['complete']}</div>
        <div class="metric-label">Compleet</div>
    </div>
    """, unsafe_allow_html=True)

with col3:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value" style="color: #F59E0B;">{summary['partial']}</div>
        <div class="metric-label">Deels Compleet</div>
    </div>
    """, unsafe_allow_html=True)

with col4:
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{summary['doc_percentage']}%</div>
        <div class="metric-label">Document Dekking</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<br>", unsafe_allow_html=True)

# Fairs section
st.markdown("## 📋 Beurzen Overzicht")

# Filter options
col_filter1, col_filter2, col_filter3 = st.columns([2, 2, 4])
with col_filter1:
    status_filter = st.selectbox(
        "Status",
        ["Alle", "Compleet", "Deels Compleet", "Ontbrekend"],
        label_visibility="collapsed"
    )

with col_filter2:
    search_query = st.text_input("🔍 Zoeken...", label_visibility="collapsed", placeholder="Zoek beurs...")

# Apply filters
filtered_fairs = fairs
if status_filter == "Compleet":
    filtered_fairs = [f for f in fairs if f['status'] == 'complete']
elif status_filter == "Deels Compleet":
    filtered_fairs = [f for f in fairs if f['status'] == 'partial']
elif status_filter == "Ontbrekend":
    filtered_fairs = [f for f in fairs if f['status'] == 'missing']

if search_query:
    filtered_fairs = [f for f in filtered_fairs if search_query.lower() in f['name'].lower()]

# Display fairs
if not filtered_fairs:
    st.info("👋 Nog geen beurzen gevonden. Klik op 'Nieuwe Discovery' om te beginnen!")
else:
    for fair in filtered_fairs:
        completeness = fair.get('completeness', {})
        doc_status = fair.get('doc_status', {})

        # Card container
        with st.container():
            col_main, col_actions = st.columns([4, 1])

            with col_main:
                # Fair name and status
                status_class = {
                    'complete': 'status-complete',
                    'partial': 'status-partial',
                    'missing': 'status-missing'
                }.get(fair['status'], 'status-missing')

                status_text = {
                    'complete': f"✓ Compleet ({completeness.get('found', 0)}/{completeness.get('total', 5)})",
                    'partial': f"⚠ Deels ({completeness.get('found', 0)}/{completeness.get('total', 5)})",
                    'missing': f"✗ Ontbreekt ({completeness.get('found', 0)}/{completeness.get('total', 5)})"
                }.get(fair['status'], 'Onbekend')

                st.markdown(f"""
                <div class="fair-card">
                    <div class="fair-card-header">
                        <h3 class="fair-card-title">{fair['name']}</h3>
                        <span class="status-badge {status_class}">{status_text}</span>
                    </div>
                    <div style="color: #6B7280; font-size: 0.9rem; margin-bottom: 0.75rem;">
                        {fair.get('city', '')} {', ' + fair.get('country', '') if fair.get('country') else ''}
                        {' • ' + fair.get('url', '') if fair.get('url') else ''}
                    </div>
                    <div>
                        {''.join([get_doc_chip_html(doc_type, doc_status.get(doc_type, False)) for doc_type in DOCUMENT_TYPES.keys()])}
                    </div>
                </div>
                """, unsafe_allow_html=True)

            with col_actions:
                st.markdown("<br>", unsafe_allow_html=True)
                if st.button("📄 Details", key=f"detail_{fair['id']}", use_container_width=True):
                    st.session_state['selected_fair'] = fair['id']
                    st.switch_page("pages/2_Fair_Details.py")

                if fair['status'] != 'complete':
                    if st.button("📧 Email", key=f"email_{fair['id']}", use_container_width=True):
                        st.session_state['selected_fair'] = fair['id']
                        st.switch_page("pages/3_Email_Generator.py")

        st.markdown("<br>", unsafe_allow_html=True)

# Footer
st.markdown("---")
st.markdown(f"""
<div style="text-align: center; color: #6B7280; padding: 1rem;">
    <small>Cialona Trade Fair Discovery • Powered by Claude AI</small>
</div>
""", unsafe_allow_html=True)
