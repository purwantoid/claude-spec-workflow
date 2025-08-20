"""Dashboard module for spec-driven workflow monitoring.

This module provides dashboard functionality for monitoring and visualizing
spec progress through both terminal-based and optional web interfaces.
"""

from .cli import DashboardManager
from .parser import SpecParser, SpecStatus, SteeringStatus
from .watcher import SpecWatcher, SpecChangeEvent, GitChangeEvent, SteeringChangeEvent
from .terminal import TerminalDashboard

__all__ = [
    'DashboardManager',
    'TerminalDashboard',
    'SpecParser', 
    'SpecStatus',
    'SteeringStatus',
    'SpecWatcher',
    'SpecChangeEvent',
    'GitChangeEvent', 
    'SteeringChangeEvent'
]