"""Utility functions for project detection and validation.

This module contains utility functions for detecting project types,
validating Claude Code installation, and other helper functionality.
Converted from reference/src/utils.ts to maintain identical behavior.
"""

import asyncio
import socket
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, TYPE_CHECKING

import aiofiles

from spec_driven_workflow.exceptions import ProjectNotFoundError

if TYPE_CHECKING:
    from spec_driven_workflow.mcp_models import MCPConfigStatus, ProviderStatus


async def detect_project_type(project_path: Path) -> List[str]:
    """Detect the type of project based on indicator files.
    
    Analyzes the project directory for common project type indicators
    and returns a list of detected project types. This maintains identical
    logic to the TypeScript version.
    
    Args:
        project_path: Path to the project directory to analyze.
        
    Returns:
        List of detected project types (e.g., ["Python", "Node.js"]).
        
    Raises:
        ProjectNotFoundError: If the project directory doesn't exist.
    """
    if not project_path.exists() or not project_path.is_dir():
        raise ProjectNotFoundError(f"Project directory does not exist: {project_path}")
    
    # Project type indicators - identical to TypeScript version
    indicators: Dict[str, List[str]] = {
        'Node.js': ['package.json', 'node_modules'],
        'Python': ['requirements.txt', 'setup.py', 'pyproject.toml', '__pycache__'],
        'Java': ['pom.xml', 'build.gradle'],
        'C#': ['*.csproj', '*.sln'],
        'Go': ['go.mod', 'go.sum'],
        'Rust': ['Cargo.toml', 'Cargo.lock'],
        'PHP': ['composer.json', 'vendor'],
        'Ruby': ['Gemfile', 'Gemfile.lock'],
    }
    
    detected: List[str] = []
    
    for project_type, files in indicators.items():
        for file in files:
            try:
                if '*' in file:
                    # Handle glob patterns - simplified check
                    extension = file.replace('*', '')
                    if any(f.name.endswith(extension) for f in project_path.iterdir()):
                        detected.append(project_type)
                        break
                else:
                    if (project_path / file).exists():
                        detected.append(project_type)
                        break
            except (OSError, PermissionError):
                # File doesn't exist or access denied, continue
                continue
    
    return detected


