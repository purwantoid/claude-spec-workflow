"""Migration validation utility for npx-to-uvx migration.

This module provides validation functions to detect remaining legacy npx references
and verify uvx command format consistency across the codebase.
"""

import os
import re
import time
from pathlib import Path
from typing import List, Dict, Tuple
from dataclasses import dataclass


@dataclass
class ValidationResult:
    """Results from migration validation."""
    legacy_references_found: List[str]
    invalid_uvx_formats: List[str]
    files_processed: int
    migration_complete: bool
    processing_time: float

class MigrationValidator:
    """Validates npx-to-uvx migration completion and command format consistency."""

    def __init__(self, project_root: str = None):
        """Initialize validator with project root directory."""
        self.project_root = Path(project_root) if project_root else Path.cwd()
        self.legacy_pattern = re.compile(r'npx\s+@pimzino/claude-code-spec-workflow@latest')
        self.uvx_pattern = re.compile(
            r'uvx\s+--from\s+git\+https://github\.com/purwantoid/claude-spec-workflow\.git\s+spec-driven-workflow'
        )
        
        # File patterns to scan
        self.scan_patterns = ['*.py', '*.md']
        
        # Directories to exclude from scanning
        self.exclude_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv'}
    
    def scan_for_legacy_references(self) -> List[str]:
        """Scan codebase for remaining legacy npx references.
        
        Returns:
            List of file paths containing legacy references with line numbers.
        """
        legacy_references = []
        
        for file_path in self._get_scan_files():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        if self.legacy_pattern.search(line):
                            legacy_references.append(f"{file_path}:{line_num}")
            except (UnicodeDecodeError, IOError):
                # Skip binary or unreadable files
                continue
                
        return legacy_references
    
    def validate_uvx_format(self) -> List[str]:
        """Validate uvx command format consistency.
        
        Only flags truly invalid formats, allows legitimate variations like:
        - Branch/tag specifications: @main, @v1.0.0
        - Different commands: setup, --help, etc.
        
        Returns:
            List of file paths with invalid uvx command formats.
        """
        invalid_formats = []

        # Pattern for uvx commands with github repo - allows legitimate variations
        valid_uvx_pattern = re.compile(r'uvx\s+(?:--from\s+)?git\+(?:https://.*@?|ssh://.*@)github\.com/purwantoid/claude-spec-workflow\.git(?:@[\w.-]+)?\s+spec-driven-workflow')
        
        # Pattern for shortened uvx commands (also valid)
        short_uvx_pattern = re.compile(r'uvx\s+spec-driven-workflow')
        
        # Pattern for any uvx command mentioning spec-driven-workflow
        loose_uvx_pattern = re.compile(r'uvx\s+.*spec-driven-workflow')
        
        for file_path in self._get_scan_files():
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    for line_num, line in enumerate(f, 1):
                        if loose_uvx_pattern.search(line):
                            # Check if it matches any valid format
                            if not (valid_uvx_pattern.search(line) or short_uvx_pattern.search(line)):
                                invalid_formats.append(f"{file_path}:{line_num}")
            except (UnicodeDecodeError, IOError):
                continue
                
        return invalid_formats
    
    def validate_migration(self) -> ValidationResult:
        """Perform comprehensive migration validation.
        
        Returns:
            ValidationResult with complete validation status.
        """
        start_time = time.time()
        
        # Scan for legacy references
        legacy_references = self.scan_for_legacy_references()
        
        # Validate uvx format
        invalid_formats = self.validate_uvx_format()
        
        # Count processed files
        files_processed = len(list(self._get_scan_files()))
        
        # Calculate processing time
        processing_time = time.time() - start_time
        
        # Determine if migration is complete
        migration_complete = len(legacy_references) == 0 and len(invalid_formats) == 0
        
        return ValidationResult(
            legacy_references_found=legacy_references,
            invalid_uvx_formats=invalid_formats,
            files_processed=files_processed,
            migration_complete=migration_complete,
            processing_time=processing_time
        )
    
    def _get_scan_files(self):
        """Get all files to scan based on patterns and exclusions."""
        for pattern in self.scan_patterns:
            for file_path in self.project_root.rglob(pattern):
                # Skip files in excluded directories
                if any(exc_dir in file_path.parts for exc_dir in self.exclude_dirs):
                    continue
                    
                # Skip our own spec files (which contain expected legacy references for documentation)
                if 'npx-to-uvx-migration' in str(file_path):
                    continue
                
                # Skip test files that legitimately contain test strings
                if file_path.name.startswith('test_') and 'migration_validator' in str(file_path):
                    continue
                
                # Skip the migration validator itself (contains regex patterns)
                if file_path.name == 'migration_validator.py':
                    continue
                    
                yield file_path
    
    def generate_report(self, result: ValidationResult) -> str:
        """Generate human-readable validation report.
        
        Args:
            result: ValidationResult from validate_migration()
            
        Returns:
            Formatted validation report string.
        """
        report = []
        report.append("# NPX-to-UVX Migration Validation Report")
        report.append(f"Generated: {time.strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("")
        
        # Summary
        status = "✅ COMPLETE" if result.migration_complete else "❌ INCOMPLETE"
        report.append(f"## Migration Status: {status}")
        report.append(f"- Files processed: {result.files_processed}")
        report.append(f"- Processing time: {result.processing_time:.2f} seconds")
        report.append("")
        
        # Legacy references
        if result.legacy_references_found:
            report.append("## ❌ Legacy NPX References Found")
            report.append(f"Found {len(result.legacy_references_found)} legacy references:")
            for ref in result.legacy_references_found:
                report.append(f"- {ref}")
            report.append("")
        else:
            report.append("## ✅ No Legacy NPX References")
            report.append("All legacy npx references have been successfully migrated.")
            report.append("")
        
        # Invalid formats
        if result.invalid_uvx_formats:
            report.append("## ❌ Invalid UVX Formats Found")
            report.append(f"Found {len(result.invalid_uvx_formats)} invalid uvx formats:")
            for ref in result.invalid_uvx_formats:
                report.append(f"- {ref}")
            report.append("")
        else:
            report.append("## ✅ All UVX Commands Valid")
            report.append("All uvx commands use the correct Git repository format.")
            report.append("")
        
        # Performance check
        if result.processing_time <= 5.0:
            report.append("## ✅ Performance Requirement Met")
            report.append(f"Validation completed in {result.processing_time:.2f}s (≤ 5s requirement)")
        else:
            report.append("## ❌ Performance Requirement Not Met")
            report.append(f"Validation took {result.processing_time:.2f}s (> 5s requirement)")
        
        return "\n".join(report)


def main():
    """CLI entry point for migration validation."""
    import sys
    
    validator = MigrationValidator()
    result = validator.validate_migration()
    report = validator.generate_report(result)
    
    print(report)
    
    # Exit with error code if migration is not complete
    sys.exit(0 if result.migration_complete else 1)


if __name__ == "__main__":
    main()