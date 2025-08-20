"""Data models for MCP (Model Context Protocol) validation and configuration.

This module defines the core data structures used for MCP installation checking,
configuration validation, and provider testing. Following established project
patterns with dataclass-based models and enum types for status tracking.
"""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import List, Optional


class ConfigValidationStatus(Enum):
    """Status enumeration for MCP configuration validation.
    
    VALID: Configuration file exists and is properly formatted
    INVALID: Configuration file has parsing or structure errors
    MISSING: Configuration file does not exist
    PARSE_ERROR: Configuration file cannot be parsed (malformed JSON/YAML)
    """
    VALID = "valid"
    INVALID = "invalid"
    MISSING = "missing"
    PARSE_ERROR = "parse_error"


class ProviderConnectionStatus(Enum):
    """Status enumeration for MCP provider connection testing.
    
    ACTIVE: Provider is running and responding to connections
    INACTIVE: Provider is configured but not currently running
    ERROR: Provider connection failed with error
    TIMEOUT: Provider connection timed out
    NOT_CONFIGURED: Provider is not configured in MCP settings
    """
    ACTIVE = "active"
    INACTIVE = "inactive"
    ERROR = "error"
    TIMEOUT = "timeout"
    NOT_CONFIGURED = "not_configured"


@dataclass
class MCPConfigStatus:
    """Status and details of MCP configuration validation.
    
    This class encapsulates the result of MCP configuration file validation,
    including the validation status, file location, discovered providers,
    and any errors or suggestions for improvement.
    """
    status: ConfigValidationStatus
    config_path: Optional[Path] = None
    providers: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    
    @property
    def is_valid(self) -> bool:
        """Check if configuration is valid and usable.
        
        Returns:
            True if configuration status is VALID
        """
        return self.status == ConfigValidationStatus.VALID
    
    @property
    def has_providers(self) -> bool:
        """Check if any providers are configured.
        
        Returns:
            True if at least one provider is configured
        """
        return len(self.providers) > 0
    
    def add_error(self, error: str) -> None:
        """Add an error message to the configuration status.
        
        Args:
            error: Error message to add
        """
        self.errors.append(error)
    
    def add_suggestion(self, suggestion: str) -> None:
        """Add a suggestion for improving the configuration.
        
        Args:
            suggestion: Suggestion message to add
        """
        self.suggestions.append(suggestion)


@dataclass
class ProviderStatus:
    """Status and details of individual MCP provider connection.
    
    This class captures the connection status and capabilities of a specific
    MCP context provider, including error information for debugging and
    troubleshooting connection issues.
    """
    name: str
    type: str
    status: ProviderConnectionStatus
    capabilities: List[str] = field(default_factory=list)
    error_message: Optional[str] = None
    response_time: Optional[float] = None  # Connection response time in seconds
    
    @property
    def is_active(self) -> bool:
        """Check if provider is actively responding.
        
        Returns:
            True if provider status is ACTIVE
        """
        return self.status == ProviderConnectionStatus.ACTIVE
    
    @property
    def has_error(self) -> bool:
        """Check if provider has connection error.
        
        Returns:
            True if provider has error or timeout status
        """
        return self.status in [ProviderConnectionStatus.ERROR, ProviderConnectionStatus.TIMEOUT]
    
    def get_status_display(self) -> str:
        """Get human-readable status display string.
        
        Returns:
            Formatted status string for display
        """
        status_display = {
            ProviderConnectionStatus.ACTIVE: "✅ Active",
            ProviderConnectionStatus.INACTIVE: "⏸️ Inactive",
            ProviderConnectionStatus.ERROR: "❌ Error",
            ProviderConnectionStatus.TIMEOUT: "⏱️ Timeout",
            ProviderConnectionStatus.NOT_CONFIGURED: "⚙️ Not Configured"
        }
        return status_display.get(self.status, f"❓ {self.status.value}")


@dataclass
class MCPValidationResult:
    """Comprehensive result of MCP validation process.
    
    This class consolidates all aspects of MCP validation including installation
    status, configuration validation, and provider connection testing. Used to
    provide complete feedback to users about their MCP environment status.
    """
    installation_valid: bool
    version: Optional[str] = None
    config_status: Optional[MCPConfigStatus] = None
    provider_statuses: List[ProviderStatus] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    validation_time: float = 0.0
    
    @property
    def is_fully_valid(self) -> bool:
        """Check if MCP environment is fully valid and ready.
        
        Returns:
            True if installation is valid and configuration is usable
        """
        return (
            self.installation_valid and
            self.config_status is not None and
            self.config_status.is_valid
        )
    
    @property
    def active_provider_count(self) -> int:
        """Count the number of active providers.
        
        Returns:
            Number of providers with ACTIVE status
        """
        return sum(1 for provider in self.provider_statuses if provider.is_active)
    
    @property
    def has_warnings(self) -> bool:
        """Check if validation generated any warnings.
        
        Returns:
            True if there are warnings or suggestions
        """
        return len(self.warnings) > 0 or len(self.suggestions) > 0
    
    def add_warning(self, warning: str) -> None:
        """Add a warning message to the validation result.
        
        Args:
            warning: Warning message to add
        """
        self.warnings.append(warning)
    
    def add_suggestion(self, suggestion: str) -> None:
        """Add a suggestion for improving the MCP setup.
        
        Args:
            suggestion: Suggestion message to add
        """
        self.suggestions.append(suggestion)
    
    def get_summary_message(self) -> str:
        """Generate a summary message for the validation result.
        
        Returns:
            Human-readable summary of MCP validation status
        """
        if not self.installation_valid:
            return "❌ MCP is not installed or not accessible"
        
        if self.config_status is None or not self.config_status.is_valid:
            return f"⚠️ MCP {self.version} is installed but configuration is invalid"
        
        active_count = self.active_provider_count
        total_count = len(self.provider_statuses)
        
        if active_count == 0:
            return f"⚠️ MCP {self.version} is configured but no providers are active"
        elif active_count == total_count:
            return f"✅ MCP {self.version} is fully configured with {active_count} active providers"
        else:
            return f"⚠️ MCP {self.version} is configured with {active_count}/{total_count} active providers"


@dataclass
class MCPInstallationInfo:
    """Information about MCP CLI installation.
    
    This class captures details about the MCP installation including version,
    installation path, and any installation-specific metadata needed for
    validation and troubleshooting.
    """
    is_installed: bool
    version: Optional[str] = None
    installation_path: Optional[Path] = None
    installation_method: Optional[str] = None  # pip, npm, binary, etc.
    python_version_compatible: Optional[bool] = None
    
    @property
    def version_display(self) -> str:
        """Get formatted version display string.
        
        Returns:
            Formatted version string or "Unknown" if version unavailable
        """
        return self.version if self.version else "Unknown"
    
    def get_installation_summary(self) -> str:
        """Generate installation summary message.
        
        Returns:
            Human-readable installation status summary
        """
        if not self.is_installed:
            return "❌ MCP CLI not found"
        
        version_info = f" (v{self.version})" if self.version else ""
        method_info = f" via {self.installation_method}" if self.installation_method else ""
        
        return f"✅ MCP CLI installed{version_info}{method_info}"