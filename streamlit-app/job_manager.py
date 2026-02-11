"""
Job Manager for Concurrent Discoveries
Runs discovery jobs in background threads so the Streamlit UI stays responsive.
Module-level state is shared across all Streamlit sessions within the same process.
"""

import asyncio
import json
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Dict, List

# ── Job data structures ──────────────────────────────────────────────────

@dataclass
class DiscoveryJob:
    job_id: str
    fair_name: str
    fair_year: int
    fair_city: str = ""
    fair_country: str = ""
    client_name: str = ""
    status: str = "pending"           # pending | running | completed | failed
    current_phase: str = "url_lookup"
    progress: int = 0
    logs: List[str] = field(default_factory=list)
    result: Optional[dict] = None
    error: Optional[str] = None
    start_time: float = 0.0
    end_time: float = 0.0
    fair_id: Optional[str] = None     # Set after import into data_manager
    phase_start_time: float = 0.0


# ── Module-level singleton store ─────────────────────────────────────────
# Shared across Streamlit sessions in the same process.

_jobs: Dict[str, DiscoveryJob] = {}
_lock = threading.Lock()


def get_job(job_id: str) -> Optional[DiscoveryJob]:
    with _lock:
        return _jobs.get(job_id)


def get_all_jobs() -> List[DiscoveryJob]:
    with _lock:
        return list(_jobs.values())


def get_active_jobs() -> List[DiscoveryJob]:
    with _lock:
        return [j for j in _jobs.values() if j.status in ("pending", "running")]


def get_completed_jobs() -> List[DiscoveryJob]:
    with _lock:
        return [j for j in _jobs.values() if j.status in ("completed", "failed")]


def remove_job(job_id: str):
    with _lock:
        _jobs.pop(job_id, None)


def cleanup_old_jobs(max_age_secs: int = 3600):
    """Remove completed/failed jobs older than max_age_secs."""
    now = time.time()
    with _lock:
        to_remove = [
            jid for jid, j in _jobs.items()
            if j.status in ("completed", "failed")
            and j.end_time > 0
            and (now - j.end_time) > max_age_secs
        ]
        for jid in to_remove:
            del _jobs[jid]


# ── PHASES (mirrors ClaudeAgent.PHASES) ──────────────────────────────────

PHASES = [
    {"id": "url_lookup",    "label": "Website zoeken",        "pct_start": 0,  "pct_end": 10,  "est_secs": 10},
    {"id": "prescan",       "label": "Website scannen",       "pct_start": 10, "pct_end": 35,  "est_secs": 40},
    {"id": "portal_scan",   "label": "Portal detectie",       "pct_start": 35, "pct_end": 50,  "est_secs": 30},
    {"id": "classification","label": "Document classificatie", "pct_start": 50, "pct_end": 65,  "est_secs": 25},
    {"id": "browser_agent", "label": "Browser verificatie",   "pct_start": 65, "pct_end": 90,  "est_secs": 90},
    {"id": "results",       "label": "Resultaten verwerken",  "pct_start": 90, "pct_end": 100, "est_secs": 5},
]


def _get_phase(phase_id: str) -> dict:
    for p in PHASES:
        if p["id"] == phase_id:
            return p
    return PHASES[0]


def _phase_index(phase_id: str) -> int:
    for i, p in enumerate(PHASES):
        if p["id"] == phase_id:
            return i
    return 0


def calc_progress(job: DiscoveryJob) -> int:
    """Calculate interpolated progress % for a job."""
    if job.status == "completed":
        return 100
    if job.status == "failed":
        return 0
    phase = _get_phase(job.current_phase)
    elapsed_in_phase = time.time() - job.phase_start_time if job.phase_start_time > 0 else 0
    ratio = min(1.0, elapsed_in_phase / max(1, phase["est_secs"]))
    pct = phase["pct_start"] + ratio * (phase["pct_end"] - phase["pct_start"])
    return min(int(pct), 99)


def calc_remaining(job: DiscoveryJob) -> int:
    """Estimate remaining seconds."""
    if job.status in ("completed", "failed"):
        return 0
    cur_idx = _phase_index(job.current_phase)
    cur_phase = _get_phase(job.current_phase)
    in_phase = time.time() - job.phase_start_time if job.phase_start_time > 0 else 0
    cur_remaining = max(0, cur_phase["est_secs"] - in_phase)
    future = sum(p["est_secs"] for p in PHASES[cur_idx + 1:])
    return int(cur_remaining + future)


# ── Discovery runner (background thread) ─────────────────────────────────

def start_discovery(
    fair_name: str,
    fair_year: int,
    fair_city: str,
    fair_country: str,
    client_name: str,
    api_key: str,
) -> str:
    """Start a discovery job in a background thread. Returns job_id."""
    job_id = uuid.uuid4().hex[:8]
    job = DiscoveryJob(
        job_id=job_id,
        fair_name=fair_name,
        fair_year=fair_year,
        fair_city=fair_city,
        fair_country=fair_country,
        client_name=client_name,
        start_time=time.time(),
        phase_start_time=time.time(),
    )

    with _lock:
        _jobs[job_id] = job

    thread = threading.Thread(
        target=_run_discovery_thread,
        args=(job_id, api_key),
        daemon=True,
        name=f"discovery-{job_id}",
    )
    thread.start()
    return job_id


