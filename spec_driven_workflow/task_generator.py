"""Task generation and parsing system for dynamic command creation.

This module handles parsing tasks from markdown files and generating
individual task commands without NPX dependency. Converted from
reference/src/task-generator.ts to maintain identical parsing logic.
"""

import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class ParsedTask:
    """Represents a parsed task from tasks.md file.
    
    This dataclass matches the TypeScript ParsedTask interface
    to maintain data structure compatibility.
    """
    id: str
    description: str
    leverage: Optional[str] = None
    requirements: Optional[str] = None


def parse_tasks_from_markdown(content: str) -> List[ParsedTask]:
    """Parse tasks from a tasks.md markdown file.
    
    Handles various formats agents might produce:
    - [ ] 1. Task description
    - [ ] 2.1 Subtask description  
      - Details
      - _Requirements: 1.1, 2.2_
      - _Leverage: existing component X_
    
    Args:
        content: Raw markdown content from tasks.md file.
        
    Returns:
        List of parsed task objects.
    """
    tasks: List[ParsedTask] = []
    lines = content.split('\n')
    
    current_task: Optional[ParsedTask] = None
    is_collecting_task_content = False
    
    for i in range(len(lines)):
        line = lines[i]
        trimmed_line = line.strip()
        
        # Match task lines with flexible format:
        # Supports: "- [ ] 1. Task", "- [] 1 Task", "- [ ] 1.1. Task", etc.
        # Also handles various spacing and punctuation
        task_match = re.match(r'^-\s*\[\s*\]\s*([0-9]+(?:\.[0-9]+)*)\s*\.?\s*(.+)$', trimmed_line)
        
        if task_match:
            # If we have a previous task, save it
            if current_task:
                tasks.append(current_task)
            
            # Start new task
            task_id = task_match.group(1)
            task_description = task_match.group(2).strip()
            
            current_task = ParsedTask(
                id=task_id,
                description=task_description
            )
            is_collecting_task_content = True
        
        # If we're in a task, look for metadata anywhere in the task block
        elif current_task and is_collecting_task_content:
            # Check if this line starts a new task section (to stop collecting)
            if re.match(r'^-\s*\[\s*\]\s*[0-9]', trimmed_line):
                # This is the start of a new task, process it in the next iteration
                i -= 1
                is_collecting_task_content = False
                continue
            
            # Check for _Requirements: anywhere in the line
            requirements_match = re.search(r'_Requirements:\s*(.+?)(?:_|$)', line)
            if requirements_match:
                current_task.requirements = requirements_match.group(1).strip()
            
            # Check for _Leverage: anywhere in the line
            leverage_match = re.search(r'_Leverage:\s*(.+?)(?:_|$)', line)
            if leverage_match:
                current_task.leverage = leverage_match.group(1).strip()
            
            # Stop collecting if we hit an empty line followed by non-indented content
            if trimmed_line == '' and i + 1 < len(lines):
                next_line = lines[i + 1]
                if (len(next_line) > 0 and 
                    next_line[0] not in [' ', '\t'] and 
                    not next_line.startswith('  -')):
                    is_collecting_task_content = False
    
    # Don't forget the last task
    if current_task:
        tasks.append(current_task)
    
    # Log parsing results for debugging
    print(f"Parsed {len(tasks)} tasks from markdown")
    if len(tasks) == 0 and content.strip():
        print("Warning: No tasks found. Content preview:")
        print(content[:500] + "...")
    
    return tasks


async def generate_task_command(
    commands_dir: Path,
    spec_name: str,
    task: ParsedTask
) -> None:
    """Generate a command file for a specific task.
    
    Args:
        commands_dir: Directory to write command files to.
        spec_name: Name of the specification.
        task: Parsed task object to generate command for.
    """
    command_file = commands_dir / f"task-{task.id}.md"
    
    content = f"""# {spec_name} - Task {task.id}

Execute task {task.id} for the {spec_name} specification.

## Task Description
{task.description}

"""

    # Add Code Reuse section if leverage info exists
    if task.leverage:
        content += f"""## Code Reuse
**Leverage existing code**: {task.leverage}

"""

    # Add Requirements section if requirements exist
    if task.requirements:
        content += f"""## Requirements Reference
**Requirements**: {task.requirements}

"""

    content += f"""## Usage
```
/{spec_name}-task-{task.id}
```

## Instructions
This command executes a specific task from the {spec_name} specification.

**Automatic Execution**: This command will automatically execute:
```
/spec-execute {task.id} {spec_name}
```

**Context Loading**:
Before executing the task, you MUST load all relevant context:
1. **Specification Documents**:
   - Load `.claude/specs/{spec_name}/requirements.md` for feature requirements
   - Load `.claude/specs/{spec_name}/design.md` for technical design
   - Load `.claude/specs/{spec_name}/tasks.md` for the complete task list
2. **Steering Documents** (if available):
   - Load `.claude/steering/product.md` for product vision context
   - Load `.claude/steering/tech.md` for technical standards
   - Load `.claude/steering/structure.md` for project conventions

**Process**:
1. Load all context documents listed above
2. Execute task {task.id}: "{task.description}"
3. **Prioritize code reuse**: Use existing components and utilities identified above
4. Follow all implementation guidelines from the main /spec-execute command
5. **Follow steering documents**: Adhere to patterns in tech.md and conventions in structure.md
6. **CRITICAL**: Mark the task as complete in tasks.md by changing [ ] to [x]
7. Confirm task completion to user
8. Stop and wait for user review

**Important Rules**:
- Execute ONLY this specific task
- **Leverage existing code** whenever possible to avoid rebuilding functionality
- **Follow project conventions** from steering documents
- Mark task as complete by changing [ ] to [x] in tasks.md
- Stop after completion and wait for user approval
- Do not automatically proceed to the next task
- Validate implementation against referenced requirements

## Task Completion Protocol
When completing this task:
1. **Update tasks.md**: Change task {task.id} status from `- [ ]` to `- [x]`
2. **Confirm to user**: State clearly "Task {task.id} has been marked as complete"
3. **Stop execution**: Do not proceed to next task automatically
4. **Wait for instruction**: Let user decide next steps

## Next Steps
After task completion, you can:
- Review the implementation
- Run tests if applicable
- Execute the next task using /{spec_name}-task-[next-id]
- Check overall progress with /spec-status {spec_name}
"""

    # Write the command file
    command_file.write_text(content, encoding='utf-8')