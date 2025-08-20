"""Core setup functionality for spec-driven workflow.

This module contains the SpecWorkflowSetup class which handles directory
creation, command generation, and overall workflow initialization.
Converted from reference/src/setup.ts to maintain 1:1 feature parity.
"""

import json
from pathlib import Path
from typing import Optional

import aiofiles

from spec_driven_workflow.commands import (
    get_bug_analyze_command,
    get_bug_create_command,
    get_bug_fix_command,
    get_bug_status_command,
    get_bug_verify_command,
    get_spec_auto_run_command,
    get_spec_create_command,
    get_spec_design_command,
    get_spec_execute_command,
    get_spec_list_command,
    get_spec_requirements_command,
    get_spec_status_command,
    get_spec_steering_setup_command,
    get_spec_tasks_command,
)
from spec_driven_workflow.migration import MigrationManager
from spec_driven_workflow.steering import SteeringManager
from spec_driven_workflow.templates import (
    get_bug_analysis_template,
    get_bug_report_template,
    get_bug_verification_template,
    get_design_template,
    get_requirements_template,
    get_tasks_template,
)


class SpecWorkflowSetup:
    """Main setup class for spec workflow initialization.
    
    This class handles the creation of the .claude/ directory structure,
    generation of slash commands, templates, and overall project setup.
    Maintains identical functionality to the TypeScript version.
    """

    def __init__(self, project_root: Optional[Path] = None) -> None:
        """Initialize setup with project root directory.
        
        Args:
            project_root: Path to the project root. Defaults to current directory.
        """
        self.project_root = project_root or Path.cwd()
        self.claude_dir = self.project_root / ".claude"
        self.commands_dir = self.claude_dir / "commands"
        self.specs_dir = self.claude_dir / "specs"
        self.templates_dir = self.claude_dir / "templates"
        self.steering_dir = self.claude_dir / "steering"
        self.bugs_dir = self.claude_dir / "bugs"
        self.steering_manager = SteeringManager(self.project_root)
        self.migration_manager = MigrationManager(self.project_root)

    async def claude_directory_exists(self) -> bool:
        """Check if .claude directory already exists.
        
        Returns:
            True if .claude directory exists, False otherwise.
        """
        return self.claude_dir.exists() and self.claude_dir.is_dir()

    async def setup_directories(self) -> None:
        """Create all necessary directories for the workflow.
        
        Creates the complete .claude/ directory structure matching
        the TypeScript version exactly.
        """
        directories = [
            self.claude_dir,
            self.commands_dir,
            self.specs_dir,
            self.templates_dir,
            self.steering_dir,
            self.bugs_dir,
        ]

        for directory in directories:
            directory.mkdir(parents=True, exist_ok=True)

    async def create_slash_commands(self) -> None:
        """Generate all 13 slash command markdown files.
        
        Creates all spec workflow and bug fix workflow commands
        matching the TypeScript version exactly.
        """
        commands = {
            "spec-create": get_spec_create_command(),
            "spec-requirements": get_spec_requirements_command(),
            "spec-design": get_spec_design_command(),
            "spec-tasks": get_spec_tasks_command(),
            "spec-execute": get_spec_execute_command(),
            "spec-auto-run": get_spec_auto_run_command(),
            "spec-status": get_spec_status_command(),
            "spec-list": get_spec_list_command(),
            "spec-steering-setup": get_spec_steering_setup_command(),
            "bug-create": get_bug_create_command(),
            "bug-analyze": get_bug_analyze_command(),
            "bug-fix": get_bug_fix_command(),
            "bug-verify": get_bug_verify_command(),
            "bug-status": get_bug_status_command(),
        }

        for command_name, command_content in commands.items():
            command_file = self.commands_dir / f"{command_name}.md"
            async with aiofiles.open(command_file, "w", encoding="utf-8") as f:
                await f.write(command_content)

    async def create_templates(self) -> None:
        """Create all document templates.
        
        Generates template files for requirements, design, tasks,
        and bug workflow documents.
        """
        templates = {
            "requirements-template.md": get_requirements_template(),
            "design-template.md": get_design_template(),
            "tasks-template.md": get_tasks_template(),
            "bug-report-template.md": get_bug_report_template(),
            "bug-analysis-template.md": get_bug_analysis_template(),
            "bug-verification-template.md": get_bug_verification_template(),
        }

        for template_name, template_content in templates.items():
            template_file = self.templates_dir / template_name
            async with aiofiles.open(template_file, "w", encoding="utf-8") as f:
                await f.write(template_content)

    async def create_config_file(self) -> None:
        """Create the spec workflow configuration file.
        
        Creates spec-config.json with default workflow settings
        matching the TypeScript version.
        """
        config = {
            "spec_workflow": {
                "version": "1.0.0",
                "auto_create_directories": True,
                "auto_reference_requirements": True,
                "enforce_approval_workflow": True,
                "default_feature_prefix": "feature-",
                "supported_formats": ["markdown", "mermaid"],
            }
        }

        config_file = self.claude_dir / "spec-config.json"
        async with aiofiles.open(config_file, "w", encoding="utf-8") as f:
            await f.write(json.dumps(config, indent=2))

    async def get_steering_context(self) -> str:
        """Get formatted steering context for workflow operations.
        
        Returns:
            Formatted steering documents context string.
        """
        docs = await self.steering_manager.load_steering_documents()
        return self.steering_manager.format_steering_context(docs)

    async def has_steering_documents(self) -> bool:
        """Check if any steering documents exist.
        
        Returns:
            True if steering documents are available.
        """
        return await self.steering_manager.steering_documents_exist()

    async def get_migration_info(self) -> dict:
        """Get migration compatibility information.
        
        Returns:
            Dictionary with migration details and compatibility status.
        """
        return await self.migration_manager.get_migration_summary()

    async def has_existing_claude_setup(self) -> bool:
        """Check if an existing .claude directory is present.
        
        Returns:
            True if existing setup is detected.
        """
        return await self.migration_manager.has_existing_claude_directory()

    async def validate_migration_compatibility(self) -> tuple[bool, list[str]]:
        """Validate existing setup for compatibility.
        
        Returns:
            Tuple of (is_compatible, list_of_issues).
        """
        return await self.migration_manager.validate_compatibility()

    async def backup_existing_setup(self, suffix: str = ".backup") -> Optional[Path]:
        """Create backup of existing .claude directory.
        
        Args:
            suffix: Backup directory suffix.
            
        Returns:
            Path to backup directory or None if failed.
        """
        return await self.migration_manager.backup_existing_data(suffix)

    async def run_setup(self) -> None:
        """Execute the complete setup process.
        
        This is the main entry point for setting up the workflow
        in a project directory. Runs all setup steps in sequence.
        """
        await self.setup_directories()
        await self.create_slash_commands()
        await self.create_templates()
        await self.create_config_file()