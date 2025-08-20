"""Spec file parsing and status tracking.

This module provides comprehensive parsing of spec files (requirements.md,
design.md, tasks.md) to extract status information, progress metrics, and
content structure for dashboard display, exactly matching TypeScript parser.ts.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from pydantic import BaseModel

from ..git import GitUtils


def debug(message: str) -> None:
    """Debug logging function matching TypeScript implementation."""
    print(f"[DEBUG] {message}")


@dataclass
class Task:
    """Task information parsed from tasks.md files."""
    id: str
    description: str
    completed: bool
    requirements: List[str] = field(default_factory=list)
    leverage: Optional[str] = None
    subtasks: Optional[List['Task']] = None


@dataclass
class RequirementDetail:
    """Detailed requirement information from requirements.md files."""
    id: str
    title: str
    user_story: Optional[str] = None
    acceptance_criteria: List[str] = field(default_factory=list)


@dataclass
class CodeReuseCategory:
    """Code reuse analysis categories from design.md files."""
    title: str
    items: List[str] = field(default_factory=list)


class SteeringStatus(BaseModel):
    """Status of steering documents in the project."""
    exists: bool = False
    has_product: bool = False
    has_tech: bool = False
    has_structure: bool = False


class SpecStatus(BaseModel):
    """Complete status information for a specification."""
    name: str
    display_name: str
    status: str = 'not-started'  # not-started, requirements, design, tasks, in-progress, completed
    requirements: Optional[Dict] = None
    design: Optional[Dict] = None
    tasks: Optional[Dict] = None
    last_modified: Optional[datetime] = None


class SpecParser:
    """Parser for extracting status information from spec files."""
    
    def __init__(self, project_path: Union[str, Path]) -> None:
        """Initialize the parser with project path.
        
        Args:
            project_path: Path to the project root directory.
        """
        # Normalize and resolve the project path to handle different path formats (matching TypeScript)
        self.project_path = Path(project_path).resolve()
        self.specs_path = self.project_path / '.claude' / 'specs'
        self.git_utils = GitUtils(self.project_path)
    
    async def get_project_steering_status(self) -> SteeringStatus:
        """Get the status of steering documents in the project.
        
        Returns:
            SteeringStatus object indicating which steering documents exist.
        """
        return await self._get_steering_status()
    
    async def get_all_specs(self) -> List[SpecStatus]:
        """Get status information for all specifications in the project (matching TypeScript method name).
        
        Returns:
            List of SpecStatus objects sorted by last modified date.
        """
        try:
            # Check if specs directory exists first (matching TypeScript logic)
            if not self.specs_path.exists():
                # Specs directory doesn't exist, return empty array
                return []
            
            debug(f'Reading specs from: {self.specs_path}')
            dirs = [d.name for d in self.specs_path.iterdir() 
                   if d.is_dir() and not d.name.startswith('.')]
            debug(f'Found directories: {dirs}')
            
            # Parse all specs (matching TypeScript Promise.all pattern)
            specs = []
            for dir_name in dirs:
                spec = await self.get_spec(dir_name)
                if spec:
                    specs.append(spec)
            
            valid_specs = [spec for spec in specs if spec is not None]
            debug(f'Parsed specs: {len(valid_specs)}')
            
            # Sort by last modified date, newest first (matching TypeScript logic)
            valid_specs.sort(key=lambda a: (
                a.last_modified.timestamp() if a.last_modified else 0
            ), reverse=True)
            
            return valid_specs
            
        except Exception as error:
            print(f"Error reading specs from {self.specs_path}: {error}")
            return []
    
    async def get_spec(self, name: str) -> Optional[SpecStatus]:
        """Get status information for a specific specification.
        
        Args:
            name: Name of the specification directory.
            
        Returns:
            SpecStatus object or None if spec doesn't exist.
        """
        spec_path = self.specs_path / name
        
        if not spec_path.exists():
            return None
        
        spec = SpecStatus(
            name=name,
            display_name=self._format_display_name(name),
            status='not-started'
        )
        
        # Check requirements
        requirements_path = spec_path / 'requirements.md'
        if requirements_path.exists():
            content = requirements_path.read_text(encoding='utf-8')
            
            # Extract title from first heading
            title_match = re.search(r'^# (.+?)(?:\s+Requirements)?$', content, re.MULTILINE)
            if title_match:
                spec.display_name = title_match.group(1).strip()
            
            user_stories = len(re.findall(r'(\*\*User Story:\*\*|## User Story \d+)', content))
            approved = '✅ APPROVED' in content or '**Approved:** ✓' in content
            
            spec.requirements = {
                'exists': True,
                'user_stories': user_stories,
                'approved': approved,
                'content': self._extract_requirements(content)
            }
            spec.status = 'requirements'
            
            if approved:
                spec.status = 'design'
        
        # Check design
        design_path = spec_path / 'design.md'
        if design_path.exists():
            content = design_path.read_text(encoding='utf-8')
            
            # Extract title if not found yet
            if spec.display_name == self._format_display_name(name):
                title_match = re.search(r'^# (.+?)(?:\s+Design)?$', content, re.MULTILINE)
                if title_match:
                    spec.display_name = title_match.group(1).strip()
            
            approved = '✅ APPROVED' in content
            has_code_reuse = '## Code Reuse Analysis' in content
            
            spec.design = {
                'exists': True,
                'approved': approved,
                'has_code_reuse_analysis': has_code_reuse,
                'code_reuse_content': self._extract_code_reuse_analysis(content)
            }
            
            if approved:
                spec.status = 'tasks'
        
        # Check tasks
        tasks_path = spec_path / 'tasks.md'
        if tasks_path.exists():
            debug(f'Reading tasks from: {tasks_path}')
            content = tasks_path.read_text(encoding='utf-8')
            debug(f'Tasks file content length: {len(content)}')
            debug(f'Tasks file includes APPROVED: {"✅ APPROVED" in content}')
            
            # If we still haven't found a display name, try to extract from tasks
            if spec.display_name == self._format_display_name(name):
                title_match = re.search(r'^# (.+?)(?:\s+Tasks)?$', content, re.MULTILINE)
                if title_match:
                    spec.display_name = title_match.group(1).strip()
            
            task_list = self._parse_tasks(content)
            completed = self._count_completed_tasks(task_list)
            total = self._count_total_tasks(task_list)
            
            debug(f'Parsed task counts - Total: {total}, Completed: {completed}')
            
            spec.tasks = {
                'exists': True,
                'approved': '✅ APPROVED' in content,
                'total': total,
                'completed': completed,
                'task_list': task_list
            }
            
            if spec.tasks['approved']:
                if completed == 0:
                    spec.status = 'tasks'
                elif completed < total:
                    spec.status = 'in-progress'
                    # Find current task
                    spec.tasks['in_progress'] = self._find_in_progress_task(task_list)
                else:
                    spec.status = 'completed'
        
        # Get last modified time (matching TypeScript logic exactly)
        files = ['requirements.md', 'design.md', 'tasks.md']
        last_modified = datetime.fromtimestamp(0)  # Unix epoch like new Date(0)
        for file_name in files:
            file_path = spec_path / file_name
            if file_path.exists():
                stats = file_path.stat()
                if datetime.fromtimestamp(stats.st_mtime) > last_modified:
                    last_modified = datetime.fromtimestamp(stats.st_mtime)
        spec.last_modified = last_modified
        
        return spec
    
    def _parse_tasks(self, content: str) -> List[Task]:
        """Parse tasks from tasks.md content (matching TypeScript method name).
        
        Args:
            content: Content of the tasks.md file.
            
        Returns:
            List of Task objects with hierarchy.
        """
        debug('Parsing tasks from content...')
        tasks = []
        lines = content.split('\n')
        debug(f'Total lines: {len(lines)}')
        
        # Let's test what the actual lines look like (matching TypeScript debug)
        for i, line in enumerate(lines[:20]):
            if '[' in line and ']' in line:
                debug(f'Line {i}: "{line}"')
        
        # Match the actual format: "- [x] 1. Create GraphQL queries..." or "- [ ] **1. Task description**"
        task_regex = re.compile(r'^(\s*)- \[([ x])\] (?:\*\*)?(\d+(?:\.\d+)*)\. (.+?)(?:\*\*)?$')
        requirements_regex = re.compile(r'_Requirements: ([\d., ]+)')
        leverage_regex = re.compile(r'_Leverage: (.+)$')
        
        current_task = None
        parent_stack = []  # List of {'level': int, 'task': Task} dicts
        
        for line in lines:
            match = task_regex.match(line)
            if match:
                indent, checked, task_id, description = match.groups()
                level = len(indent) // 2
                
                current_task = Task(
                    id=task_id,
                    description=description.strip(),
                    completed=checked == 'x',
                    requirements=[]
                )
                
                # Find parent based on level (matching TypeScript logic)
                while len(parent_stack) > 0 and parent_stack[-1]['level'] >= level:
                    parent_stack.pop()
                
                if parent_stack:
                    parent = parent_stack[-1]['task']
                    if parent.subtasks is None:
                        parent.subtasks = []
                    parent.subtasks.append(current_task)
                else:
                    tasks.append(current_task)
                
                parent_stack.append({'level': level, 'task': current_task})
            
            elif current_task:
                # Check for requirements
                req_match = requirements_regex.search(line)
                if req_match:
                    current_task.requirements = [r.strip() for r in req_match.group(1).split(',')]
                
                # Check for leverage
                lev_match = leverage_regex.search(line)
                if lev_match:
                    current_task.leverage = lev_match.group(1).strip()
        
        return tasks
    
    def _count_completed_tasks(self, tasks: List[Task]) -> int:
        """Count completed tasks recursively.
        
        Args:
            tasks: List of Task objects.
            
        Returns:
            Number of completed tasks.
        """
        count = 0
        for task in tasks:
            if task.completed:
                count += 1
            if task.subtasks:
                count += self._count_completed_tasks(task.subtasks)
        return count
    
    def _count_total_tasks(self, tasks: List[Task]) -> int:
        """Count total tasks recursively.
        
        Args:
            tasks: List of Task objects.
            
        Returns:
            Total number of tasks.
        """
        count = len(tasks)
        for task in tasks:
            if task.subtasks:
                count += self._count_total_tasks(task.subtasks)
        return count
    
    def _find_in_progress_task(self, tasks: List[Task]) -> Optional[str]:
        """Find the first incomplete task ID.
        
        Args:
            tasks: List of Task objects.
            
        Returns:
            ID of first incomplete task or None.
        """
        for task in tasks:
            if not task.completed:
                return task.id
            if task.subtasks:
                sub_task_id = self._find_in_progress_task(task.subtasks)
                if sub_task_id:
                    return sub_task_id
        return None
    
    def _format_display_name(self, name: str) -> str:
        """Format spec name for display.
        
        Args:
            name: Raw spec directory name.
            
        Returns:
            Formatted display name.
        """
        return ' '.join(word.capitalize() for word in name.split('-'))
    
    def _extract_requirements(self, content: str) -> List[RequirementDetail]:
        """Extract requirement details from requirements.md content (matching TypeScript method name).
        
        Args:
            content: Content of requirements.md file.
            
        Returns:
            List of requirement details.
        """
        requirements = []
        lines = content.split('\n')
        current_requirement = None
        in_acceptance_criteria = False
        
        debug('Extracting requirements from content...')
        
        for i, line in enumerate(lines):
            # Check if line contains a numbered requirement - try multiple patterns
            requirement_patterns = [
                re.compile(r'^### Requirement (\d+): (.+)$'),           # ### Requirement 1: Title
                re.compile(r'^## Requirement (\d+): (.+)$'),            # ## Requirement 1: Title
                re.compile(r'^### (\d+)\. (.+)$'),                      # ### 1. Title
                re.compile(r'^## (\d+)\. (.+)$'),                       # ## 1. Title
            ]
            
            match_found = False
            for pattern in requirement_patterns:
                match = pattern.match(line)
                if match:
                    # Save previous requirement
                    if current_requirement:
                        requirements.append(current_requirement)
                    
                    current_requirement = RequirementDetail(
                        id=match.group(1),
                        title=match.group(2).strip(),
                        acceptance_criteria=[]
                    )
                    debug(f'Found requirement {match.group(1)}: {match.group(2).strip()}')
                    in_acceptance_criteria = False
                    match_found = True
                    break
            
            if not match_found:
                # Look for user story
                if current_requirement and '**User Story:**' in line:
                    current_requirement.user_story = line.replace('**User Story:**', '').strip()
                # Look for acceptance criteria section
                elif current_requirement and '#### Acceptance Criteria' in line:
                    in_acceptance_criteria = True
                # Collect acceptance criteria items
                elif current_requirement and in_acceptance_criteria and re.match(r'^\d+\. ', line):
                    current_requirement.acceptance_criteria.append(re.sub(r'^\d+\. ', '', line).strip())
                # Stop at next major section
                elif line.startswith('### Requirement') or line.startswith('### ') or line.startswith('## '):
                    in_acceptance_criteria = False
        
        # Don't forget the last requirement
        if current_requirement:
            requirements.append(current_requirement)
        
        debug(f'Extracted {len(requirements)} requirements: {[f"{r.id}: {r.title}" for r in requirements]}')
        return requirements
    
    def _extract_code_reuse_analysis(self, content: str) -> List[CodeReuseCategory]:
        """Extract code reuse analysis from design.md content.
        
        Args:
            content: Content of design.md file.
            
        Returns:
            List of code reuse categories.
        """
        categories = []
        lines = content.split('\n')
        in_code_reuse_section = False
        current_category = None
        
        for line in lines:
            if '## Code Reuse Analysis' in line:
                in_code_reuse_section = True
                continue
            
            if in_code_reuse_section:
                # Stop at next major section
                if line.startswith('## ') and 'Code Reuse' not in line:
                    break
                
                # Look for numbered categories
                category_match = re.match(r'^\d+\.\s*\*\*(.+?)\*\*', line)
                if category_match:
                    if current_category:
                        categories.append(current_category)
                    current_category = CodeReuseCategory(
                        title=category_match.group(1).strip(),
                        items=[]
                    )
                # Look for bullet points under categories
                elif current_category and (line.startswith('   - ') or line.startswith('  - ')):
                    item = re.sub(r'^\s*-\s*', '', line).strip()
                    if item:
                        # Clean up markdown formatting
                        clean_item = re.sub(r'`([^`]+)`', r'\1', item)  # Remove backticks
                        clean_item = re.sub(r'\*\*([^*]+)\*\*', r'\1', clean_item)  # Remove bold
                        current_category.items.append(clean_item.strip())
        
        # Add the last category
        if current_category:
            categories.append(current_category)
        
        return categories
    
    async def _get_steering_status(self) -> SteeringStatus:
        """Get the status of steering documents.
        
        Returns:
            SteeringStatus indicating which documents exist.
        """
        steering_path = self.project_path / '.claude' / 'steering'
        
        if not steering_path.exists():
            return SteeringStatus()
        
        return SteeringStatus(
            exists=True,
            has_product=(steering_path / 'product.md').exists(),
            has_tech=(steering_path / 'tech.md').exists(),
            has_structure=(steering_path / 'structure.md').exists()
        )