"""
Cialona Trade Fair Discovery - Discovery Page
Supports multiple concurrent discoveries with live progress tracking.
"""

import streamlit as st
import json
import subprocess
import sys
import time as _time
from pathlib import Path
from datetime import datetime
import os

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
import data_manager as dm
import job_manager as jm
from config import CUSTOM_CSS, CIALONA_ORANGE, CIALONA_NAVY, APP_ICON

# Page configuration
st.set_page_config(
    page_title="Discovery | Cialona",
    page_icon=APP_ICON,
    layout="wide"
)

# Inject custom CSS
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


def ensure_playwright_installed():
    """Ensure Playwright browsers are installed."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            browser.close()
        return True
    except Exception as e:
        error_str = str(e)
        if "Executable doesn't exist" in error_str or "browserType.launch" in error_str:
            st.info("Eerste keer setup: Playwright browsers installeren...")
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "playwright", "install", "chromium"],
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    return True
                else:
                    st.error(f"Playwright installatie mislukt: {result.stderr}")
                    return False
            except Exception as install_error:
                st.error(f"Kon Playwright niet installeren: {install_error}")
                return False
        else:
            st.error(f"Playwright fout: {e}")
            return False


# ── Track which jobs belong to this session ──────────────────────────────
if 'my_job_ids' not in st.session_state:
    st.session_state.my_job_ids = []


# ── Sidebar ──────────────────────────────────────────────────────────────
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

    if st.button("Dashboard", use_container_width=True):
        st.switch_page("app.py")


# ── Header ───────────────────────────────────────────────────────────────
st.markdown(f"""
<div class="main-header">
    <h1>Nieuwe Discovery</h1>
    <p class="tagline">Vind automatisch exhibitor documenten voor een of meerdere beurzen</p>
