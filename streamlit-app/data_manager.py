"""
Data Manager for Trade Fair Discovery
Handles loading, saving, and managing fair data.
"""

import fcntl
import json
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

try:
    import streamlit as st
except ImportError:
    st = None

# Data directory
DATA_DIR = Path(__file__).parent / "data"
FAIRS_FILE = DATA_DIR / "fairs.json"
LOCK_FILE = DATA_DIR / ".fairs.lock"

# In-process lock for thread safety (fcntl only protects across processes)
_file_lock = threading.Lock()

def ensure_data_dir():
    """Ensure data directory exists."""
    DATA_DIR.mkdir(exist_ok=True)

def load_fairs() -> dict:
    """Load all fairs from JSON file (thread-safe with file lock)."""
    ensure_data_dir()
    if FAIRS_FILE.exists():
        with _file_lock:
            with open(FAIRS_FILE, 'r', encoding='utf-8') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)  # Shared (read) lock
                try:
                    return json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return {}

def save_fairs(fairs: dict):
    """Save all fairs to JSON file (thread-safe with exclusive file lock)."""
    ensure_data_dir()
    with _file_lock:
        with open(FAIRS_FILE, 'w', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)  # Exclusive (write) lock
            try:
                json.dump(fairs, f, indent=2, ensure_ascii=False)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def get_fair(fair_id: str) -> Optional[dict]:
    """Get a specific fair by ID."""
    fairs = load_fairs()
    return fairs.get(fair_id)

def save_fair(fair_id: str, fair_data: dict):
    """Save or update a specific fair (atomic read-modify-write)."""
    ensure_data_dir()
    fair_data['updated_at'] = datetime.now().isoformat()
    with _file_lock:
        # Read under lock
        fairs = {}
        if FAIRS_FILE.exists():
            with open(FAIRS_FILE, 'r', encoding='utf-8') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    fairs = json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        # Modify
        fairs[fair_id] = fair_data
        # Write under lock
        with open(FAIRS_FILE, 'w', encoding='utf-8') as f:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
            try:
                json.dump(fairs, f, indent=2, ensure_ascii=False)
            finally:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def delete_fair(fair_id: str):
    """Delete a fair (atomic read-modify-write)."""
    ensure_data_dir()
    with _file_lock:
        fairs = {}
        if FAIRS_FILE.exists():
            with open(FAIRS_FILE, 'r', encoding='utf-8') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_SH)
                try:
                    fairs = json.load(f)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        if fair_id in fairs:
            del fairs[fair_id]
            with open(FAIRS_FILE, 'w', encoding='utf-8') as f:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                try:
                    json.dump(fairs, f, indent=2, ensure_ascii=False)
                finally:
                    fcntl.flock(f.fileno(), fcntl.LOCK_UN)

def create_fair_id(fair_name: str) -> str:
    """Create a URL-safe ID from fair name."""
    import re
    # Remove special characters, lowercase, replace spaces with dashes
    fair_id = re.sub(r'[^a-zA-Z0-9\s-]', '', fair_name.lower())
    fair_id = re.sub(r'\s+', '-', fair_id.strip())
    return fair_id

def import_discovery_result(discovery_output: dict) -> str:
    """Import a discovery result and save it as a fair."""
    fair_name = discovery_output.get('fair_name', 'Unknown Fair')
    fair_id = create_fair_id(fair_name)

    # Calculate completeness
    docs = discovery_output.get('documents', {})
    quality = discovery_output.get('quality', {})
    schedule = discovery_output.get('schedule', {})

    # Schedule is "found" if quality is strong/partial OR actual date entries exist
    schedule_found = (
        quality.get('schedule') in ('strong', 'partial')
        or bool(schedule.get('build_up'))
        or bool(schedule.get('tear_down'))
        or bool(docs.get('schedule_page_url'))
    )

    doc_status = {
        'floorplan': bool(docs.get('floorplan_url')),
        'exhibitor_manual': bool(docs.get('exhibitor_manual_url')),
        'rules': bool(docs.get('rules_url')),
        'schedule': schedule_found,
        'exhibitor_directory': bool(docs.get('exhibitor_directory_url')),
    }

    found_count = sum(doc_status.values())
    total_count = len(doc_status)

    fair_data = {
        'id': fair_id,
        'name': fair_name,
        'official_url': discovery_output.get('official_url'),
        'official_domain': discovery_output.get('official_domain'),
        'country': discovery_output.get('country'),
        'city': discovery_output.get('city'),
        'venue': discovery_output.get('venue'),
        'documents': docs,
        'schedule': discovery_output.get('schedule', {}),
        'quality': quality,
        'doc_status': doc_status,
        'completeness': {
            'found': found_count,
            'total': total_count,
            'percentage': round(found_count / total_count * 100) if total_count > 0 else 0
        },
        'discovery_output': discovery_output,  # Store full output for reference
        'created_at': datetime.now().isoformat(),
        'updated_at': datetime.now().isoformat(),
        'status': 'complete' if found_count == total_count else ('partial' if found_count > 0 else 'missing'),
        'notes': [],
        'contact_email': None,  # For email functionality
    }

    save_fair(fair_id, fair_data)
    return fair_id

def get_fairs_summary() -> dict:
    """Get summary statistics for all fairs."""
    fairs = load_fairs()

    total = len(fairs)
    complete = sum(1 for f in fairs.values() if f.get('status') == 'complete')
    partial = sum(1 for f in fairs.values() if f.get('status') == 'partial')
    missing = sum(1 for f in fairs.values() if f.get('status') == 'missing')

    # Calculate overall document coverage
    total_docs = 0
    found_docs = 0
    for fair in fairs.values():
        completeness = fair.get('completeness', {})
        total_docs += completeness.get('total', 0)
        found_docs += completeness.get('found', 0)

    return {
        'total_fairs': total,
        'complete': complete,
        'partial': partial,
        'missing': missing,
        'total_docs': total_docs,
        'found_docs': found_docs,
        'doc_percentage': round(found_docs / total_docs * 100) if total_docs > 0 else 0
    }

