"""
Cialona Trade Fair Discovery - Fair Details Page
View detailed information about a specific fair.
"""

import streamlit as st
import streamlit.components.v1 as components
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


def copy_button(text: str, label: str = "📋 Kopieer", btn_id: str = "copy", bg: str = "#0369A1"):
    """Render an HTML/JS button that copies text to clipboard."""
    import html as html_mod
    safe_text = html_mod.escape(text).replace("'", "\\'").replace("\n", "\\n")
    components.html(f"""
    <button id="{btn_id}" onclick="
        navigator.clipboard.writeText('{safe_text}').then(function() {{
            document.getElementById('{btn_id}').innerText = '✅ Gekopieerd!';
            setTimeout(function() {{ document.getElementById('{btn_id}').innerText = '{label}'; }}, 1500);
        }});
    " style="
        background: {bg}; color: white; border: none; padding: 0.5rem 1rem;
        border-radius: 6px; cursor: pointer; font-size: 0.9rem; width: 100%;
    ">{label}</button>
    """, height=42)


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
    logo_path = Path(__file__).parent.parent / "assets" / "logo.png"
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
tab_docs, tab_schedule, tab_contact, tab_raw = st.tabs(["📄 Documenten", "📅 Schema", "📧 Contact & Email", "🔧 Raw Data"])

with tab_docs:
    st.markdown("### Gevonden Documenten")

    docs = fair.get('documents', {})
    doc_status = fair.get('doc_status', {})

    # Document cards
    col1, col2 = st.columns(2)

    # Helper function for document card
    def render_doc_card(doc_key: str, url_key: str, col):
        doc_info = DOCUMENT_TYPES.get(doc_key, {})
        raw_url = docs.get(url_key)

        # Robust URL validation
        url = None
        if raw_url:
            if isinstance(raw_url, str) and raw_url.startswith('http'):
                url = raw_url.strip()
            elif isinstance(raw_url, (list, tuple)) and len(raw_url) > 0:
                # Handle case where URL is accidentally a list
                first = raw_url[0]
                if isinstance(first, str) and first.startswith('http'):
                    url = first.strip()

        found = url is not None

        with col:
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

            if found:
                try:
                    st.link_button("📥 Openen", url, use_container_width=True, key=f"open_{doc_key}")
                except Exception:
                    # Fallback to markdown link if link_button fails
                    st.markdown(f"[📥 Openen]({url})")
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

with tab_contact:
    st.markdown("### 📧 Contact Informatie & Email")

    # Get contact info and email draft from discovery output
    discovery_output = fair.get('discovery_output', {})
    contact_info = discovery_output.get('contact_info', {})
    email_draft = discovery_output.get('email_draft_if_missing')

    # Show recommended email prominently
    recommended_email = contact_info.get('recommended_email')
    recommended_reason = contact_info.get('recommended_email_reason', '')
    emails = contact_info.get('emails', [])

    if recommended_email:
        st.markdown("#### ⭐ Aanbevolen Emailadres")
        col_rec, col_rec_action = st.columns([3, 1])
        with col_rec:
            st.markdown(f"""
            <div style="background: #ECFDF5; border-radius: 8px; padding: 1rem; margin-bottom: 0.5rem;
                        border: 2px solid #059669;">
                <strong style="color: #065F46; font-size: 1.1rem;">⭐ {recommended_email}</strong>
                <br><span style="color: #047857; font-size: 0.85rem;">{recommended_reason}</span>
            </div>
            """, unsafe_allow_html=True)
        with col_rec_action:
            copy_button(recommended_email, "📋 Kopieer", btn_id="copy_rec", bg="#059669")

    # Show all other emails in a collapsible section
    if emails:
        other_emails = [e for e in emails if e.get('email') != recommended_email]
        label = f"Alle gevonden emailadressen ({len(emails)})"
        with st.expander(label, expanded=not recommended_email):
            for email_data in emails:
                email = email_data.get('email', '')
                context = email_data.get('context', '')
                is_recommended = email == recommended_email

                col_email, col_action = st.columns([3, 1])
                with col_email:
                    border_color = "#059669" if is_recommended else "#BAE6FD"
                    bg_color = "#ECFDF5" if is_recommended else "#F0F9FF"
                    prefix = "⭐ " if is_recommended else ""
                    st.markdown(f"""
                    <div style="background: {bg_color}; border-radius: 8px; padding: 0.75rem; margin-bottom: 0.5rem;
                                border: 1px solid {border_color};">
                        <strong style="color: #0369A1;">{prefix}{email}</strong>
                        {f'<br><span style="color: #6B7280; font-size: 0.8rem;">{context[:80]}</span>' if context else ''}
                    </div>
                    """, unsafe_allow_html=True)
                with col_action:
                    copy_button(email, "📋 Kopieer", btn_id=f"copy_{email.replace('@','_').replace('.','_')}")
    elif not recommended_email:
        st.info("Geen emailadressen gevonden tijdens de discovery.")

    st.markdown("---")

    # Show email draft if documents are missing
    if email_draft:
        st.markdown("#### ✉️ Concept Email voor Ontbrekende Documenten")
        st.warning("Onderstaande email is automatisch gegenereerd op basis van ontbrekende documenten.")

        # Split into Dutch and English sections
        if "=== CONCEPT EMAIL (NEDERLANDS) ===" in email_draft:
            parts = email_draft.split("=== DRAFT EMAIL (ENGLISH) ===")
            dutch_part = parts[0].replace("=== CONCEPT EMAIL (NEDERLANDS) ===", "").strip()
            english_part = parts[1].strip() if len(parts) > 1 else ""

            tab_nl, tab_en = st.tabs(["🇳🇱 Nederlands", "🇬🇧 English"])

            with tab_nl:
                st.text_area("Concept Email (NL)", dutch_part, height=350, key="email_nl")
                st.button("📋 Kopieer naar klembord", key="copy_nl", help="Selecteer de tekst hierboven en kopieer met Ctrl+C")

            with tab_en:
                st.text_area("Draft Email (EN)", english_part, height=350, key="email_en")
                st.button("📋 Copy to clipboard", key="copy_en", help="Select the text above and copy with Ctrl+C")
        else:
            st.text_area("Email Draft", email_draft, height=400)
    else:
        if fair.get('status') == 'complete':
            st.success("✅ Alle documenten zijn gevonden - geen email nodig!")
        else:
            st.info("Geen concept email beschikbaar. Start een nieuwe discovery om een email te genereren.")