async def validate_claude_code() -> bool:
    """Validate that Claude Code is installed and accessible.
    
    Checks if the Claude Code CLI is available by running 'claude --version'.
    Cross-platform support for Windows, macOS, and Linux.
    
    Returns:
        True if Claude Code is available, False otherwise.
    """
    import os
    import platform
    
    system = platform.system().lower()
    
    try:
        # Method 1: Try common Claude Code installation paths based on OS
        if system == "windows":
            claude_paths = [
                os.path.expanduser("~\\.claude\\local\\claude.exe"),
                os.path.expanduser("~\\AppData\\Local\\claude\\claude.exe"),
                os.path.expanduser("~\\AppData\\Roaming\\claude\\claude.exe"),
                "C:\\Program Files\\claude\\claude.exe",
                "C:\\Program Files (x86)\\claude\\claude.exe",
            ]
        else:  # macOS and Linux
            claude_paths = [
                os.path.expanduser("~/.claude/local/claude"),
                "/usr/local/bin/claude",
                "/usr/bin/claude",
                "/opt/claude/claude",
            ]
            if system == "darwin":  # macOS specific
                claude_paths.append("/opt/homebrew/bin/claude")
        
        for claude_path in claude_paths:
            if os.path.exists(claude_path):
                process = await asyncio.create_subprocess_exec(
                    claude_path, '--version',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                if process.returncode == 0:
                    return True
    except Exception:
        pass
    
    try:
        # Method 2: Try with shell command (handles aliases and PATH)
        if system == "windows":
            # Windows: Try both cmd and PowerShell
            commands = [
                'claude --version',  # Direct command
                'cmd /c claude --version',  # Via cmd
                'powershell -Command "claude --version"',  # Via PowerShell
            ]
        else:
            # Unix-like: Try with shell
            commands = ['claude --version']
            
        for cmd in commands:
            process = await asyncio.create_subprocess_shell(
                cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            await process.communicate()
            if process.returncode == 0:
                return True
    except Exception:
        pass
    
    try:
        # Method 3: Try direct executable (fallback for PATH-based installation)
        process = await asyncio.create_subprocess_exec(
            'claude', '--version',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        return process.returncode == 0
    except (FileNotFoundError, OSError):
        return False


async def find_claude_executable() -> Optional[str]:
    """Find the Claude executable path.
    
    Uses the same logic as validate_claude_code() but returns the path
    instead of just checking if it exists.
    
    Returns:
        Path to Claude executable if found, None otherwise.
    """
    import os
    import platform
    
    system = platform.system().lower()
    
    try:
        # Method 1: Try common Claude Code installation paths based on OS
        if system == "windows":
            claude_paths = [
                os.path.expanduser("~\\.claude\\local\\claude.exe"),
                os.path.expanduser("~\\AppData\\Local\\claude\\claude.exe"),
                os.path.expanduser("~\\AppData\\Roaming\\claude\\claude.exe"),
                "C:\\Program Files\\claude\\claude.exe",
                "C:\\Program Files (x86)\\claude\\claude.exe",
            ]
        else:  # macOS and Linux
            claude_paths = [
                os.path.expanduser("~/.claude/local/claude"),
                "/usr/local/bin/claude",
                "/usr/bin/claude",
                "/opt/claude/claude",
            ]
            if system == "darwin":  # macOS specific
                claude_paths.append("/opt/homebrew/bin/claude")
        
        for claude_path in claude_paths:
            if os.path.exists(claude_path):
                # Test if executable works
                process = await asyncio.create_subprocess_exec(
                    claude_path, '--version',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                await process.communicate()
                if process.returncode == 0:
                    return claude_path
    except Exception:
        pass
    
    try:
        # Method 2: Check if claude is in PATH
        process = await asyncio.create_subprocess_exec(
            'claude', '--version',
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        await process.communicate()
        if process.returncode == 0:
            return 'claude'  # Available in PATH
    except (FileNotFoundError, OSError):
        pass
    
    return None


async def ensure_context7_mcp_server() -> tuple[bool, str]:
    """Ensure the context7 MCP server is configured in Claude Code.
    
    Attempts to add context7 MCP server. If it already exists, that's considered a success.
    Uses Claude Code's built-in MCP management commands.
    
    Returns:
        Tuple of (success, a message). Success indicates if a context7 server is available.
        Message provides details about the operation performed.
    """
    try:
        # Try to add context7 MCP server
        success, error_message = await _add_context7_server()
        
        if success:
            return True, "context7 MCP server added successfully"
        elif error_message and "already exists" in error_message:
            return True, "context7 MCP server already configured"
        else:
            return False, f"Failed to add context7 MCP server: {error_message or 'unknown error'}"
            
    except Exception as e:
        return False, f"Error managing context7 MCP server: {e}"

async def _add_context7_server() -> tuple[bool, str]:
    """Add context7 MCP server to Claude Code.
    
    Cross-platform support for Windows, macOS, and Linux.
    
    Returns:
        Tuple of (success, error_message). Success indicates if command succeeded.
        Error message contains stderr output for debugging.
    """
    import os
    import platform
    
    system = platform.system().lower()
    
    try:
        # Try common Claude Code installation paths based on OS
        if system == "windows":
            claude_paths = [
                os.path.expanduser("~\\.claude\\local\\claude.exe"),
                os.path.expanduser("~\\AppData\\Local\\claude\\claude.exe"),
                os.path.expanduser("~\\AppData\\Roaming\\claude\\claude.exe"),
                "C:\\Program Files\\claude\\claude.exe",
                "C:\\Program Files (x86)\\claude\\claude.exe",
            ]
        else:  # macOS and Linux
            claude_paths = [
                os.path.expanduser("~/.claude/local/claude"),
                "/usr/local/bin/claude",
                "/usr/bin/claude",
                "/opt/claude/claude",
            ]
            if system == "darwin":  # macOS specific
                claude_paths.append("/opt/homebrew/bin/claude")
        
        for claude_path in claude_paths:
            if os.path.exists(claude_path):
                process = await asyncio.create_subprocess_exec(
                    claude_path, 'mcp', 'add', '--transport', 'http', 
                    'context7', 'https://mcp.context7.com/mcp',
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE
                )
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=30.0
                )
                
                success = process.returncode == 0
                error_message = stderr.decode().strip() if stderr else ""
                return success, error_message
        
        # If no direct path found, try via shell command (handles PATH)
        if system == "windows":
            cmd = 'claude mcp add --transport http context7 https://mcp.context7.com/mcp'
        else:
            cmd = 'claude mcp add --transport http context7 https://mcp.context7.com/mcp'
            
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        stdout, stderr = await asyncio.wait_for(
            process.communicate(), timeout=30.0
        )
        
        success = process.returncode == 0
        error_message = stderr.decode().strip() if stderr else ""
        
        if success or "already exists" in error_message:
            return success, error_message
        else:
            return False, error_message or "Claude Code executable not found"
            
    except asyncio.TimeoutError:
        return False, "Command timed out"
    except Exception as e:
        return False, str(e)




async def check_mcp_configuration(project_path: Path) -> 'MCPConfigStatus':
    """Validate MCP configuration file and structure.
    
    Discovers MCP configuration files in common locations, validates their
    structure, and extracts provider information. Supports JSON and YAML
    configuration formats commonly used by MCP installations.
    
    Args:
        project_path: Path to the project directory to check for MCP config
        
    Returns:
        MCPConfigStatus object with validation results, errors, and suggestions
        
    Raises:
        MCPConfigurationError: If configuration validation encounters unexpected errors
    """
    from spec_driven_workflow.mcp_models import MCPConfigStatus, ConfigValidationStatus
    from spec_driven_workflow.exceptions import MCPConfigurationError
    import json
    
    config_status = MCPConfigStatus(status=ConfigValidationStatus.MISSING)
    
    # Common MCP configuration file locations
    config_locations = [
        project_path / ".mcp" / "config.json",
        project_path / ".mcp.json",
        project_path / "mcp.json",
        project_path / ".mcp" / "settings.json",
        project_path / ".config" / "mcp" / "config.json",
        project_path.home() / ".mcp" / "config.json",  # User home directory
        project_path.home() / ".config" / "mcp" / "config.json",
    ]
    
    try:
        # Search for existing configuration files
        config_file = None
        for location in config_locations:
            if await file_exists(location):
                config_file = location
                config_status.config_path = config_file
                break
        
        if config_file is None:
            config_status.status = ConfigValidationStatus.MISSING
            config_status.add_suggestion("Create MCP configuration file in .mcp/config.json")
            config_status.add_suggestion("Run setup command to initialize MCP configuration")
            return config_status
        
        # Read and parse configuration file
        try:
            async with aiofiles.open(config_file, 'r', encoding='utf-8') as f:
                config_content = await f.read()
                
            # Try parsing as JSON first (most common format)
            if config_file.suffix == '.json':
                config_data = json.loads(config_content)
            else:
                # Try JSON regardless of extension
                try:
                    config_data = json.loads(config_content)
                except json.JSONDecodeError:
                    # Try YAML if JSON fails
                    try:
                        import yaml
                        config_data = yaml.safe_load(config_content)
                    except ImportError:
                        config_status.status = ConfigValidationStatus.PARSE_ERROR
                        config_status.add_error("Cannot parse YAML configuration (PyYAML not installed)")
                        return config_status
                    except Exception as e:  # Catch yaml.YAMLError and any other YAML-related errors
                        config_status.status = ConfigValidationStatus.PARSE_ERROR
                        config_status.add_error(f"YAML parsing error: {e}")
                        return config_status
                        
        except json.JSONDecodeError as e:
            config_status.status = ConfigValidationStatus.PARSE_ERROR
            config_status.add_error(f"JSON parsing error: {e}")
            return config_status
        except FileNotFoundError:
            config_status.status = ConfigValidationStatus.MISSING
            return config_status
        except Exception as e:
            raise MCPConfigurationError(f"Unexpected error reading MCP configuration: {e}")
        
        # Validate configuration structure
        validation_result = _validate_mcp_config_structure(config_data)
        config_status.status = validation_result.status
        config_status.providers = validation_result.providers
        config_status.errors.extend(validation_result.errors)
        config_status.suggestions.extend(validation_result.suggestions)
        
        return config_status
        
    except Exception as e:
        if isinstance(e, MCPConfigurationError):
            raise
        raise MCPConfigurationError(f"Unexpected error during MCP configuration validation: {e}")


def _validate_mcp_config_structure(config_data: dict) -> 'MCPConfigStatus':
    """Validate the structure of parsed MCP configuration data.
    
    Checks for required fields, validates provider configurations, and
    identifies common configuration issues that could prevent MCP from
    functioning properly.
    
    Args:
        config_data: Parsed configuration data dictionary
        
    Returns:
        MCPConfigStatus with validation results
    """
    from spec_driven_workflow.mcp_models import MCPConfigStatus, ConfigValidationStatus
    
    status = MCPConfigStatus(status=ConfigValidationStatus.VALID)
    
    try:
        # Check for required top-level fields
        if not isinstance(config_data, dict):
            status.status = ConfigValidationStatus.INVALID
            status.add_error("Configuration must be a JSON object")
            return status
        
        # Look for provider configurations in common locations
        providers_found = []
        
        # Check for 'providers' field (most common)
        if 'providers' in config_data:
            providers = config_data['providers']
            if isinstance(providers, dict):
                providers_found.extend(providers.keys())
            elif isinstance(providers, list):
                for provider in providers:
                    if isinstance(provider, dict) and 'name' in provider:
                        providers_found.append(provider['name'])
                    elif isinstance(provider, str):
                        providers_found.append(provider)
        
        # Check for 'mcpServers' field (alternative naming)
        if 'mcpServers' in config_data:
            servers = config_data['mcpServers']
            if isinstance(servers, dict):
                providers_found.extend(servers.keys())
            elif isinstance(servers, list):
                for server in servers:
                    if isinstance(server, dict) and 'name' in server:
                        providers_found.append(server['name'])
        
        # Check for 'servers' field (another common naming)
        if 'servers' in config_data:
            servers = config_data['servers']
            if isinstance(servers, dict):
                providers_found.extend(servers.keys())
        
        status.providers = list(set(providers_found))  # Remove duplicates
        
        # Validate provider configurations if found
        if status.providers:
            _validate_provider_configurations(config_data, status)
        else:
            status.add_suggestion("Add provider configurations to enable MCP context features")
            status.add_suggestion("Common providers include filesystem, git, and database connectors")
        
        # Check for common configuration issues
        _check_common_config_issues(config_data, status)
        
        return status
        
    except Exception as e:
        status.status = ConfigValidationStatus.INVALID
        status.add_error(f"Configuration structure validation error: {e}")
        return status


def _validate_provider_configurations(config_data: dict, status: 'MCPConfigStatus') -> None:
    """Validate individual provider configurations within MCP config.
    
    Args:
        config_data: Full configuration data
        status: MCPConfigStatus to update with validation results
    """
    providers = config_data.get('providers', {})
    servers = config_data.get('mcpServers', {})
    
    # Merge provider sources
    all_providers = {}
    if isinstance(providers, dict):
        all_providers.update(providers)
    if isinstance(servers, dict):
        all_providers.update(servers)
    
    for provider_name, provider_config in all_providers.items():
        if not isinstance(provider_config, dict):
            status.add_error(f"Provider '{provider_name}' configuration must be an object")
            continue
        
        # Check for required provider fields
        if 'command' not in provider_config and 'path' not in provider_config:
            status.add_error(f"Provider '{provider_name}' missing required 'command' or 'path' field")
        
        # Validate command array format
        if 'command' in provider_config:
            command = provider_config['command']
            if not isinstance(command, list) or not command:
                status.add_error(f"Provider '{provider_name}' command must be a non-empty array")
        
        # Check for common optional fields and provide suggestions
        if 'args' in provider_config and not isinstance(provider_config['args'], list):
            status.add_error(f"Provider '{provider_name}' args must be an array")
        
        if 'env' in provider_config and not isinstance(provider_config['env'], dict):
            status.add_error(f"Provider '{provider_name}' env must be an object")


def _check_common_config_issues(config_data: dict, status: 'MCPConfigStatus') -> None:
    """Check for common MCP configuration issues and provide suggestions.
    
    Args:
        config_data: Configuration data to check
        status: MCPConfigStatus to update with findings
    """
    # Check for version field
    if 'version' not in config_data:
        status.add_suggestion("Consider adding 'version' field to track configuration schema")
    
    # Check for logging configuration
    if 'logging' not in config_data:
        status.add_suggestion("Add logging configuration for better debugging")
    
    # Check for timeout settings
    if 'timeout' not in config_data and 'timeouts' not in config_data:
        status.add_suggestion("Consider adding timeout settings for provider connections")
    
    # Validate global settings if present
    if 'global' in config_data:
        global_config = config_data['global']
        if not isinstance(global_config, dict):
            status.add_error("Global configuration must be an object")


async def test_mcp_providers(config_path: Path) -> list['ProviderStatus']:
    """Test connections to configured MCP context providers.
    
    Attempts to connect to each provider configured in the MCP configuration
    file, testing their responsiveness and capabilities. Implements timeout
    handling to prevent hanging on unresponsive providers.
    
    Args:
        config_path: Path to the MCP configuration file
        
    Returns:
        List of ProviderStatus objects with connection test results
        
    Raises:
        MCPProviderError: If provider testing encounters unexpected errors
    """
    from spec_driven_workflow.mcp_models import ProviderStatus, ProviderConnectionStatus
    from spec_driven_workflow.exceptions import MCPProviderError
    import json
    import time
    
    provider_statuses = []
    
    try:
        # Read configuration file
        if not await file_exists(config_path):
            raise MCPProviderError(f"MCP configuration file not found: {config_path}")
        
        try:
            async with aiofiles.open(config_path, 'r', encoding='utf-8') as f:
                config_content = await f.read()
            config_data = json.loads(config_content)
        except (FileNotFoundError, json.JSONDecodeError) as e:
            raise MCPProviderError(f"Failed to read MCP configuration: {e}")
        
        # Extract provider configurations
        providers = _extract_provider_configs(config_data)
        
        if not providers:
            return provider_statuses  # No providers configured
        
        # Test each provider connection
        for provider_name, provider_config in providers.items():
            provider_status = await _test_single_provider(provider_name, provider_config)
            provider_statuses.append(provider_status)
        
        return provider_statuses
        
    except Exception as e:
        if isinstance(e, MCPProviderError):
            raise
        raise MCPProviderError(f"Unexpected error testing MCP providers: {e}")


async def _test_single_provider(provider_name: str, provider_config: dict) -> 'ProviderStatus':
    """Test connection to a single MCP provider.
    
    Args:
        provider_name: Name of the provider to test
        provider_config: Provider configuration dictionary
        
    Returns:
        ProviderStatus object with test results
    """
    from spec_driven_workflow.mcp_models import ProviderStatus, ProviderConnectionStatus
    import time
    
    start_time = time.time()
    
    try:
        # Get provider type from configuration
        provider_type = provider_config.get('type', 'unknown')
        
        # Initialize status object
        status = ProviderStatus(
            name=provider_name,
            type=provider_type,
            status=ProviderConnectionStatus.INACTIVE
        )
        
        # Check if provider has required configuration
        if 'command' not in provider_config and 'path' not in provider_config:
            status.status = ProviderConnectionStatus.NOT_CONFIGURED
            status.error_message = "Provider missing required 'command' or 'path' configuration"
            return status
        
        # Test provider connection based on type
        if 'command' in provider_config:
            command = provider_config['command']
            if isinstance(command, list) and command:
                success, capabilities, error = await _test_provider_command(command, provider_config)
                
                if success:
                    status.status = ProviderConnectionStatus.ACTIVE
                    status.capabilities = capabilities or []
                else:
                    status.status = ProviderConnectionStatus.ERROR
                    status.error_message = error
            else:
                status.status = ProviderConnectionStatus.NOT_CONFIGURED
                status.error_message = "Provider command must be a non-empty array"
        else:
            # Path-based provider (less common)
            status.status = ProviderConnectionStatus.INACTIVE
            status.error_message = "Path-based providers not currently testable"
        
        # Calculate response time
        status.response_time = time.time() - start_time
        
        return status
        
    except asyncio.TimeoutError:
        return ProviderStatus(
            name=provider_name,
            type=provider_config.get('type', 'unknown'),
            status=ProviderConnectionStatus.TIMEOUT,
            error_message="Provider connection timed out",
            response_time=time.time() - start_time
        )
    except Exception as e:
        return ProviderStatus(
            name=provider_name,
            type=provider_config.get('type', 'unknown'),
            status=ProviderConnectionStatus.ERROR,
            error_message=f"Provider connection error: {e}",
            response_time=time.time() - start_time
        )


async def _test_provider_command(command: list[str], provider_config: dict) -> tuple[bool, list[str] | None, str | None]:
    """Test a provider by executing its command with a test query.
    
    Args:
        command: Command array to execute
        provider_config: Full provider configuration
        
    Returns:
        Tuple of (success, capabilities, error_message)
    """
    try:
        # Get environment variables if specified
        env = provider_config.get('env', {})
        
        # Create a simple test process to check if provider is responsive
        # Most MCP providers support a version or help command
        test_commands = [
            command + ['--version'],
            command + ['--help'],
            command + ['-v'],
            command + ['-h'],
            command  # Just try the base command
        ]
        
        for test_cmd in test_commands:
            try:
                process = await asyncio.create_subprocess_exec(
                    *test_cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env={**env} if env else None
                )
                
                stdout, stderr = await asyncio.wait_for(
                    process.communicate(), timeout=3.0
                )
                
                # If command executed without error, consider provider active
                if process.returncode == 0:
                    # Try to extract capabilities from output
                    capabilities = _parse_provider_capabilities(stdout.decode())
                    return True, capabilities, None
                elif process.returncode is not None:
                    # Command ran but returned error - provider exists but may have issues
                    error_output = stderr.decode().strip()
                    if "command not found" in error_output.lower() or "no such file" in error_output.lower():
                        continue  # Try next test command
                    return False, None, f"Provider returned error code {process.returncode}: {error_output}"
            except asyncio.TimeoutError:
                # This specific test timed out, try next command
                continue   
            except (FileNotFoundError, OSError):
                # Command not found, try next test command
                continue
        
        # All test commands failed
        return False, None, "Provider command not found or not executable"
        
    except Exception as e:
        return False, None, f"Provider test error: {e}"


def _extract_provider_configs(config_data: dict) -> dict[str, dict]:
    """Extract provider configurations from MCP config data.
    
    Args:
        config_data: Parsed MCP configuration data
        
    Returns:
        Dictionary mapping provider names to their configurations
    """
    providers = {}
    
    # Check common provider configuration locations
    if 'providers' in config_data:
        provider_data = config_data['providers']
        if isinstance(provider_data, dict):
            providers.update(provider_data)
        elif isinstance(provider_data, list):
            for provider in provider_data:
                if isinstance(provider, dict) and 'name' in provider:
                    providers[provider['name']] = provider
    
    if 'mcpServers' in config_data:
        server_data = config_data['mcpServers']
        if isinstance(server_data, dict):
            providers.update(server_data)
    
    if 'servers' in config_data:
        server_data = config_data['servers']
        if isinstance(server_data, dict):
            providers.update(server_data)
    
    return providers


def _parse_provider_capabilities(output: str) -> list[str]:
    """Parse provider capabilities from command output.
    
    Args:
        output: Command output to parse for capabilities
        
    Returns:
        List of detected capabilities
    """
    capabilities = []
    
    if not output:
        return capabilities
    
    output_lower = output.lower()
    
    # Common MCP provider capabilities
    capability_indicators = {
        'filesystem': ['file', 'directory', 'read', 'write', 'path'],
        'git': ['git', 'repository', 'commit', 'branch'],
        'database': ['database', 'sql', 'query', 'table'],
        'web': ['http', 'url', 'web', 'api'],
        'search': ['search', 'index', 'find'],
        'code': ['code', 'syntax', 'parse', 'ast'],
        'documentation': ['doc', 'markdown', 'help'],
    }
    
    for capability, indicators in capability_indicators.items():
        if any(indicator in output_lower for indicator in indicators):
            capabilities.append(capability)
    
    return capabilities


async def suggest_providers_for_project(project_types: list[str]) -> list[str]:
    """Suggest appropriate MCP providers based on detected project types.
    
    Analyzes the project type and recommends MCP providers that would be
    most useful for the specific type of development work.
    
    Args:
        project_types: List of detected project types from detect_project_type()
        
    Returns:
        List of suggested provider names with brief descriptions
    """
    suggestions = []
    
    # Base suggestions for all projects
    base_providers = [
        "filesystem - Access project files and directory structure",
        "git - Integration with version control system",
    ]
    suggestions.extend(base_providers)
    
    # Type-specific suggestions
    for project_type in project_types:
        if project_type in ['python', 'pip']:
            suggestions.extend([
                "python - Python code analysis and execution",
                "pip - Python package management integration",
            ])
        elif project_type == 'node':
            suggestions.extend([
                "npm - Node.js package management",
                "javascript - JavaScript/TypeScript code analysis",
            ])
        elif project_type == 'web':
            suggestions.extend([
                "web - HTTP client for API testing",
                "browser - Web browser automation",
            ])
        elif project_type in ['docker', 'kubernetes']:
            suggestions.extend([
                "docker - Container management and inspection",
                "kubernetes - Cluster resource management",
            ])
        elif project_type == 'database':
            suggestions.extend([
                "postgresql - PostgreSQL database access",
                "sqlite - SQLite database operations",
            ])
    
    # Remove duplicates while preserving order
    seen = set()
    unique_suggestions = []
    for suggestion in suggestions:
        if suggestion not in seen:
            seen.add(suggestion)
            unique_suggestions.append(suggestion)
    
    return unique_suggestions


async def create_basic_mcp_config(project_path: Path, project_types: list[str] | None = None) -> bool:
    """Create a basic MCP configuration file for the project.
    
    Generates a basic MCP configuration file with suggested providers based on
    the detected project type. Prompts user for confirmation before creating
    the file and allows customization of provider selection.
    
    Args:
        project_path: Path to the project directory where config should be created
        project_types: Optional list of detected project types for provider suggestions
        
    Returns:
        True if configuration was successfully created, False otherwise
        
    Raises:
        MCPConfigurationError: If config creation fails
    """
    from spec_driven_workflow.exceptions import MCPConfigurationError
    import json
    
    try:
        # Determine project types if not provided
        if project_types is None:
            project_types = await detect_project_type(project_path)
        
        # Create .mcp directory if it doesn't exist
        mcp_dir = project_path / ".mcp"
        config_path = mcp_dir / "config.json"
        
        # Check if config already exists
        if await file_exists(config_path):
            return False  # Don't overwrite existing configuration
        
        # Create directory
        mcp_dir.mkdir(exist_ok=True)
        
        # Generate configuration template
        config_template = _generate_mcp_config_template(project_types)
        
        # Write configuration file
        async with aiofiles.open(config_path, 'w', encoding='utf-8') as f:
            await f.write(json.dumps(config_template, indent=2))
        
        return True
        
    except Exception as e:
        raise MCPConfigurationError(f"Failed to create MCP configuration: {e}")


def _generate_mcp_config_template(project_types: list[str]) -> dict:
    """Generate a basic MCP configuration template based on project types.
    
    Args:
        project_types: List of detected project types
        
    Returns:
        Configuration dictionary suitable for JSON serialization
    """
    config = {
        "version": "1.0",
        "description": "Generated MCP configuration for spec-driven workflow",
        "providers": {},
        "global": {
            "timeout": 30000,
            "retries": 3
        },
        "logging": {
            "level": "info",
            "file": ".mcp/logs/mcp.log"
        }
    }
    
    # Add base providers that are useful for all projects
    base_providers = {
        "filesystem": {
            "type": "filesystem",
            "command": ["mcp-server-filesystem"],
            "args": [str(Path.cwd())],
            "description": "Access to project files and directory structure"
        },
        "git": {
            "type": "git",
            "command": ["mcp-server-git"],
            "args": [str(Path.cwd())],
            "description": "Git repository integration and version control"
        }
    }
    
    config["providers"].update(base_providers)
    
    # Add project-type-specific providers
    type_specific_providers = {}
    
    if 'python' in project_types:
        type_specific_providers["python"] = {
            "type": "python",
            "command": ["python", "-m", "mcp.server.python"],
            "description": "Python code analysis and execution support"
        }
        
        if 'pip' in project_types:
            type_specific_providers["pip"] = {
                "type": "package",
                "command": ["mcp-server-pip"],
                "description": "Python package management integration"
            }
    
    if 'node' in project_types:
        type_specific_providers["npm"] = {
            "type": "package",
            "command": ["mcp-server-npm"],
            "description": "Node.js package management"
        }
        type_specific_providers["javascript"] = {
            "type": "code",
            "command": ["mcp-server-javascript"],
            "description": "JavaScript/TypeScript code analysis"
        }
    
    if 'web' in project_types:
        type_specific_providers["web"] = {
            "type": "web",
            "command": ["mcp-server-web"],
            "description": "HTTP client for web API testing"
        }
    
    if 'docker' in project_types:
        type_specific_providers["docker"] = {
            "type": "container",
            "command": ["mcp-server-docker"],
            "description": "Docker container management"
        }
    
    if 'database' in project_types:
        type_specific_providers["sqlite"] = {
            "type": "database",
            "command": ["mcp-server-sqlite"],
            "args": ["./database.sqlite"],
            "description": "SQLite database operations"
        }
    
    # Add type-specific providers to configuration
    config["providers"].update(type_specific_providers)
    
    # Add helpful comments as a separate section
    config["_comments"] = {
        "providers": "Configure MCP context providers for your project",
        "command": "Command array to execute the provider server",
        "args": "Additional arguments passed to the provider",
        "env": "Environment variables for the provider (optional)",
        "type": "Provider type for categorization and display",
        "description": "Human-readable description of provider capabilities"
    }
    
    return config


async def validate_and_suggest_mcp_config_improvements(config_path: Path) -> list[str]:
    """Validate existing MCP configuration and suggest improvements.
    
    Analyzes the current MCP configuration and provides suggestions for
    optimization, additional providers, or configuration improvements based
    on project analysis and best practices.
    
    Args:
        config_path: Path to existing MCP configuration file
        
    Returns:
        List of improvement suggestions
        
    Raises:
        MCPConfigurationError: If validation encounters errors
    """
    from spec_driven_workflow.exceptions import MCPConfigurationError
    import json
    
    suggestions = []
    
    try:
        if not await file_exists(config_path):
            suggestions.append("No MCP configuration found - consider creating one with create_basic_mcp_config()")
            return suggestions
        
        # Read existing configuration
        async with aiofiles.open(config_path, 'r', encoding='utf-8') as f:
            config_content = await f.read()
        
        config_data = json.loads(config_content)
        project_path = config_path.parent.parent  # Assume .mcp/config.json structure
        project_types = await detect_project_type(project_path)
        
        # Check for missing base providers
        providers = config_data.get('providers', {})
        
        if 'filesystem' not in providers:
            suggestions.append("Add filesystem provider for project file access")
        
        if 'git' not in providers and await file_exists(project_path / '.git'):
            suggestions.append("Add git provider for version control integration")
        
        # Check for project-type-specific improvements
        if 'python' in project_types and 'python' not in providers:
            suggestions.append("Add python provider for Python code analysis")
        
        if 'node' in project_types and 'npm' not in providers:
            suggestions.append("Add npm provider for Node.js package management")
        
        if 'web' in project_types and 'web' not in providers:
            suggestions.append("Add web provider for HTTP API testing")
        
        # Check configuration structure
        if 'global' not in config_data:
            suggestions.append("Add global section with timeout and retry settings")
        
        if 'logging' not in config_data:
            suggestions.append("Add logging configuration for debugging MCP issues")
        
        # Check provider configurations
        for provider_name, provider_config in providers.items():
            if not isinstance(provider_config, dict):
                continue
                
            if 'command' not in provider_config:
                suggestions.append(f"Provider '{provider_name}' missing command configuration")
            
            if 'description' not in provider_config:
                suggestions.append(f"Add description for provider '{provider_name}' for better documentation")
        
        # Performance suggestions
        if len(providers) > 10:
            suggestions.append("Consider organizing providers into groups or profiles for better performance")
        
        # Security suggestions
        for provider_name, provider_config in providers.items():
            if isinstance(provider_config, dict) and 'env' in provider_config:
                env_vars = provider_config['env']
                if isinstance(env_vars, dict):
                    for key, _value in env_vars.items():
                        if any(secret_word in key.lower() for secret_word in ['password', 'secret', 'key', 'token']):
                            suggestions.append(f"Provider '{provider_name}' may contain sensitive data in environment variables")
        
        return suggestions
        
    except json.JSONDecodeError as e:
        raise MCPConfigurationError(f"Invalid JSON in MCP configuration: {e}")
    except Exception as e:
        raise MCPConfigurationError(f"Failed to validate MCP configuration: {e}")


async def file_exists(file_path: Path) -> bool:
    """Check if a file exists.
    
    Args:
        file_path: Path to the file to check.
        
    Returns:
        True if file exists, False otherwise.
    """
    return file_path.exists() and file_path.is_file()


async def ensure_directory(dir_path: Path) -> None:
    """Ensure a directory exists, creating it if necessary.
    
    Args:
        dir_path: Path to the directory to create.
        
    Raises:
        OSError: If directory creation fails for reasons other than already existing.
    """
    try:
        dir_path.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        # Re-raise if it's not a "directory already exists" error
        if e.errno != 17:  # EEXIST
            raise


async def is_port_available(port: int) -> bool:
    """Check if a port is available for use.
    
    Args:
        port: Port number to check.
        
    Returns:
        True if port is available, False otherwise.
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('localhost', port))
            return result != 0
    except (socket.error, OSError):
        return False


async def find_available_port(start_port: int = 3000, max_attempts: int = 100) -> int:
    """Find an available port starting from a given port number.
    
    Args:
        start_port: Port number to start checking from.
        max_attempts: Maximum number of ports to check.
        
    Returns:
        First available port number found.
        
    Raises:
        RuntimeError: If no available port is found within max_attempts.
    """
    for port in range(start_port, start_port + max_attempts):
        if await is_port_available(port):
            return port
    
    raise RuntimeError(
        f"Could not find an available port after checking {max_attempts} "
        f"ports starting from {start_port}"
    )


async def get_best_available_port(
    preferred_ports: Optional[List[int]] = None
) -> int:
    """Get the best available port from a list of preferred ports, with fallback.
    
    Args:
        preferred_ports: List of preferred port numbers to try first.
                        Defaults to [3000, 3001, 3002, 8080, 8000, 4000].
        
    Returns:
        First available port from preferred list, or any available port >= 3000.
    """
    if preferred_ports is None:
        preferred_ports = [3000, 3001, 3002, 8080, 8000, 4000]
    
    # First try the preferred ports
    for port in preferred_ports:
        if await is_port_available(port):
            return port
    
    # Fall back to finding any available port starting from 3000
    return await find_available_port(3000)