def get_fairs_for_display() -> list:
    """Get all fairs formatted for display in dashboard."""
    fairs = load_fairs()
    display_list = []

    for fair_id, fair in fairs.items():
        display_list.append({
            'id': fair_id,
            'name': fair.get('name', 'Unknown'),
            'url': fair.get('official_url', ''),
            'status': fair.get('status', 'unknown'),
            'completeness': fair.get('completeness', {}),
            'doc_status': fair.get('doc_status', {}),
            'updated_at': fair.get('updated_at', ''),
            'country': fair.get('country'),
            'city': fair.get('city'),
        })

    # Sort by name
    display_list.sort(key=lambda x: x['name'].lower())
    return display_list

# Demo data for testing
DEMO_FAIRS = {
    "ambiente": {
        "id": "ambiente",
        "name": "Ambiente",
        "official_url": "https://ambiente.messefrankfurt.com",
        "official_domain": "ambiente.messefrankfurt.com",
        "country": "Germany",
        "city": "Frankfurt",
        "venue": "Messe Frankfurt",
        "documents": {
            "downloads_overview_url": "https://fairconstruction.messefrankfurt.com/frankfurt/en/download.html",
            "floorplan_url": "https://ambiente.messefrankfurt.com/content/dam/messefrankfurt-redaktion/consumergoods/ground-plan/ambiente-christmasworld-creativeworld-hall-plan2026.pdf",
            "exhibitor_manual_url": "https://ambiente.messefrankfurt.com/content/dam/messefrankfurt-redaktion/ambiente/agb/ambiente-gtc.pdf",
            "rules_url": "https://fairconstruction.messefrankfurt.com/content/dam/messefrankfurt-redaktion/fairconstruction/documents/en/fairconstruction-faq-setup-dismantling-2025.pdf",
            "schedule_page_url": None,
            "exhibitor_directory_url": "https://ambiente.messefrankfurt.com/frankfurt/en/exhibitor-search.html"
        },
        "schedule": {
            "build_up": [
                {"date": "2026-01-29", "time": "07:00-24:00", "description": "Advanced set-up"},
                {"date": "2026-01-30", "time": "07:00-24:00", "description": "Advanced set-up"},
                {"date": "2026-01-31", "time": "00:00-15:00", "description": "Regular set-up"},
                {"date": "2026-02-05", "time": "15:00-24:00", "description": "Set-up within stand area only"}
            ],
            "tear_down": [
                {"date": "2026-02-10", "time": "20:30-24:00", "description": "Regular dismantling starts"},
                {"date": "2026-02-13", "time": "09:00", "description": "Regular dismantling ends"}
            ]
        },
        "quality": {
            "floorplan": "strong",
            "exhibitor_manual": "strong",
            "rules": "strong",
            "schedule": "strong",
            "exhibitor_directory": "strong"
        },
        "doc_status": {
            "floorplan": True,
            "exhibitor_manual": True,
            "rules": True,
            "schedule": True,
            "exhibitor_directory": True
        },
        "completeness": {"found": 5, "total": 5, "percentage": 100},
        "status": "complete",
        "created_at": "2026-02-04T10:00:00",
        "updated_at": "2026-02-04T10:00:00",
        "notes": [],
        "contact_email": "exhibitor@messefrankfurt.com"
    },
    "bauma": {
        "id": "bauma",
        "name": "bauma",
        "official_url": "https://bauma.de",
        "official_domain": "bauma.de",
        "country": "Germany",
        "city": "München",
        "venue": "Messe München",
        "documents": {
            "downloads_overview_url": "https://bauma.de/de/messe/aussteller/aussteller-shop/",
            "floorplan_url": "https://d2n1n6byqxibyi.cloudfront.net/asset/933560888063/document_s9siall9gd5032r82c1s719u4n/BMA25-Gelaendeplan-low.pdf",
            "exhibitor_manual_url": "https://d2n1n6byqxibyi.cloudfront.net/asset/933560888063/document_9anugq9j295g9bkfappq254l4m/MM_Services A-Z_DT_2026_bfsg.pdf",
            "rules_url": "https://d2n1n6byqxibyi.cloudfront.net/asset/933560888063/document_eplhfioknp0nrcvm54lopsg35e/MM25-Technische-Richtlinien.pdf",
            "schedule_page_url": None,
            "exhibitor_directory_url": "https://exhibitors.bauma.de"
        },
        "schedule": {
            "build_up": [
                {"date": "2028-04-03", "time": "TBD", "description": "bauma 2028 start"}
            ],
            "tear_down": [
                {"date": "2028-04-09", "time": "TBD", "description": "bauma 2028 end"}
            ]
        },
        "quality": {
            "floorplan": "strong",
            "exhibitor_manual": "strong",
            "rules": "strong",
            "schedule": "strong",
            "exhibitor_directory": "strong"
        },
        "doc_status": {
            "floorplan": True,
            "exhibitor_manual": True,
            "rules": True,
            "schedule": True,
            "exhibitor_directory": True
        },
        "completeness": {"found": 5, "total": 5, "percentage": 100},
        "status": "complete",
        "created_at": "2026-02-04T10:00:00",
        "updated_at": "2026-02-04T10:00:00",
        "notes": [],
        "contact_email": None
    }
}

def load_demo_data():
    """Load demo data for testing."""
    for fair_id, fair_data in DEMO_FAIRS.items():
        save_fair(fair_id, fair_data)