with tab_raw:
    st.markdown("### Raw Discovery Data")

    st.info("Dit is de volledige data zoals gevonden door de discovery agent.")

    # Discovery Log download (detailed troubleshooting)
    discovery_output = fair.get('discovery_output', {})
    debug_info = discovery_output.get('debug', {})
    discovery_log = debug_info.get('discovery_log', [])
    discovery_summary = debug_info.get('discovery_summary', [])

    # Compact summary (for quick sharing / troubleshooting)
    if discovery_summary:
        st.markdown("#### Compact Summary (voor troubleshooting)")
        summary_text = "\n".join(discovery_summary)
        st.code(summary_text, language=None)
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            st.download_button(
                label="Download Summary (.txt)",
                data=summary_text,
                file_name=f"{fair_id}_summary.txt",
                mime="text/plain",
                key="dl_summary_txt"
            )
        with col_s2:
            # Copy-friendly version for pasting into chat
            st.download_button(
                label="Download Summary (.md)",
                data=summary_text,
                file_name=f"{fair_id}_summary.md",
                mime="text/markdown",
                key="dl_summary_md"
            )
        st.markdown("---")

    # Full detailed log (collapsed by default)
    if discovery_log:
        st.markdown("#### Volledige Discovery Log (gedetailleerd)")
        st.caption(f"{len(discovery_log)} log entries beschikbaar")

        # Build markdown log document
        log_lines = [
            f"# Discovery Log: {fair.get('name', 'Onbekend')}",
            f"Datum: {fair.get('last_discovery', 'Onbekend')}",
            f"Status: {fair.get('status', 'Onbekend')}",
            "",
            "---",
            "",
        ]
        log_lines.extend(discovery_log)

        log_text = "\n".join(log_lines)

        col_dl1, col_dl2 = st.columns(2)
        with col_dl1:
            st.download_button(
                label="Download Volledige Log (.txt)",
                data=log_text,
                file_name=f"{fair_id}_discovery_log.txt",
                mime="text/plain",
                key="dl_log_txt"
            )
        with col_dl2:
            st.download_button(
                label="Download Volledige Log (.md)",
                data=log_text,
                file_name=f"{fair_id}_discovery_log.md",
                mime="text/markdown",
                key="dl_log_md"
            )

        with st.expander("Volledige log bekijken", expanded=False):
            st.code("\n".join(discovery_log), language=None)

        st.markdown("---")

    # Show discovery output if available
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
