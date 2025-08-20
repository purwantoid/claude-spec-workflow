"""Spec Driven Workflow - Python implementation of claude-code-spec-workflow.

Automated workflows for Claude Code. Includes spec-driven development 
(Requirements → Design → Tasks → Implementation) and a streamlined bug fix workflow
(Report → Analyze → Fix → Verify).

This package provides 1:1 feature parity with the TypeScript version while
leveraging Python tooling (uv/uvx) instead of npm/Node.js.
"""

__version__ = "1.3.4"
__author__ = "Pimzino"
__license__ = "MIT"

# Package exports
from spec_driven_workflow.exceptions import (
    SpecWorkflowError,
    ProjectNotFoundError,
    ClaudeCodeNotFoundError,
    SpecNotFoundError,
    TaskParsingError,
)

__all__ = [
    "__version__",
    "__author__",
    "__license__",
    "SpecWorkflowError",
    "ProjectNotFoundError", 
    "ClaudeCodeNotFoundError",
    "SpecNotFoundError",
    "TaskParsingError",
]