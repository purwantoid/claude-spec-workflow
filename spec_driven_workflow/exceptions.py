"""Exception classes for spec-driven workflow operations.

This module defines the exception hierarchy used throughout the spec_driven_workflow
package, providing specific error types for different failure scenarios.
"""


class SpecWorkflowError(Exception):
    """Base exception for all spec workflow operations.
    
    This is the base class for all exceptions raised by the spec_driven_workflow
    package. All other exceptions in this module inherit from this class.
    """
    pass


class ProjectNotFoundError(SpecWorkflowError):
    """Raised when a project directory doesn't exist or is inaccessible.
    
    This exception is raised when trying to initialize a workflow in a directory
    that doesn't exist or when the specified project path is invalid.
    """
    pass


class ClaudeCodeNotFoundError(SpecWorkflowError):
    """Raised when Claude Code is not installed or not accessible.
    
    This exception is raised during setup validation when the Claude Code CLI
    cannot be found in the system PATH or is not properly installed.
    """
    pass


class SpecNotFoundError(SpecWorkflowError):
    """Raised when a specified spec doesn't exist.
    
    This exception is raised when trying to access, modify, or execute operations
    on a specification that doesn't exist in the project's .claude/specs/ directory.
    """
    pass


class TaskParsingError(SpecWorkflowError):
    """Raised when task parsing from markdown fails.
    
    This exception is raised when the task generator cannot parse tasks from
    a tasks.md file due to malformed markdown, invalid task format, or other
    parsing issues.
    """
    pass


class MCPValidationError(SpecWorkflowError):
    """Base exception for MCP (Model Context Protocol) validation errors.
    
    This exception is raised when MCP installation, configuration, or provider
    validation fails during setup or validation processes.
    """
    pass


class MCPInstallationError(MCPValidationError):
    """Raised when MCP CLI installation validation fails.
    
    This exception is raised when the MCP CLI cannot be found, is not properly
    installed, or fails version checking during setup validation.
    """
    pass


class MCPConfigurationError(MCPValidationError):
    """Raised when MCP configuration validation fails.
    
    This exception is raised when MCP configuration files are missing, malformed,
    or contain invalid provider configurations that prevent proper MCP operation.
    """
    pass


class MCPProviderError(MCPValidationError):
    """Raised when MCP provider connection or validation fails.
    
    This exception is raised when configured MCP providers cannot be reached,
    fail authentication, or return invalid responses during connection testing.
    """
    pass