def _run_discovery_thread(job_id: str, api_key: str):
    """Execute a full discovery in a background thread with its own event loop."""
    job = _jobs[job_id]
    job.status = "running"

    # Create a fresh event loop for this thread
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(
            _run_discovery_async(job, api_key)
        )

        # Import result into data_manager
        import data_manager as dm
        result['year'] = job.fair_year
        fair_id = dm.import_discovery_result(result)

        job.result = result
        job.fair_id = fair_id
        job.status = "completed"
        job.current_phase = "results"
        job.progress = 100
        _add_log(job, f"Discovery voltooid! Fair ID: {fair_id}")

    except Exception as e:
        import traceback
        job.error = str(e)
        job.status = "failed"
        _add_log(job, f"FOUT: {e}")
        _add_log(job, traceback.format_exc())

    finally:
        job.end_time = time.time()
        loop.close()


def _add_log(job: DiscoveryJob, msg: str):
    """Thread-safe log append."""
    ts = time.strftime('%H:%M:%S')
    job.logs.append(f"[{ts}] {msg}")
    # Keep last 200 lines
    if len(job.logs) > 200:
        job.logs = job.logs[-200:]


async def _run_discovery_async(job: DiscoveryJob, api_key: str) -> dict:
    """The actual discovery logic, mirroring the old synchronous flow."""
    import sys
    sys.path.insert(0, str(Path(__file__).parent))

    from discovery.claude_agent import ClaudeAgent
    from discovery.schemas import TestCaseInput, output_to_dict

    # ── Phase & log callbacks that update the job ─────────────
    def on_status(msg: str):
        _add_log(job, msg)

    def on_phase(phase_id: str):
        now = time.time()
        job.current_phase = phase_id
        job.phase_start_time = now

    # ── Step 1: URL lookup ────────────────────────────────────
    _add_log(job, f"Zoeken naar website voor: {job.fair_name} {job.fair_year}")

    fair_url = await _find_fair_url(job, api_key)

    # ── Step 2: Run agent ─────────────────────────────────────
    if fair_url:
        _add_log(job, f"Start URL: {fair_url}")
    else:
        _add_log(job, "Agent zal zelf zoeken naar de website")

    input_data = TestCaseInput(
        fair_name=f"{job.fair_name} {job.fair_year}",
        known_url=fair_url,
        city=job.fair_city or None,
        country=job.fair_country or None,
        client_name=job.client_name or None,
    )

    agent = ClaudeAgent(
        api_key=api_key,
        max_iterations=40,
        debug=True,
        on_status=on_status,
        on_phase=on_phase,
        download_dir_suffix=job.job_id,
    )

    output = await agent.run(input_data)
    return output_to_dict(output)


async def _find_fair_url(job: DiscoveryJob, api_key: str) -> Optional[str]:
    """Use Claude to find fair website URL (runs in the job's event loop)."""
    import anthropic as _anthropic
    import socket

    client = _anthropic.Anthropic(api_key=api_key)

    failed_url = None
    max_attempts = 3

    for attempt in range(max_attempts):
        error_ctx = ""
        if failed_url:
            error_ctx = f'\nIMPORTANT: The previously suggested URL "{failed_url}" was INVALID. Double-check domain spelling.\n'

        prompt = f"""Find the official website URL for this trade fair:{error_ctx}

Trade Fair: {job.fair_name}
Year: {job.fair_year}
{f'City: {job.fair_city}' if job.fair_city else ''}

Return ONLY a JSON object with: url, confidence ("high"/"medium"/"low"), notes.
If not found: {{"url": null, "confidence": "low", "notes": "..."}}
Return ONLY JSON, no other text."""

        try:
            import random as _rnd
            resp = None
            for _api_attempt in range(4):
                try:
                    resp = client.messages.create(
                        model="claude-sonnet-4-20250514",
                        max_tokens=500,
                        messages=[{"role": "user", "content": prompt}],
                    )
                    break
                except Exception as rate_err:
                    if 'rate_limit' in str(rate_err).lower() or '429' in str(rate_err):
                        wait = (2 ** _api_attempt) * 5 + _rnd.uniform(0, 3)
                        _add_log(job, f"⏳ API rate limit (poging {_api_attempt + 1}/4), wacht {wait:.0f}s...")
                        await asyncio.sleep(wait)
                        if _api_attempt == 3:
                            raise
                    else:
                        raise

            if resp is None:
                break

            text = resp.content[0].text.strip()
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0].strip()
            elif "```" in text:
                text = text.split("```")[1].split("```")[0].strip()

            result = json.loads(text)
            candidate = result.get("url")
            if candidate:
                _add_log(job, f"URL gevonden: {candidate} ({result.get('confidence', '?')})")
                # Validate DNS
                from urllib.parse import urlparse as _urlparse
                hostname = _urlparse(candidate).hostname
                if hostname:
                    try:
                        socket.gethostbyname(hostname)
                        _add_log(job, "URL gevalideerd!")
                        return candidate
                    except (socket.gaierror, socket.herror):
                        _add_log(job, "URL ongeldig, opnieuw zoeken...")
                        failed_url = candidate
                        continue
            else:
                _add_log(job, f"Geen URL gevonden: {result.get('notes', '')}")
                break

        except Exception as e:
            _add_log(job, f"URL lookup fout: {e}")
            break

    return None
