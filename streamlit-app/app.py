"""
Cialona Trade Fair Discovery - Main Dashboard
"""

import streamlit as st
from pathlib import Path
import data_manager as dm
from config import (
    CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, CIALONA_WHITE,
    DOCUMENT_TYPES, APP_TITLE, APP_ICON, ADMIN_PIN,
    get_status_html, get_doc_chip_html
)

ASSETS_DIR = Path(__file__).parent / "assets"
LOGO_PATH = ASSETS_DIR / "logo.png"

# Page configuration
st.set_page_config(
    page_title=f"{APP_TITLE} | Cialona",
    page_icon=APP_ICON,
    layout="wide",
    initial_sidebar_state="expanded"
)

# Inject custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ── Sidebar ──────────────────────────────────────────────────────────────
with st.sidebar:
    # Logo or fallback text
    if LOGO_PATH.exists():
        st.image(str(LOGO_PATH), width=200)
    else:
        st.markdown(f"""
        <div style="text-align: center; padding: 1rem;">
            <h2 style="color: {CIALONA_ORANGE}; margin: 0;">CIALONA</h2>
            <p style="color: white; font-size: 0.8rem; margin: 0;">Eye for Attention</p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("---")

    # Navigation
    if st.button("🔍 Nieuwe Discovery", use_container_width=True):
        st.switch_page("pages/1_Discovery.py")

    if st.button("📧 Email Generator", use_container_width=True):
        st.switch_page("pages/3_Email_Generator.py")

    # Admin: logo upload (pin-protected)
    st.markdown("---")
    st.markdown(f"""
    <p style="color: rgba(255,255,255,0.5); font-size: 0.75rem; text-align: center; margin: 0;">
        Instellingen
    </p>
    """, unsafe_allow_html=True)

    if 'admin_unlocked' not in st.session_state:
        st.session_state.admin_unlocked = False

    if not st.session_state.admin_unlocked:
        pin = st.text_input("PIN", type="password", key="admin_pin",
                            label_visibility="collapsed", placeholder="Admin PIN...")
        if pin and pin == ADMIN_PIN:
            st.session_state.admin_unlocked = True
            st.rerun()
        elif pin:
            st.error("Onjuiste PIN")
    else:
        st.markdown(f"""
        <div style="background: rgba(16,185,129,0.15); border: 1px solid rgba(16,185,129,0.4);
                    border-radius: 8px; padding: 0.5rem; text-align: center; margin-bottom: 0.75rem;">
            <span style="color: #10B981; font-size: 0.85rem;">Admin modus actief</span>
        </div>
        """, unsafe_allow_html=True)
        uploaded_logo = st.file_uploader(
            "Upload logo (PNG)", type=["png"], key="logo_upload"
        )
        if uploaded_logo is not None:
            # Only save if file is new (avoid re-saving on every rerun)
            logo_bytes = uploaded_logo.getvalue()
            existing = LOGO_PATH.read_bytes() if LOGO_PATH.exists() else b""
            if logo_bytes != existing:
                ASSETS_DIR.mkdir(parents=True, exist_ok=True)
                LOGO_PATH.write_bytes(logo_bytes)
                st.success("Logo opgeslagen!")
                st.rerun()
            else:
                st.success("Logo actief")

        if LOGO_PATH.exists():
            if st.button("Verwijder logo", use_container_width=True):
                LOGO_PATH.unlink()
                st.rerun()

        if st.button("Vergrendel", use_container_width=True):
            st.session_state.admin_unlocked = False
            st.rerun()

# ── Main Content ─────────────────────────────────────────────────────────

# Load data
summary = dm.get_fairs_summary()
fairs = dm.get_fairs_for_display()
has_fairs = summary['total_fairs'] > 0

# Header — compact
st.markdown(f"""
<div class="main-header">
    <h1>{APP_ICON} Trade Fair Discovery</h1>
    <p class="tagline">Automatisch exhibitor documenten vinden voor standbouw projecten</p>
</div>
""", unsafe_allow_html=True)

# ── Empty state: welcoming onboarding ────────────────────────────────────
if not has_fairs:
    st.markdown("<br>", unsafe_allow_html=True)

    col_welcome, _ = st.columns([3, 1])
    with col_welcome:
        st.markdown(f"""
        <div style="background: {CIALONA_WHITE}; border: 2px dashed #CBD5E1; border-radius: 16px;
                    padding: 3rem; text-align: center;">
            <div style="font-size: 3rem; margin-bottom: 1rem;">🔍</div>
            <h2 style="color: {CIALONA_NAVY}; margin: 0 0 0.5rem 0;">Welkom bij Trade Fair Discovery</h2>
            <p style="color: #6B7280; font-size: 1.05rem; max-width: 500px; margin: 0 auto 1.5rem auto;">
                Vind automatisch plattegronden, handleidingen, technische richtlijnen en opbouwschema's
                voor elke beurs.
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    # Quick-start steps
    col_s1, col_s2, col_s3 = st.columns(3)
    with col_s1:
        st.markdown(f"""
        <div style="background: white; border-radius: 12px; padding: 1.5rem; text-align: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #E5E7EB; height: 180px;">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">1️⃣</div>
            <h4 style="color: {CIALONA_NAVY}; margin: 0 0 0.5rem 0;">Start een Discovery</h4>
            <p style="color: #6B7280; font-size: 0.9rem; margin: 0;">
                Voer de naam en website van de beurs in
            </p>
        </div>
        """, unsafe_allow_html=True)
    with col_s2:
        st.markdown(f"""
        <div style="background: white; border-radius: 12px; padding: 1.5rem; text-align: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #E5E7EB; height: 180px;">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">2️⃣</div>
            <h4 style="color: {CIALONA_NAVY}; margin: 0 0 0.5rem 0;">AI zoekt documenten</h4>
            <p style="color: #6B7280; font-size: 0.9rem; margin: 0;">
                De agent doorzoekt de website en vindt alle relevante PDFs
            </p>
        </div>
        """, unsafe_allow_html=True)
    with col_s3:
        st.markdown(f"""
        <div style="background: white; border-radius: 12px; padding: 1.5rem; text-align: center;
                    box-shadow: 0 2px 8px rgba(0,0,0,0.06); border: 1px solid #E5E7EB; height: 180px;">
            <div style="font-size: 2rem; margin-bottom: 0.5rem;">3️⃣</div>
            <h4 style="color: {CIALONA_NAVY}; margin: 0 0 0.5rem 0;">Resultaten & Email</h4>
            <p style="color: #6B7280; font-size: 0.9rem; margin: 0;">
                Bekijk wat gevonden is en mail de organisatie voor het ontbrekende
            </p>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)

    if st.button("🔍 Start je eerste Discovery", use_container_width=True, key="onboard_discovery"):
        st.switch_page("pages/1_Discovery.py")

# ── Dashboard with data ──────────────────────────────────────────────────
else:
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
        search_query = st.text_input(
            "Zoeken", label_visibility="collapsed", placeholder="Zoek beurs..."
        )

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
        st.info("Geen beurzen gevonden voor dit filter.")
    else:
        for fair in filtered_fairs:
            completeness = fair.get('completeness', {})
            doc_status = fair.get('doc_status', {})

            with st.container():
                col_main, col_actions = st.columns([4, 1])

                with col_main:
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
    <small>Cialona Trade Fair Discovery</small>
</div>
""", unsafe_allow_html=True)
