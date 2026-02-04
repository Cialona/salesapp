"""
Output schemas for Trade Fair Discovery.
"""

from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime


@dataclass
class TestCaseInput:
    fair_name: str
    known_url: Optional[str] = None
    city: Optional[str] = None
    country: Optional[str] = None


@dataclass
class ScheduleEntry:
    date: Optional[str] = None
    time: Optional[str] = None
    description: str = ""
    source_url: str = ""


@dataclass
class Documents:
    downloads_overview_url: Optional[str] = None
    floorplan_url: Optional[str] = None
    exhibitor_manual_url: Optional[str] = None
    rules_url: Optional[str] = None
    schedule_page_url: Optional[str] = None
    exhibitor_directory_url: Optional[str] = None


@dataclass
class Schedule:
    build_up: List[ScheduleEntry] = field(default_factory=list)
    tear_down: List[ScheduleEntry] = field(default_factory=list)


@dataclass
class Quality:
    floorplan: str = "missing"
    exhibitor_manual: str = "missing"
    rules: str = "missing"
    schedule: str = "missing"
    exhibitor_directory: str = "missing"


@dataclass
class Reasoning:
    floorplan: Optional[str] = None
    exhibitor_manual: Optional[str] = None
    rules: Optional[str] = None
    schedule: Optional[str] = None
    exhibitor_directory: Optional[str] = None


@dataclass
class Evidence:
    title: Optional[str] = None
    snippet: Optional[str] = None


@dataclass
class EvidenceSet:
    floorplan: Evidence = field(default_factory=Evidence)
    exhibitor_manual: Evidence = field(default_factory=Evidence)
    rules: Evidence = field(default_factory=Evidence)
    schedule: Evidence = field(default_factory=Evidence)
    exhibitor_directory: Evidence = field(default_factory=Evidence)


@dataclass
class ActionLogEntry:
    step: str
    input: str
    output: str
    ms: int


@dataclass
class DownloadedFileInfo:
    url: str
    path: str
    content_type: Optional[str] = None
    bytes: Optional[int] = None


@dataclass
class Candidates:
    floorplan: List[str] = field(default_factory=list)
    exhibitor_manual: List[str] = field(default_factory=list)
    rules: List[str] = field(default_factory=list)
    schedule: List[str] = field(default_factory=list)
    exhibitor_directory: List[str] = field(default_factory=list)


@dataclass
class DebugInfo:
    action_log: List[ActionLogEntry] = field(default_factory=list)
    visited_urls: List[str] = field(default_factory=list)
    downloaded_files: List[DownloadedFileInfo] = field(default_factory=list)
    blocked_urls: List[str] = field(default_factory=list)
    candidates: Candidates = field(default_factory=Candidates)
    notes: List[str] = field(default_factory=list)


@dataclass
class DiscoveryOutput:
    fair_name: str
    official_url: Optional[str] = None
    official_domain: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    venue: Optional[str] = None
    documents: Documents = field(default_factory=Documents)
    schedule: Schedule = field(default_factory=Schedule)
    quality: Quality = field(default_factory=Quality)
    primary_reasoning: Reasoning = field(default_factory=Reasoning)
    evidence: EvidenceSet = field(default_factory=EvidenceSet)
    debug: DebugInfo = field(default_factory=DebugInfo)
    email_draft_if_missing: Optional[str] = None


def create_empty_output(fair_name: str) -> DiscoveryOutput:
    """Create an empty discovery output."""
    return DiscoveryOutput(fair_name=fair_name)


def output_to_dict(output: DiscoveryOutput) -> Dict[str, Any]:
    """Convert DiscoveryOutput to dictionary for JSON serialization."""

    def schedule_entry_to_dict(entry: ScheduleEntry) -> Dict[str, Any]:
        return {
            'date': entry.date,
            'time': entry.time,
            'description': entry.description,
            'source_url': entry.source_url
        }

    def evidence_to_dict(ev: Evidence) -> Dict[str, Any]:
        return {'title': ev.title, 'snippet': ev.snippet}

    return {
        'fair_name': output.fair_name,
        'official_url': output.official_url,
        'official_domain': output.official_domain,
        'country': output.country,
        'city': output.city,
        'venue': output.venue,
        'documents': {
            'downloads_overview_url': output.documents.downloads_overview_url,
            'floorplan_url': output.documents.floorplan_url,
            'exhibitor_manual_url': output.documents.exhibitor_manual_url,
            'rules_url': output.documents.rules_url,
            'schedule_page_url': output.documents.schedule_page_url,
            'exhibitor_directory_url': output.documents.exhibitor_directory_url,
        },
        'schedule': {
            'build_up': [schedule_entry_to_dict(e) for e in output.schedule.build_up],
            'tear_down': [schedule_entry_to_dict(e) for e in output.schedule.tear_down],
        },
        'quality': {
            'floorplan': output.quality.floorplan,
            'exhibitor_manual': output.quality.exhibitor_manual,
            'rules': output.quality.rules,
            'schedule': output.quality.schedule,
            'exhibitor_directory': output.quality.exhibitor_directory,
        },
        'primary_reasoning': {
            'floorplan': output.primary_reasoning.floorplan,
            'exhibitor_manual': output.primary_reasoning.exhibitor_manual,
            'rules': output.primary_reasoning.rules,
            'schedule': output.primary_reasoning.schedule,
            'exhibitor_directory': output.primary_reasoning.exhibitor_directory,
        },
        'evidence': {
            'floorplan': evidence_to_dict(output.evidence.floorplan),
            'exhibitor_manual': evidence_to_dict(output.evidence.exhibitor_manual),
            'rules': evidence_to_dict(output.evidence.rules),
            'schedule': evidence_to_dict(output.evidence.schedule),
            'exhibitor_directory': evidence_to_dict(output.evidence.exhibitor_directory),
        },
        'debug': {
            'action_log': [
                {'step': e.step, 'input': e.input, 'output': e.output, 'ms': e.ms}
                for e in output.debug.action_log
            ],
            'visited_urls': output.debug.visited_urls,
            'downloaded_files': [
                {'url': f.url, 'path': f.path, 'content_type': f.content_type, 'bytes': f.bytes}
                for f in output.debug.downloaded_files
            ],
            'blocked_urls': output.debug.blocked_urls,
            'candidates': {
                'floorplan': output.debug.candidates.floorplan,
                'exhibitor_manual': output.debug.candidates.exhibitor_manual,
                'rules': output.debug.candidates.rules,
                'schedule': output.debug.candidates.schedule,
                'exhibitor_directory': output.debug.candidates.exhibitor_directory,
            },
            'notes': output.debug.notes,
        },
        'email_draft_if_missing': output.email_draft_if_missing,
    }
