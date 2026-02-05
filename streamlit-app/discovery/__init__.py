"""
Trade Fair Discovery Module
Python implementation of the Claude Computer Use agent.
"""

from .browser_controller import BrowserController
from .claude_agent import ClaudeAgent
from .schemas import DiscoveryOutput, TestCaseInput, create_empty_output
from .document_classifier import DocumentClassifier, ClassificationResult, DocumentClassification

__all__ = [
    'BrowserController',
    'ClaudeAgent',
    'DiscoveryOutput',
    'TestCaseInput',
    'create_empty_output',
    'DocumentClassifier',
    'ClassificationResult',
    'DocumentClassification',
]
