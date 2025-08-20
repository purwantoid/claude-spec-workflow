"""Migration compatibility layer for TypeScript to Python transition.

This module provides compatibility features to ensure existing .claude/
directories and TypeScript-generated specs can be read and used by the
Python version without data loss or conflicts.
"""

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import aiofiles

logger = logging.getLogger(__name__)


class MigrationManager:
    """Manages migration compatibility between TypeScript and Python versions.
    
    Handles detection of existing .claude/ directories, parsing of TypeScript-
    generated specs, and ensuring no conflicts between versions.
    """

    def __init__(self, project_path: Path) -> None:
        """Initialize with project path.
        
        Args:
            project_path: Path to the project root directory.
        """
        self.project_path = project_path
        self.claude_dir = project_path / ".claude"

    async def has_existing_claude_directory(self) -> bool:
        """Check if a .claude directory already exists.
        
        Returns:
            True if .claude directory exists with expected structure.
        """
        if not self.claude_dir.exists():
            return False
        
        # Check for key directories that indicate an existing installation
        key_dirs = ["commands", "specs", "templates"]
        return any((self.claude_dir / dir_name).exists() for dir_name in key_dirs)

    async def detect_typescript_installation(self) -> bool:
        """Detect if TypeScript version files are present.
        
        Returns:
            True if TypeScript version indicators are found.
        """
        # Look for TypeScript-specific indicators
        ts_indicators = [
            "package.json",  # npm package
            "node_modules",  # installed dependencies
        ]
        
        for indicator in ts_indicators:
            if (self.project_path / indicator).exists():
                # Additional check: look for spec-driven-workflow in package.json
                if indicator == "package.json":
                    try:
                        async with aiofiles.open(self.project_path / "package.json", "r") as f:
                            package_data = json.loads(await f.read())
                            deps = {**package_data.get("dependencies", {}), 
                                   **package_data.get("devDependencies", {})}
                            if "claude-code-spec-workflow" in deps:
                                return True
                    except (json.JSONDecodeError, OSError):
                        pass
        
        return False

    async def read_existing_config(self) -> Optional[Dict[str, Any]]:
        """Read existing spec-config.json if it exists.
        
        Returns:
            Configuration data or None if not found.
        """
        config_file = self.claude_dir / "spec-config.json"
        if not config_file.exists():
            return None
        
        try:
            async with aiofiles.open(config_file, "r", encoding="utf-8") as f:
                return json.loads(await f.read())
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(f"Could not read existing config: {e}")
            return None

    async def get_existing_specs(self) -> List[Dict[str, Any]]:
        """Get list of existing specs from the specs directory.
        
        Returns:
            List of spec information dictionaries.
        """
        specs = []
        specs_dir = self.claude_dir / "specs"
        
        if not specs_dir.exists():
            return specs
        
        try:
            for spec_dir in specs_dir.iterdir():
                if spec_dir.is_dir():
                    spec_info = await self._parse_spec_directory(spec_dir)
                    if spec_info:
                        specs.append(spec_info)
        except OSError as e:
            logger.warning(f"Could not read specs directory: {e}")
        
        return specs

    async def _parse_spec_directory(self, spec_dir: Path) -> Optional[Dict[str, Any]]:
        """Parse a single spec directory for metadata.
        
        Args:
            spec_dir: Path to the spec directory.
            
        Returns:
            Spec information dictionary or None if invalid.
        """
        spec_name = spec_dir.name
        spec_info = {
            "name": spec_name,
            "path": str(spec_dir),
            "phase": "unknown",
            "files": [],
        }
        
        # Check for common spec files
        spec_files = ["requirements.md", "design.md", "tasks.md", "status.json"]
        
        for file_name in spec_files:
            file_path = spec_dir / file_name
            if file_path.exists():
                spec_info["files"].append(file_name)
                
                # Determine phase based on latest file
                if file_name == "requirements.md":
                    spec_info["phase"] = "requirements"
                elif file_name == "design.md":
                    spec_info["phase"] = "design"
                elif file_name == "tasks.md":
                    spec_info["phase"] = "tasks"
        
        # Try to read status.json for more detailed info
        status_file = spec_dir / "status.json"
        if status_file.exists():
            try:
                async with aiofiles.open(status_file, "r", encoding="utf-8") as f:
                    status_data = json.loads(await f.read())
                    spec_info.update(status_data)
            except (json.JSONDecodeError, OSError):
                pass
        
        return spec_info if spec_info["files"] else None

    async def get_existing_bugs(self) -> List[Dict[str, Any]]:
        """Get list of existing bugs from the bugs directory.
        
        Returns:
            List of bug information dictionaries.
        """
        bugs = []
        bugs_dir = self.claude_dir / "bugs"
        
        if not bugs_dir.exists():
            return bugs
        
        try:
            for bug_dir in bugs_dir.iterdir():
                if bug_dir.is_dir():
                    bug_info = await self._parse_bug_directory(bug_dir)
                    if bug_info:
                        bugs.append(bug_info)
        except OSError as e:
            logger.warning(f"Could not read bugs directory: {e}")
        
        return bugs

    async def _parse_bug_directory(self, bug_dir: Path) -> Optional[Dict[str, Any]]:
        """Parse a single bug directory for metadata.
        
        Args:
            bug_dir: Path to the bug directory.
            
        Returns:
            Bug information dictionary or None if invalid.
        """
        bug_name = bug_dir.name
        bug_info = {
            "name": bug_name,
            "path": str(bug_dir),
            "phase": "unknown",
            "files": [],
        }
        
        # Check for common bug files
        bug_files = ["report.md", "analysis.md", "verification.md", "status.json"]
        
        for file_name in bug_files:
            file_path = bug_dir / file_name
            if file_path.exists():
                bug_info["files"].append(file_name)
                
                # Determine phase based on latest file
                if file_name == "report.md":
                    bug_info["phase"] = "report"
                elif file_name == "analysis.md":
                    bug_info["phase"] = "analysis"
                elif file_name == "verification.md":
                    bug_info["phase"] = "verification"
        
        # Try to read status.json for more detailed info
        status_file = bug_dir / "status.json"
        if status_file.exists():
            try:
                async with aiofiles.open(status_file, "r", encoding="utf-8") as f:
                    status_data = json.loads(await f.read())
                    bug_info.update(status_data)
            except (json.JSONDecodeError, OSError):
                pass
        
        return bug_info if bug_info["files"] else None

    async def validate_compatibility(self) -> Tuple[bool, List[str]]:
        """Validate that existing .claude directory is compatible.
        
        Returns:
            Tuple of (is_compatible, list_of_issues).
        """
        issues = []
        
        if not await self.has_existing_claude_directory():
            return True, []  # No existing directory, no issues
        
        # Check for required directories
        required_dirs = ["commands", "specs", "templates"]
        for dir_name in required_dirs:
            dir_path = self.claude_dir / dir_name
            if not dir_path.exists():
                issues.append(f"Missing required directory: {dir_name}")
        
        # Check config file format
        config = await self.read_existing_config()
        if config and "spec_workflow" not in config:
            issues.append("Invalid spec-config.json format")
        
        # Check for conflicting files that might cause issues
        conflict_files = [
            "CLAUDE.md",  # Removed in newer versions
            "scripts",    # Removed in v1.2.5
        ]
        
        for conflict_file in conflict_files:
            if (self.claude_dir / conflict_file).exists():
                issues.append(f"Deprecated file/directory found: {conflict_file}")
        
        return len(issues) == 0, issues

    async def backup_existing_data(self, backup_suffix: str = ".backup") -> Optional[Path]:
        """Create a backup of existing .claude directory.
        
        Args:
            backup_suffix: Suffix to add to backup directory name.
            
        Returns:
            Path to backup directory or None if backup failed.
        """
        if not await self.has_existing_claude_directory():
            return None
        
        backup_dir = self.project_path / f".claude{backup_suffix}"
        
        try:
            # Simple copy by reading and writing files
            await self._copy_directory(self.claude_dir, backup_dir)
            return backup_dir
        except OSError as e:
            logger.error(f"Failed to create backup: {e}")
            return None

    async def _copy_directory(self, src: Path, dst: Path) -> None:
        """Recursively copy directory contents.
        
        Args:
            src: Source directory path.
            dst: Destination directory path.
        """
        dst.mkdir(parents=True, exist_ok=True)
        
        for item in src.iterdir():
            dst_item = dst / item.name
            
            if item.is_dir():
                await self._copy_directory(item, dst_item)
            else:
                async with aiofiles.open(item, "rb") as src_file:
                    content = await src_file.read()
                    async with aiofiles.open(dst_item, "wb") as dst_file:
                        await dst_file.write(content)

    async def get_migration_summary(self) -> Dict[str, Any]:
        """Get comprehensive migration information.
        
        Returns:
            Dictionary with migration details.
        """
        return {
            "has_existing_claude": await self.has_existing_claude_directory(),
            "has_typescript_installation": await self.detect_typescript_installation(),
            "existing_config": await self.read_existing_config(),
            "existing_specs": await self.get_existing_specs(),
            "existing_bugs": await self.get_existing_bugs(),
            "compatibility_check": await self.validate_compatibility(),
        }