</div>
""", unsafe_allow_html=True)

# ── Check for API key ────────────────────────────────────────────────────
api_key = os.environ.get('ANTHROPIC_API_KEY')
if not api_key:
    try:
        api_key = st.secrets.get('ANTHROPIC_API_KEY')
    except Exception:
        pass

if not api_key:
    st.warning("Anthropic API key niet geconfigureerd.")
    st.markdown("""
    **Hoe configureer je de API key?**
    1. Ga naar je app in Streamlit Cloud
    2. Klik op "Manage app" (rechtsonder) > "Settings" > "Secrets"
    3. Voeg toe:
    ```
    ANTHROPIC_API_KEY = "sk-ant-..."
    ```
    """)
    st.stop()


# ══════════════════════════════════════════════════════════════════════════
# SECTION 1: Start New Discovery Form
# ══════════════════════════════════════════════════════════════════════════

st.markdown("### Beurs Informatie")

col1, col2 = st.columns(2)

with col1:
    fair_name = st.text_input(
        "Beurs Naam *",
        placeholder="bijv. Ambiente, bauma, ISPO Munich",
        key="new_fair_name",
    )
    fair_city = st.text_input(
        "Stad",
        placeholder="bijv. Frankfurt, Munchen, Milaan",
        key="new_fair_city",
    )

with col2:
    current_year = datetime.now().year
    fair_year = st.number_input(
        "Jaar *",
        min_value=2020,
        max_value=2035,
        value=current_year + 1,
        step=1,
        key="new_fair_year",
    )
    fair_country = st.text_input(
        "Land",
        placeholder="bijv. Germany, Italy, Netherlands",
        key="new_fair_country",
    )

# Client name (optional)
client_name = st.text_input(
    "Klantnaam (optioneel)",
    placeholder="bijv. ACME Corporation, Shell, Philips",
    help="Wordt gebruikt in de concept-email voor ontbrekende documenten",
    key="new_client_name",
)

# Active jobs count
active_jobs = jm.get_active_jobs()
active_count = len(active_jobs)

# Start button
col_start, col_info = st.columns([2, 3])
with col_start:
    can_start = bool(fair_name)
    start_label = "Start Discovery"
    if active_count > 0:
        start_label = f"Start Discovery (+{active_count} actief)"

    if st.button(start_label, type="primary", disabled=not can_start, use_container_width=True):
        # Check Playwright once
        if not ensure_playwright_installed():
            st.error("Browser kon niet worden gestart. Probeer het later opnieuw.")
        else:
            job_id = jm.start_discovery(
                fair_name=fair_name,
                fair_year=int(fair_year),
                fair_city=fair_city or "",
                fair_country=fair_country or "",
                client_name=client_name or "",
                api_key=api_key,
            )
            st.session_state.my_job_ids.append(job_id)
            st.rerun()

with col_info:
    st.info(
        "**Tip:** Je kunt meerdere beurzen tegelijk starten. "
        "Vul een nieuwe beurs in en klik opnieuw op Start Discovery."
    )


# ══════════════════════════════════════════════════════════════════════════
# SECTION 2: Active & Recent Discoveries
# ══════════════════════════════════════════════════════════════════════════

# Collect all jobs for this session (single lookup per job)
my_jobs = []
for _jid in st.session_state.my_job_ids:
    _j = jm.get_job(_jid)
    if _j:
        my_jobs.append(_j)

# Split into active and finished
active = [j for j in my_jobs if j.status in ("pending", "running")]
finished = [j for j in my_jobs if j.status in ("completed", "failed", "cancelled")]

# ── Active discoveries ───────────────────────────────────────────────────
if active:
    st.markdown("---")
    st.markdown(f"### Actieve Discoveries ({len(active)})")

    for job in active:
        progress = jm.calc_progress(job)
        remaining = jm.calc_remaining(job)
        r_mins, r_secs = divmod(remaining, 60)
        elapsed = int(_time.time() - job.start_time) if job.start_time else 0
        e_mins, e_secs = divmod(elapsed, 60)

        cur_phase = jm._get_phase(job.current_phase)
        cur_idx = jm._phase_index(job.current_phase)

        # Unique key per job prevents Streamlit element identity issues during auto-refresh
        with st.container(key=f"active_{job.job_id}"):
            # Job header
            st.markdown(f"""
            <div id="header-{job.job_id}" style="background: white; border-radius: 12px; padding: 1.25rem; margin-bottom: 0.5rem;
                        border: 2px solid {CIALONA_ORANGE}; box-shadow: 0 2px 8px rgba(247,147,30,0.15);">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 0.75rem;">
                    <div>
                        <strong style="font-size: 1.1rem; color: {CIALONA_NAVY};">
                            {job.fair_name} {job.fair_year}
                        </strong>
                        <span style="background: {CIALONA_ORANGE}; color: white; padding: 0.15rem 0.6rem;
                              border-radius: 9999px; font-size: 0.75rem; margin-left: 0.5rem;">
                            {cur_phase['label']}
                        </span>
                    </div>
                    <div style="color: #6B7280; font-size: 0.85rem;">
                        ~{r_mins}:{r_secs:02d} resterend &middot; {e_mins}:{e_secs:02d} verstreken
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Stop button for this individual job
            if st.button("Stoppen", key=f"stop_{job.job_id}", type="secondary"):
                jm.stop_job(job.job_id)
                st.rerun()

            # Progress bar (value must be 0-100 int or 0.0-1.0 float)
            st.progress(min(max(progress, 0), 100))

            # Phase indicators
            phase_cols = st.columns(len(jm.PHASES))
            for i, (col, phase) in enumerate(zip(phase_cols, jm.PHASES)):
                with col:
                    if i < cur_idx:
                        col.markdown(f"""<div style="text-align:center;font-size:0.7rem;color:#10B981;
                            font-weight:600;">✓ {phase['label']}</div>""", unsafe_allow_html=True)
                    elif i == cur_idx:
                        col.markdown(f"""<div style="text-align:center;font-size:0.7rem;color:{CIALONA_ORANGE};
                            font-weight:600;">● {phase['label']}</div>""", unsafe_allow_html=True)
                    else:
                        col.markdown(f"""<div style="text-align:center;font-size:0.7rem;color:#9CA3AF;">
                            {phase['label']}</div>""", unsafe_allow_html=True)

            # Logs (collapsed)
            with st.expander("Voortgang details", expanded=False):
                if job.logs:
                    st.code("\n".join(job.logs[-20:]))
                else:
                    st.write("Wachten op logs...")

        st.markdown("")  # spacing

    # Auto-refresh while jobs are active
    _time.sleep(2)
    st.rerun()

