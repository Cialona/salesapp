"""
Cialona Trade Fair Discovery - Fair Details Page
View detailed information about a specific fair.
"""

import streamlit as st
from pathlib import Path
import sys
from datetime import datetime

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import data_manager as dm
from config import (
    CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, APP_ICON,
    DOCUMENT_TYPES, get_doc_chip_html
)

# Page configuration
st.set_page_config(
    page_title="Beurs Details | Cialona",
    page_icon=APP_ICON,
    layout="wide"
)

# Inject custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# Sidebar
with st.sidebar:
    st.markdown(f"""
    <div style="text-align: center; padding: 1rem;">
        <h2 style="color: {CIALONA_ORANGE}; margin: 0;">CIALONA</h2>
        <p style="color: white; font-size: 0.8rem; margin: 0;">Eye for Attention</p>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("---")

    if st.button("🏠 Dashboard", use_container_width=True):
        st.switch_page("app.py")

    if st.button("🔍 Nieuwe Discovery", use_container_width=True):
        st.switch_page("pages/1_Discovery.py")

# Get selected fair
fair_id = st.session_state.get('selected_fair')

# If no fair selected, show selector
if not fair_id:
    st.markdown("### Selecteer een beurs")

    fairs = dm.get_fairs_for_display()
    if fairs:
        options = {f['name']: f['id'] for f in fairs}
        selected_name = st.selectbox("Beurs", list(options.keys()))
        if selected_name:
            fair_id = options[selected_name]
            st.session_state['selected_fair'] = fair_id
    else:
        st.info("Nog geen beurzen beschikbaar. Start eerst een discovery.")
        st.stop()

# Load fair data
fair = dm.get_fair(fair_id)

if not fair:
    st.error(f"Beurs niet gevonden: {fair_id}")
    st.stop()

# Header with fair info
completeness = fair.get('completeness', {})
status_color = {
    'complete': '#10B981',
    'partial': '#F59E0B',
    'missing': '#EF4444'
}.get(fair.get('status'), '#6B7280')

st.markdown(f"""
<div class="main-header">
    <h1>{fair.get('name', 'Onbekende Beurs')}</h1>
    <p class="tagline">
        {fair.get('city', '')} {', ' + fair.get('country', '') if fair.get('country') else ''} •
        <span style="color: {status_color};">
            {completeness.get('found', 0)}/{completeness.get('total', 5)} documenten gevonden
        </span>
    </p>
</div>
""", unsafe_allow_html=True)

# Quick actions
col_act1, col_act2, col_act3, col_act4 = st.columns(4)
with col_act1:
    if fair.get('official_url'):
        st.link_button("🌐 Website", fair['official_url'], use_container_width=True)
with col_act2:
    if fair.get('documents', {}).get('downloads_overview_url'):
        st.link_button("📥 Downloads", fair['documents']['downloads_overview_url'], use_container_width=True)
with col_act3:
    if fair.get('status') != 'complete':
        if st.button("📧 Email Sturen", use_container_width=True):
            st.session_state['selected_fair'] = fair_id
            st.switch_page("pages/3_Email_Generator.py")
with col_act4:
    if st.button("🔄 Opnieuw Scannen", use_container_width=True):
        st.session_state['rescan_fair'] = fair_id
        st.switch_page("pages/1_Discovery.py")

st.markdown("<br>", unsafe_allow_html=True)

# Main content tabs
tab_docs, tab_schedule, tab_raw = st.tabs(["📄 Documenten", "📅 Schema", "🔧 Raw Data"])

with tab_docs:
    st.markdown("### Gevonden Documenten")

    docs = fair.get('documents', {})
    doc_status = fair.get('doc_status', {})

    # Document cards
    col1, col2 = st.columns(2)

    # Helper function for document card
    def render_doc_card(doc_key: str, url_key: str, col):
        doc_info = DOCUMENT_TYPES.get(doc_key, {})
        url = docs.get(url_key)
        found = doc_status.get(doc_key, False)

        with col:
            status_class = "doc-found" if found else "doc-missing"
            status_icon = "✅" if found else "❌"

            st.markdown(f"""
            <div style="background: white; border-radius: 12px; padding: 1rem; margin-bottom: 1rem;
                        border: 1px solid {'#A7F3D0' if found else '#FECACA'}; box-shadow: 0 2px 4px rgba(0,0,0,0.05);">
                <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
                    <span style="font-size: 1.5rem;">{doc_info.get('icon', '📄')}</span>
                    <strong>{doc_info.get('dutch_name', doc_key)}</strong>
                    <span>{status_icon}</span>
                </div>
                <p style="color: #6B7280; font-size: 0.875rem; margin: 0.5rem 0;">
                    {doc_info.get('description', '')}
                </p>
            </div>
            """, unsafe_allow_html=True)

            if url:
                st.link_button(f"📥 Openen", url, use_container_width=True, key=f"open_{doc_key}")
            else:
                st.button("❌ Niet gevonden", disabled=True, use_container_width=True, key=f"missing_{doc_key}")

    # Render document cards
    render_doc_card('floorplan', 'floorplan_url', col1)
    render_doc_card('exhibitor_manual', 'exhibitor_manual_url', col2)
    render_doc_card('rules', 'rules_url', col1)
    render_doc_card('exhibitor_directory', 'exhibitor_directory_url', col2)

    # Schedule card (special handling)
    st.markdown("---")
    schedule = fair.get('schedule', {})
    build_up = schedule.get('build_up', [])
    tear_down = schedule.get('tear_down', [])
    has_schedule = len(build_up) > 0 or len(tear_down) > 0

    st.markdown(f"""
    <div style="background: white; border-radius: 12px; padding: 1rem;
                border: 1px solid {'#A7F3D0' if has_schedule else '#FECACA'};">
        <div style="display: flex; align-items: center; gap: 0.5rem; margin-bottom: 0.5rem;">
            <span style="font-size: 1.5rem;">📅</span>
            <strong>Opbouw & Afbouw Schema</strong>
            <span>{'✅' if has_schedule else '❌'}</span>
        </div>
    </div>
    """, unsafe_allow_html=True)

with tab_schedule:
    st.markdown("### Opbouw & Afbouw Schema")

    schedule = fair.get('schedule', {})
    build_up = schedule.get('build_up', [])
    tear_down = schedule.get('tear_down', [])

    if not build_up and not tear_down:
        st.info("Geen schema informatie beschikbaar.")
    else:
        col_build, col_tear = st.columns(2)

        with col_build:
            st.markdown("#### 🔨 Opbouw")
            if build_up:
                for entry in build_up:
                    date = entry.get('date', 'N/A')
                    time = entry.get('time', '')
                    desc = entry.get('description', '')

                    st.markdown(f"""
                    <div style="background: #F0FDF4; border-left: 4px solid #10B981;
                                padding: 0.75rem; margin-bottom: 0.5rem; border-radius: 0 8px 8px 0;">
                        <strong>{date}</strong> {time if time else ''}<br>
                        <span style="color: #6B7280; font-size: 0.875rem;">{desc}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.write("Geen opbouw data")

        with col_tear:
            st.markdown("#### 🧹 Afbouw")
            if tear_down:
                for entry in tear_down:
                    date = entry.get('date', 'N/A')
                    time = entry.get('time', '')
                    desc = entry.get('description', '')

                    st.markdown(f"""
                    <div style="background: #FEF2F2; border-left: 4px solid #EF4444;
                                padding: 0.75rem; margin-bottom: 0.5rem; border-radius: 0 8px 8px 0;">
                        <strong>{date}</strong> {time if time else ''}<br>
                        <span style="color: #6B7280; font-size: 0.875rem;">{desc}</span>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.write("Geen afbouw data")

with tab_raw:
    st.markdown("### Raw Discovery Data")

    st.info("Dit is de volledige data zoals gevonden door de discovery agent.")

    # Show discovery output if available
    discovery_output = fair.get('discovery_output')
    if discovery_output:
        st.json(discovery_output)
    else:
        st.json(fair)

    # Download button
    import json
    fair_json = json.dumps(fair, indent=2, ensure_ascii=False)
    st.download_button(
        label="📥 Download JSON",
        data=fair_json,
        file_name=f"{fair_id}_data.json",
        mime="application/json"
    )

# Notes section
st.markdown("---")
st.markdown("### 📝 Notities")

notes = fair.get('notes', [])
if notes:
    for note in notes:
        st.write(f"• {note}")

new_note = st.text_input("Nieuwe notitie toevoegen")
if st.button("➕ Toevoegen") and new_note:
    notes.append(f"{datetime.now().strftime('%Y-%m-%d %H:%M')}: {new_note}")
    fair['notes'] = notes
    dm.save_fair(fair_id, fair)
    st.success("Notitie toegevoegd!")
    st.rerun()

# Danger zone
st.markdown("---")
with st.expander("⚠️ Danger Zone"):
    st.warning("Let op: Deze acties kunnen niet ongedaan worden gemaakt.")

    if st.button("🗑️ Verwijder Beurs", type="secondary"):
        dm.delete_fair(fair_id)
        st.success(f"Beurs '{fair.get('name')}' verwijderd.")
        st.session_state.pop('selected_fair', None)
        st.switch_page("app.py")