# ── Finished discoveries ─────────────────────────────────────────────────
if finished:
    st.markdown("---")
    st.markdown(f"### Afgeronde Discoveries ({len(finished)})")

    for job in finished:
        elapsed = int(job.end_time - job.start_time) if job.end_time and job.start_time else 0
        e_mins, e_secs = divmod(elapsed, 60)

        if job.status == "completed":
            # Get result stats
            fair_data = dm.get_fair(job.fair_id) if job.fair_id else None
            found = 0
            total = 5
            if fair_data:
                comp = fair_data.get('completeness', {})
                found = comp.get('found', 0)
                total = comp.get('total', 5)

            st.markdown(f"""
            <div style="background: white; border-radius: 12px; padding: 1.25rem; margin-bottom: 0.5rem;
                        border: 2px solid #10B981; box-shadow: 0 2px 8px rgba(16,185,129,0.1);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong style="font-size: 1.1rem; color: {CIALONA_NAVY};">
                            {job.fair_name} {job.fair_year}
                        </strong>
                        <span style="background: #D1FAE5; color: #065F46; padding: 0.15rem 0.6rem;
                              border-radius: 9999px; font-size: 0.75rem; margin-left: 0.5rem;">
                            Voltooid
                        </span>
                    </div>
                    <div style="color: #6B7280; font-size: 0.85rem;">
                        {found}/{total} documenten &middot; {e_mins}:{e_secs:02d}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            col_a, col_b, col_c = st.columns([1, 1, 2])
            with col_a:
                if st.button("Bekijk Details", key=f"detail_{job.job_id}", use_container_width=True):
                    st.session_state['selected_fair'] = job.fair_id
                    st.switch_page("pages/2_Fair_Details.py")
            with col_b:
                if found < total:
                    if st.button("Email Sturen", key=f"email_{job.job_id}", use_container_width=True):
                        st.session_state['selected_fair'] = job.fair_id
                        st.switch_page("pages/3_Email_Generator.py")

        elif job.status == "cancelled":
            # Cancelled job
            st.markdown(f"""
            <div style="background: white; border-radius: 12px; padding: 1.25rem; margin-bottom: 0.5rem;
                        border: 2px solid #F59E0B; box-shadow: 0 2px 8px rgba(245,158,11,0.1);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong style="font-size: 1.1rem; color: {CIALONA_NAVY};">
                            {job.fair_name} {job.fair_year}
                        </strong>
                        <span style="background: #FEF3C7; color: #92400E; padding: 0.15rem 0.6rem;
                              border-radius: 9999px; font-size: 0.75rem; margin-left: 0.5rem;">
                            Gestopt
                        </span>
                    </div>
                    <div style="color: #6B7280; font-size: 0.85rem;">
                        {e_mins}:{e_secs:02d}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

        else:
            # Failed job
            st.markdown(f"""
            <div style="background: white; border-radius: 12px; padding: 1.25rem; margin-bottom: 0.5rem;
                        border: 2px solid #EF4444; box-shadow: 0 2px 8px rgba(239,68,68,0.1);">
                <div style="display: flex; justify-content: space-between; align-items: center;">
                    <div>
                        <strong style="font-size: 1.1rem; color: {CIALONA_NAVY};">
                            {job.fair_name} {job.fair_year}
                        </strong>
                        <span style="background: #FEE2E2; color: #991B1B; padding: 0.15rem 0.6rem;
                              border-radius: 9999px; font-size: 0.75rem; margin-left: 0.5rem;">
                            Mislukt
                        </span>
                    </div>
                    <div style="color: #6B7280; font-size: 0.85rem;">
                        {e_mins}:{e_secs:02d}
                    </div>
                </div>
            </div>
            """, unsafe_allow_html=True)

            with st.expander("Foutdetails"):
                st.error(job.error or "Onbekende fout")
                if job.logs:
                    st.code("\n".join(job.logs[-20:]))

        st.markdown("")  # spacing

# ── Legacy nav buttons for single-discovery flow ─────────────────────────
if not finished and 'last_discovery_fair_id' in st.session_state:
    _nav_fair_id = st.session_state['last_discovery_fair_id']
    col_nav1, col_nav2 = st.columns(2)
    with col_nav1:
        if st.button("Bekijk Details", use_container_width=True, key="nav_details"):
            st.session_state['selected_fair'] = _nav_fair_id
            st.switch_page("pages/2_Fair_Details.py")
    with col_nav2:
        if st.button("Naar Dashboard", use_container_width=True, key="nav_dashboard"):
            st.switch_page("app.py")

st.markdown("---")

# ── JSON Import (advanced) ───────────────────────────────────────────────
with st.expander("JSON Importeren (voor beheerders)"):
    st.markdown("Heb je al een discovery resultaat? Plak de JSON hier.")

    json_input = st.text_area(
        "JSON Data",
        height=200,
        placeholder='{"fair_name": "Ambiente", "documents": {...}, ...}'
    )

    uploaded_file = st.file_uploader("Of upload een JSON bestand", type=['json'])

    if uploaded_file is not None:
        json_input = uploaded_file.read().decode('utf-8')
        st.success(f"Bestand geladen: {uploaded_file.name}")

    if st.button("Importeren", disabled=not json_input, key="import_json"):
        try:
            discovery_data = json.loads(json_input)

            if 'fair_name' not in discovery_data:
                st.error("JSON moet een 'fair_name' veld bevatten")
            else:
                fair_id = dm.import_discovery_result(discovery_data)
                st.success(f"Beurs '{discovery_data['fair_name']}' geimporteerd!")

                if st.button("Bekijk Details", key="import_detail"):
                    st.session_state['selected_fair'] = fair_id
                    st.switch_page("pages/2_Fair_Details.py")

        except json.JSONDecodeError as e:
            st.error(f"Ongeldige JSON: {e}")
