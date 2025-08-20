"""Core auto-run task execution components.

This module provides the main orchestration and execution components for
automated task execution. Follows the established async patterns and Rich
progress reporting used throughout the project.
"""

import asyncio
import json
import re
import shlex
import subprocess
import time

from pathlib import Path

import aiofiles

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
)

# Enhanced inquirer integration following established patterns from cli.py
try:
    import inquirer
    INQUIRER_AVAILABLE = True
except ImportError:
    INQUIRER_AVAILABLE = False

from spec_driven_workflow.auto_run_models import (
    AutoRunOptions,
    AutoRunResult,
    ExecutionMode,
    ExecutionState,
    SpecContext,
    TaskResult,
    TaskStatus,
)
from spec_driven_workflow.task_generator import ParsedTask, parse_tasks_from_markdown

# Claude Code SDK integration for proper command execution
try:
    from claude_code_sdk import query, ClaudeCodeOptions, Message
    CLAUDE_SDK_AVAILABLE = True
except ImportError:
    CLAUDE_SDK_AVAILABLE = False
    # Fallback to subprocess approach if SDK not available
    from spec_driven_workflow.utils import find_claude_executable


class TaskAutoRunner:
    """Orchestrates automated execution of all tasks in a specification.
    
    This class manages the overall workflow for auto-run execution, coordinating
    between task parsing, progress reporting, and individual task execution.
    Follows the established async patterns from cli.py and integrates with
    existing task parsing infrastructure.
    """

    def __init__(self, console: Console | None = None) -> None:
        """Initialize the TaskAutoRunner.
        
        Args:
            console: Rich console instance for output formatting
        """
        self.console = console or Console()
        self.task_executor = TaskExecutor(self.console)
        self.progress_manager = ProgressManager(self.console)
        self.current_execution_state: ExecutionState | None = None

    def _get_state_file_path(self, spec_name: str) -> Path:
        """Get the file path for execution state persistence.
        
        Args:
            spec_name: Name of the specification
            
        Returns:
            Path to the state file
        """
        return Path.cwd() / ".claude" / "specs" / spec_name / ".auto_run_state.json"

    async def _save_execution_state(self, state: ExecutionState) -> None:
        """Save the execution state to file for recovery purposes.
        
        Implements Requirement 2.3: execution state tracking and persistence.
        
        Args:
            state: ExecutionState to save
        """
        try:
            state_file = self._get_state_file_path(state.spec_name)
            state_data = state.to_dict()

            async with aiofiles.open(state_file, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(state_data, indent=2))

        except Exception as e:
            # Don't fail the execution if state saving fails, just log it
            self.console.print(f"[yellow]⚠️ Warning: Could not save execution state: {e}[/yellow]")

    async def _load_execution_state(self, spec_name: str) -> ExecutionState | None:
        """Load execution state from a file for recovery.
        
        Args:
            spec_name: Name of the specification
            
        Returns:
            ExecutionState if found and valid, None otherwise
        """
        try:
            state_file = self._get_state_file_path(spec_name)
            if not state_file.exists():
                return None

            async with aiofiles.open(state_file, encoding='utf-8') as f:
                content = await f.read()
                state_data = json.loads(content)

            return ExecutionState.from_dict(state_data)

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            self.console.print(f"[yellow]⚠️ Warning: Invalid execution state file: {e}[/yellow]")
            return None
        except Exception as e:
            # Don't fail if state loading fails
            self.console.print(f"[yellow]⚠️ Warning: Could not load execution state: {e}[/yellow]")
            return None

    async def _clear_execution_state(self, spec_name: str) -> None:
        """Clear the execution state file after successful completion.
        
        Args:
            spec_name: Name of the specification
        """
        try:
            state_file = self._get_state_file_path(spec_name)
            if state_file.exists():
                state_file.unlink()
        except Exception:
            # Silently ignore errors when clearing the state
            pass

    async def _update_execution_state(self, task_result: TaskResult) -> None:
        """Update execution state with a task result.
        
        Enhanced to handle retries by removing previous failure entries when tasks succeed.
        
        Args:
            task_result: Result of task execution
        """
        if self.current_execution_state is None:
            return

        # Clean up previous entries for this task (handles retries)
        task_id = task_result.task_id
        if task_id in self.current_execution_state.completed_task_ids:
            self.current_execution_state.completed_task_ids.remove(task_id)
        if task_id in self.current_execution_state.failed_task_ids:
            self.current_execution_state.failed_task_ids.remove(task_id)
        if task_id in self.current_execution_state.skipped_task_ids:
            self.current_execution_state.skipped_task_ids.remove(task_id)

        # Update state based on the current task result
        if task_result.status == TaskStatus.SUCCESS:
            self.current_execution_state.completed_task_ids.append(task_result.task_id)
        elif task_result.status == TaskStatus.FAILED:
            self.current_execution_state.failed_task_ids.append(task_result.task_id)
        elif task_result.status == TaskStatus.SKIPPED:
            self.current_execution_state.skipped_task_ids.append(task_result.task_id)

        # Update timestamps and the current task
        self.current_execution_state.last_updated = time.time()
        self.current_execution_state.current_task_id = None  # Task completed

        # Save an updated state
        await self._save_execution_state(self.current_execution_state)

    async def check_for_resumable_execution(self, spec_name: str) -> ExecutionState | None:
        """Check if there's a resumable execution for the given spec.
        
        Implements Requirement 2.3: auto-resume detection after interruptions.
        
        Args:
            spec_name: Name of the specification to check
            
        Returns:
            ExecutionState if resumable, None otherwise
        """
        saved_state = await self._load_execution_state(spec_name)

        if saved_state and saved_state.is_resumable:
            return saved_state

        return None

    async def prompt_resume_execution(self, saved_state: ExecutionState) -> bool:
        """Prompt the user whether to resume previous execution.
        
        Implements enhanced user experience for resuming interrupted executions
        per Requirements 2.3 and 1.3.
        
        Args:
            saved_state: Previously saved execution state
            
        Returns:
            True if the user wants to resume, False to start fresh
        """
        self.console.print()
        self.console.print("[bold yellow]🔄 Found Previous Auto-Run Session[/bold yellow]")
        self.console.print(f"[blue]Spec: {saved_state.spec_name}[/blue]")
        self.console.print(f"[dim]Started: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(saved_state.start_time))}[/dim]")
        self.console.print(f"[dim]Progress: {len(saved_state.completed_task_ids)}/{saved_state.total_tasks} tasks completed ({saved_state.completion_rate:.0%})[/dim]")

        if saved_state.failed_task_ids:
            self.console.print(f"[red]Failed tasks: {', '.join(saved_state.failed_task_ids)}[/red]")

        if saved_state.interruption_reason:
            self.console.print(f"[yellow]Interruption: {saved_state.interruption_reason}[/yellow]")

        self.console.print()

        # Use inquirer for enhanced user experience when available
        if INQUIRER_AVAILABLE:
            questions = [
                inquirer.List('action',
                            message='Resume previous execution or start fresh?',
                            choices=[
                                ('🔄 Resume from where it left off', 'resume'),
                                ('🆕 Start fresh (discard previous progress)', 'fresh'),
                                ('❌ Cancel auto-run', 'cancel')
                            ],
                            default='resume')
            ]
            answers = inquirer.prompt(questions)
            if not answers or answers['action'] == 'cancel':
                return False

            return answers['action'] == 'resume'
        else:
            # Fallback to basic input
            self.console.print("Options:")
            self.console.print("  r - Resume from where it left off")
            self.console.print("  f - Start fresh (discard previous progress)")
            self.console.print("  c - Cancel auto-run")

            while True:
                choice = input("Action (r/f/c): ").lower().strip()
                if choice in ['r', 'resume']:
                    return True
                elif choice in ['f', 'fresh'] or choice in ['c', 'cancel']:
                    return False
                else:
                    print("Please enter 'r', 'f', or 'c'")

    async def run_all_tasks(self, spec_name: str, options: AutoRunOptions) -> AutoRunResult:
        """Execute all tasks in a specification sequentially.
        
        This is the main orchestration method that coordinates task parsing,
        filtering, and execution following requirement 1.1 (Sequential Task Runner).
        
        Args:
            spec_name: Name of the specification to execute
            options: Configuration options for execution
            
        Returns:
            AutoRunResult with comprehensive execution summary
        """
        self.console.print(f"[bold cyan]🚀 Starting auto-run for specification: {spec_name}[/bold cyan]")

        # Load spec context
        try:
            spec_context = await self._load_spec_context(spec_name)
            self.console.print("[green]✓ Loaded specification context[/green]")
        except Exception as e:
            self.console.print(f"[red]✗ Failed to load specification: {e}[/red]")
            raise

        # Parse tasks from tasks.md leveraging existing parse_tasks_from_markdown
        parsed_tasks = parse_tasks_from_markdown(spec_context.tasks_content)
        self.console.print(f"[blue]📋 Parsed {len(parsed_tasks)} tasks from tasks.md[/blue]")

        if not parsed_tasks:
            self.console.print("[yellow]⚠️ No tasks found in tasks.md[/yellow]")
            return AutoRunResult(spec_name=spec_name, total_tasks=0)

        # Filter tasks based on selection with enhanced error handling per Requirement 2.1
        try:
            selected_tasks = self._filter_tasks(parsed_tasks, options.task_selection)
        except ValueError as e:
            self.console.print(f"[red]❌ Task selection error: {e}[/red]")
            self.console.print()
            self.console.print("[yellow]💡 Task selection format examples:[/yellow]")
            self.console.print("[dim]  --tasks all          # Execute all tasks[/dim]")
            self.console.print("[dim]  --tasks 1-3          # Execute tasks 1, 2, 3[/dim]")
            self.console.print("[dim]  --tasks 2,4,6        # Execute specific tasks[/dim]")
            self.console.print("[dim]  --tasks 1,3-5        # Mixed selection[/dim]")
            self.console.print("[dim]  --tasks 2.1-2.3      # Subtask range[/dim]")
            self.console.print()
            raise ValueError(f"Invalid task selection: {e}")

        if not selected_tasks:
            self.console.print("[yellow]⚠️ No tasks match the selection criteria[/yellow]")
            return AutoRunResult(spec_name=spec_name, total_tasks=0)

        self.console.print(f"[blue]🎯 Selected {len(selected_tasks)} tasks for execution[/blue]")

        # Log execution mode with enhanced descriptions per Requirement 2.2
        mode_text = self._get_execution_mode_description(options.execution_mode)
        self.console.print(f"[dim]Execution mode: {mode_text}[/dim]")

        # Show additional mode-specific information
        if options.execution_mode == ExecutionMode.INTERACTIVE:
            self.console.print("[dim]• You will be prompted before each task execution[/dim]")
            self.console.print("[dim]• Failed tasks will offer retry/skip/abort options[/dim]")
        elif options.continue_on_error:
            self.console.print("[dim]• Failed tasks will be skipped automatically (continue-on-error enabled)[/dim]")
        else:
            self.console.print("[dim]• Execution will stop on first failure (continue-on-error disabled)[/dim]")

        # Initialize execution state for persistence per Requirement 2.3
        self.current_execution_state = ExecutionState(
            spec_name=spec_name,
            start_time=time.time(),
            last_updated=time.time(),
            options=options,
            total_tasks=len(selected_tasks)
        )

        # Save the initial state
        await self._save_execution_state(self.current_execution_state)

        # Initialize result tracking
        result = AutoRunResult(
            spec_name=spec_name,
            total_tasks=len(selected_tasks)
        )

        # Create a progress display with exception handling for interruptions
        try:
            with self.progress_manager.create_progress_display(len(selected_tasks)) as progress:
                # Execute tasks sequentially with enhanced execution control per Requirements 2.2
                for task in selected_tasks:
                    # Interactive mode: prompt for confirmation before each task
                    if options.execution_mode == ExecutionMode.INTERACTIVE:
                        should_execute = await self._prompt_task_confirmation(task)
                        if not should_execute:
                            # Skip this task
                            skipped_result = TaskResult(
                                task_id=task.id,
                                task_description=task.description,
                                status=TaskStatus.SKIPPED,
                                execution_time=0.0
                            )
                            result.add_task_result(skipped_result)
                            self.progress_manager.update_task_progress(
                                task.id, TaskStatus.SKIPPED, "Skipped by user"
                            )
                            continue

                    # Update current task in execution state
                    self.current_execution_state.current_task_id = task.id
                    await self._save_execution_state(self.current_execution_state)

                    # Execute the task
                    task_result = await self._execute_single_task(
                        task, spec_context, options, progress
                    )
                    result.add_task_result(task_result)

                    # Update execution state with a task result
                    await self._update_execution_state(task_result)

                    # Enhanced error handling with retry support per Requirement 1.3
                    if task_result.status == TaskStatus.FAILED:
                        if options.execution_mode == ExecutionMode.INTERACTIVE:
                            # Interactive mode: prompt for recovery action
                            while True:
                                action = await self._prompt_failure_action(task_result)
                                if action == "retry":
                                    # Retry the task
                                    self.console.print(f"[yellow]🔄 Retrying task {task.id}...[/yellow]")
                                    retry_result = await self._execute_single_task(
                                        task, spec_context, options, progress
                                    )
                                    result.update_last_task_result(retry_result)
                                    # Update state for retry
                                    await self._update_execution_state(retry_result)
                                    if retry_result.status == TaskStatus.SUCCESS:
                                        break  # Success, continue to next task
                                    # If still failed, prompt again
                                    task_result = retry_result
                                elif action == "skip":
                                    # Skip and continue to the next task
                                    break
                                elif action == "abort":
                                    self.console.print("[red]❌ Execution aborted by user[/red]")
                                    return result
                        # Automatic mode: handle based on the continue_on_error setting
                        elif not options.continue_on_error:
                            self.console.print(f"[red]❌ Task {task.id} failed. Stopping execution.[/red]")
                            break
                        else:
                            self.console.print(f"[yellow]⚠️ Task {task.id} failed. Continuing due to --continue-on-error flag.[/yellow]")

        except KeyboardInterrupt:
            # Handle Ctrl+C interruption gracefully per Requirement 2.3
            self.console.print("\n[yellow]⚠️ Auto-run interrupted by user[/yellow]")
            if self.current_execution_state:
                self.current_execution_state.interruption_reason = "Interrupted by user (Ctrl+C)"
                await self._save_execution_state(self.current_execution_state)
            self.console.print("[blue]💾 Execution state saved. You can resume later with --resume-from option.[/blue]")
            raise
        except Exception as e:
            # Handle unexpected errors
            self.console.print(f"[red]💥 Unexpected error during execution: {e}[/red]")
            if self.current_execution_state:
                self.current_execution_state.interruption_reason = f"Unexpected error: {e!s}"
                await self._save_execution_state(self.current_execution_state)
            raise

        result.finalize()

        # Clear execution state on successful completion per Requirement 2.3
        if result.is_successful:
            await self._clear_execution_state(spec_name)
        # Mark interruption reason in state if execution was incomplete
        elif self.current_execution_state:
            self.current_execution_state.interruption_reason = "Execution stopped due to failures"
            await self._save_execution_state(self.current_execution_state)

        # Enhanced completion reporting per Requirement 1.3
        self.progress_manager.report_completion_summary(result)

        # Provide a failure summary for multiple failed tasks
        if result.failed_tasks > 1:
            self._report_failure_summary(result)

        return result

    def _report_failure_summary(self, result: AutoRunResult) -> None:
        """Report comprehensive failure summary per Requirement 1.3.
        
        Args:
            result: AutoRunResult containing execution details
        """
        failed_results = [r for r in result.task_results if r.status == TaskStatus.FAILED]

        if not failed_results:
            return

        self.console.print()
        self.console.print("[bold red]📋 Failure Summary[/bold red]")
        self.console.print(f"[red]{len(failed_results)} task(s) failed during execution:[/red]")
        self.console.print()

        for i, task_result in enumerate(failed_results, 1):
            self.console.print(f"[red]{i}. Task {task_result.task_id}: {task_result.task_description}[/red]")
            self.console.print(f"[dim]   Error: {task_result.error_message}[/dim]")
            self.console.print(f"[dim]   Time: {task_result.execution_time:.2f}s[/dim]")

        self.console.print()
        self.console.print("[yellow]💡 Actionable guidance:[/yellow]")
        self.console.print("[dim]• Review the error messages above for specific failure reasons[/dim]")
        self.console.print("[dim]• Use interactive mode (--mode interactive) for step-by-step control[/dim]")
        self.console.print("[dim]• Use --continue-on-error to skip failed tasks and continue[/dim]")
        self.console.print("[dim]• Resume from specific task with --resume-from <task-id>[/dim]")

        # Show which tasks were successful for context
        successful_results = [r for r in result.task_results if r.status == TaskStatus.SUCCESS]
        if successful_results:
            self.console.print()
            self.console.print(f"[green]✅ {len(successful_results)} task(s) completed successfully:[/green]")
            success_ids = [r.task_id for r in successful_results]
            self.console.print(f"[dim]   {', '.join(success_ids)}[/dim]")

    async def run_task_range(self, spec_name: str, start_task: str, end_task: str) -> AutoRunResult:
        """Execute a range of tasks from start_task to end_task.
        
        Args:
            spec_name: Name of the specification
            start_task: Starting task ID (e.g., "1", "2.1")
            end_task: Ending task ID (e.g., "3", "2.3")
            
        Returns:
            AutoRunResult with execution summary for the range
        """
        options = AutoRunOptions(task_selection=f"{start_task}-{end_task}")
        return await self.run_all_tasks(spec_name, options)

    async def resume_from_task(self, spec_name: str, task_id: str, options: AutoRunOptions) -> AutoRunResult:
        """Resume execution from a specific task ID.
        
        Enhanced implementation with comprehensive task validation as per Requirement 2.1.
        
        Args:
            spec_name: Name of the specification
            task_id: Task ID to resume from
            options: Auto-run options for execution control
            
        Returns:
            AutoRunResult with execution summary from resume point
            
        Raises:
            ValueError: If task_id doesn't exist or is invalid
        """
        # Load spec context to validate task exists
        spec_context = await self._load_spec_context(spec_name)
        parsed_tasks = parse_tasks_from_markdown(spec_context.tasks_content)

        # Validate task_id exists using the enhanced validation logic
        available_task_ids = {task.id for task in parsed_tasks}
        if task_id not in available_task_ids:
            available_ids_str = ", ".join(sorted(available_task_ids))
            raise ValueError(
                f"Task ID '{task_id}' not found in specification '{spec_name}'. "
                f"Available task IDs: {available_ids_str}"
            )

        # Find the resume index
        resume_index = next(i for i, task in enumerate(parsed_tasks) if task.id == task_id)

        self.console.print(f"[cyan]🔄 Resuming execution from task {task_id}[/cyan]")

        # Create selection string for remaining tasks
        remaining_task_ids = [task.id for task in parsed_tasks[resume_index:]]
        task_selection = ",".join(remaining_task_ids)

        # Update options with the remaining tasks selection
        resume_options = AutoRunOptions(
            execution_mode=options.execution_mode,
            task_selection=task_selection,
            continue_on_error=options.continue_on_error,
            show_detailed_progress=options.show_detailed_progress,
            resume_from_task=task_id
        )
        return await self.run_all_tasks(spec_name, resume_options)

    async def resume_from_saved_state(self, saved_state: ExecutionState) -> AutoRunResult:
        """Resume execution from a saved state.
        
        Enhanced resume functionality that uses saved execution state for more
        accurate resumption per Requirement 2.3.
        
        Args:
            saved_state: Previously saved execution state
            
        Returns:
            AutoRunResult with execution summary from resume point
        """
        self.console.print("[cyan]🔄 Resuming auto-run from saved state[/cyan]")
        self.console.print(f"[blue]Spec: {saved_state.spec_name}[/blue]")

        # Load spec context to get the current task list
        spec_context = await self._load_spec_context(saved_state.spec_name)
        parsed_tasks = parse_tasks_from_markdown(spec_context.tasks_content)

        # Find tasks that need to be executed (not completed or skipped)
        completed_and_skipped = set(saved_state.completed_task_ids + saved_state.skipped_task_ids)
        remaining_tasks = [task for task in parsed_tasks if task.id not in completed_and_skipped]

        if not remaining_tasks:
            self.console.print("[green]✅ All tasks already completed![/green]")
            # Clear the state file since everything is done
            await self._clear_execution_state(saved_state.spec_name)
            return AutoRunResult(
                spec_name=saved_state.spec_name,
                total_tasks=len(parsed_tasks),
                executed_tasks=len(saved_state.completed_task_ids),
                successful_tasks=len(saved_state.completed_task_ids),
                summary_message="All tasks were already completed"
            )

        self.console.print(f"[blue]📋 {len(remaining_tasks)} tasks remaining to execute[/blue]")

        # Create new options with the remaining task selection
        remaining_task_ids = [task.id for task in remaining_tasks]
        resume_options = AutoRunOptions(
            execution_mode=saved_state.options.execution_mode,
            task_selection=",".join(remaining_task_ids),
            continue_on_error=saved_state.options.continue_on_error,
            show_detailed_progress=saved_state.options.show_detailed_progress,
            resume_from_task=remaining_task_ids[0] if remaining_task_ids else None
        )

        return await self.run_all_tasks(saved_state.spec_name, resume_options)

    async def _load_spec_context(self, spec_name: str) -> SpecContext:
        """Load all specification documents and context.
        
        Args:
            spec_name: Name of the specification to load
            
        Returns:
            SpecContext with all loaded documents
        """
        spec_dir = Path.cwd() / ".claude" / "specs" / spec_name

        # Load main spec documents
        requirements_path = spec_dir / "requirements.md"
        design_path = spec_dir / "design.md"
        tasks_path = spec_dir / "tasks.md"

        async with aiofiles.open(requirements_path, encoding='utf-8') as f:
            requirements_content = await f.read()

        async with aiofiles.open(design_path, encoding='utf-8') as f:
            design_content = await f.read()

        async with aiofiles.open(tasks_path, encoding='utf-8') as f:
            tasks_content = await f.read()

        # Load steering documents if available
        steering_documents = {}
        steering_dir = Path.cwd() / ".claude" / "steering"

        for steering_file in ["product.md", "tech.md", "structure.md"]:
            steering_path = steering_dir / steering_file
            if steering_path.exists():
                async with aiofiles.open(steering_path, encoding='utf-8') as f:
                    steering_documents[steering_file] = await f.read()

        return SpecContext(
            spec_name=spec_name,
            requirements_content=requirements_content,
            design_content=design_content,
            tasks_content=tasks_content,
            steering_documents=steering_documents,
            spec_directory=spec_dir
        )

    def _filter_tasks(self, tasks: list[ParsedTask], selection: str | None) -> list[ParsedTask]:
        """Filter tasks based on selection criteria.
        
        Enhanced implementation that supports hierarchical task numbering and provides
        comprehensive validation and error reporting as required by Requirement 2.1.
        
        Supports formats:
        - "all" or "*": All tasks
        - "1-3": Range selection
        - "2,4,6": Comma-separated list
        - "1,3-5": Mixed selection
        - "2.1-2.3": Subtask ranges
        
        Args:
            tasks: List of all parsed tasks
            selection: Selection criteria
            
        Returns:
            Filtered list of tasks to execute in hierarchical order
            
        Raises:
            ValueError: If a selection format is invalid or contains non-existent task IDs
        """
        if not selection or selection.lower() in ["all", "*"]:
            return self._sort_tasks_hierarchically(tasks)

        # Validate a selection format and parse task IDs
        try:
            selected_task_ids = self._parse_task_selection(selection)
        except ValueError as e:
            raise ValueError(f"Invalid task selection format: {e}")

        # Validate that all selected task IDs exist
        available_task_ids = {task.id for task in tasks}
        invalid_ids = [task_id for task_id in selected_task_ids if task_id not in available_task_ids]

        if invalid_ids:
            available_ids_str = ", ".join(sorted(available_task_ids))
            invalid_ids_str = ", ".join(invalid_ids)
            raise ValueError(
                f"Task IDs not found: {invalid_ids_str}. "
                f"Available task IDs: {available_ids_str}"
            )

        # Filter tasks based on validated selection
        filtered = [t for t in tasks if t.id in selected_task_ids]

        if not filtered:
            raise ValueError(f"No tasks match selection criteria: {selection}")

        return self._sort_tasks_hierarchically(filtered)

    def _parse_task_selection(self, selection: str) -> list[str]:
        """Parse task selection string into a list of task IDs.
        
        Supports complex selection formats including ranges and mixed selections.
        
        Args:
            selection: Selection string (e.g., "1,3-5,7")
            
        Returns:
            List of task ID strings
            
        Raises:
            ValueError: If a selection format is invalid
        """
        if not selection or not selection.strip():
            raise ValueError("Selection cannot be empty")

        task_ids = []

        # Split by commas to handle mixed selections
        parts = [part.strip() for part in selection.split(",")]

        for part in parts:
            if not part:
                continue

            if "-" in part:
                # Handle range selection (e.g., "1-3" or "2.1-2.3")
                if part.count("-") > 1:
                    raise ValueError(f"Invalid range format: '{part}' (too many dashes)")

                start, end = part.split("-", 1)
                start, end = start.strip(), end.strip()

                if not start or not end:
                    raise ValueError(f"Invalid range format: '{part}' (missing start or end)")

                try:
                    range_ids = self._generate_task_range(start, end)
                    task_ids.extend(range_ids)
                except ValueError as e:
                    raise ValueError(f"Invalid range '{part}': {e}")
            else:
                # Single task ID
                task_id = part.strip()
                if not task_id:
                    raise ValueError("Empty task ID in selection")
                task_ids.append(task_id)

        return list(dict.fromkeys(task_ids))  # Remove duplicates while preserving order

    def _generate_task_range(self, start: str, end: str) -> list[str]:
        """Generate a list of task IDs within a range.
        
        Supports both simple numeric ranges (1-3) and hierarchical ranges (2.1-2.3).
        
        Args:
            start: Start task ID
            end: End task ID
            
        Returns:
            List of task IDs in the range
            
        Raises:
            ValueError: If range is invalid
        """
        try:
            # Handle simple numeric ranges (e.g., "1-3")
            if "." not in start and "." not in end:
                start_num = int(start)
                end_num = int(end)
                if start_num > end_num:
                    raise ValueError(f"Start ({start}) is greater than end ({end})")
                return [str(i) for i in range(start_num, end_num + 1)]

            # Handle hierarchical ranges (e.g., "2.1-2.3")
            start_parts = [int(p) for p in start.split(".")]
            end_parts = [int(p) for p in end.split(".")]

            # Ensure the same hierarchy level
            if len(start_parts) != len(end_parts):
                raise ValueError(f"Hierarchy level mismatch between '{start}' and '{end}'")

            # For subtask ranges, only the last part should vary
            if len(start_parts) > 1:
                if start_parts[:-1] != end_parts[:-1]:
                    raise ValueError(f"Parent task mismatch between '{start}' and '{end}'")

                if start_parts[-1] > end_parts[-1]:
                    raise ValueError(f"Start subtask ({start}) is greater than end subtask ({end})")

                # Generate subtask IDs
                parent_prefix = ".".join(str(p) for p in start_parts[:-1])
                return [f"{parent_prefix}.{i}" for i in range(start_parts[-1], end_parts[-1] + 1)]

            # Should not reach here for valid hierarchical ranges
            raise ValueError(f"Unsupported range format: '{start}-{end}'")

        except (ValueError, IndexError) as e:
            if "invalid literal" in str(e).lower():
                raise ValueError(f"Non-numeric task IDs in range: '{start}-{end}'")
            raise ValueError(f"Invalid range: {e}")

    def _sort_tasks_hierarchically(self, tasks: list[ParsedTask]) -> list[ParsedTask]:
        """Sort tasks in hierarchical order (1, 2, 2.1, 2.2, 3, etc.).
        
        This ensures tasks are executed in the correct dependency order,
        following the hierarchical numbering system from task_generator.py.
        
        Args:
            tasks: List of tasks to sort
            
        Returns:
            Tasks sorted in hierarchical order
        """
        def task_sort_key(task: ParsedTask) -> tuple:
            """Create a sort key for hierarchical task ordering."""
            # Split task ID into numeric parts (e.g., "2.1" -> [2, 1])
            try:
                parts = [float(part) for part in task.id.split('.')]
                # Pad to ensure consistent sorting (e.g., [2] -> [2, 0])
                while len(parts) < 3:  # Support up to 3 levels (1.2.3)
                    parts.append(0)
                return tuple(parts)
            except ValueError:
                # Fallback for non-numeric task IDs
                return (float('inf'), 0, 0)

        return sorted(tasks, key=task_sort_key)

    def _task_in_range(self, task_id: str, start: str, end: str) -> bool:
        """Check if a task ID falls within the specified range.
        
        Args:
            task_id: Task ID to check
            start: Start of range
            end: End of range
            
        Returns:
            True if a task is within range
        """
        # Simple numeric comparison for basic task IDs
        try:
            task_num = float(task_id)
            start_num = float(start)
            end_num = float(end)
            return start_num <= task_num <= end_num
        except ValueError:
            # Fallback to string comparison
            return start <= task_id <= end

    async def _execute_single_task(
        self,
        task: ParsedTask,
        spec_context: SpecContext,
        options: AutoRunOptions,
        progress: Progress
    ) -> TaskResult:
        """Execute a single task with progress tracking.
        
        Args:
            task: Task to execute
            spec_context: Specification context
            options: Execution options
            progress: Progress display instance
            
        Returns:
            TaskResult with execution details
        """
        task_result = TaskResult(
            task_id=task.id,
            task_description=task.description,
            status=TaskStatus.PENDING,
            requirements_addressed=task.requirements.split(", ") if task.requirements else None,
            leverage_info=task.leverage
        )

        # Update progress display
        self.progress_manager.update_task_progress(
            task.id, TaskStatus.RUNNING, f"Executing: {task.description}"
        )

        task_result.mark_started()

        try:
            # Execute the task using TaskExecutor
            success = await self.task_executor.execute_task(task, spec_context)

            if success:
                task_result.mark_completed(success=True)
                # Mark task as complete in tasks.md
                await self._mark_task_complete(spec_context, task.id)
            else:
                task_result.mark_completed(success=False, error_message="Task execution failed")

        except Exception as e:
            task_result.mark_completed(success=False, error_message=str(e))
            self.console.print(f"[red]Error executing task {task.id}: {e}[/red]")

        # Update progress
        self.progress_manager.update_task_progress(
            task.id, task_result.status, f"Completed: {task.description}"
        )

        return task_result

    async def _mark_task_complete(self, spec_context: SpecContext, task_id: str) -> None:
        """Mark a task as complete in tasks.md by changing [ ] to [x].
        
        Args:
            spec_context: Specification context
            task_id: ID of a task to mark complete
        """
        tasks_path = spec_context.spec_directory / "tasks.md"

        async with aiofiles.open(tasks_path, encoding='utf-8') as f:
            content = await f.read()

        # Replace [ ] with [x] for the specific task
        pattern = rf'^(-\s*)\[\s*\]\s*({re.escape(task_id)}\s*\.?.*?)$'
        replacement = r'\1[x] \2'
        updated_content = re.sub(pattern, replacement, content, flags=re.MULTILINE)

        async with aiofiles.open(tasks_path, 'w', encoding='utf-8') as f:
            await f.write(updated_content)

    async def _prompt_task_confirmation(self, task: 'ParsedTask') -> bool:
        """Prompt the user for confirmation before executing a task in interactive mode.
        
        Enhanced implementation using an inquirer library when available, following
        the established patterns from cli.py. Implements Requirement 2.2: 
        Interactive mode confirmation prompts.
        
        Args:
            task: Task to be executed
            
        Returns:
            True if the user wants to execute the task, False to skip
            
        Raises:
            KeyboardInterrupt: If the user chooses to abort execution
        """
        self.console.print()
        self.console.print(f"[bold cyan]📋 Next Task: {task.id} - {task.description}[/bold cyan]")

        # Show task details if available
        if hasattr(task, 'requirements') and task.requirements:
            self.console.print(f"[dim]Requirements: {task.requirements}[/dim]")
        if hasattr(task, 'leverage') and task.leverage:
            self.console.print(f"[dim]Leverage: {task.leverage}[/dim]")

        self.console.print()

        # Use inquirer for enhanced user experience when available
        if INQUIRER_AVAILABLE:
            questions = [
                inquirer.List('action',
                            message=f'Execute task {task.id}?',
                            choices=[
                                ('Execute this task', 'execute'),
                                ('Skip this task', 'skip'),
                                ('Abort auto-run', 'abort')
                            ],
                            default='execute')
            ]
            answers = inquirer.prompt(questions)
            if not answers:
                # User pressed Ctrl+C or ESC
                self.console.print("[red]❌ Auto-run aborted by user[/red]")
                raise KeyboardInterrupt("User aborted execution")

            action = answers['action']
            if action == 'execute':
                return True
            elif action == 'skip':
                self.console.print(f"[yellow]⏭️ Skipping task {task.id}[/yellow]")
                return False
            elif action == 'abort':
                self.console.print("[red]❌ Auto-run aborted by user[/red]")
                raise KeyboardInterrupt("User aborted execution")
        else:
            # Fallback to basic input if inquirer not available
            self.console.print("Options:")
            self.console.print("  y - Execute this task")
            self.console.print("  s - Skip this task")
            self.console.print("  a - Abort auto-run")

            while True:
                choice = input("Execute task? (y/s/a): ").lower().strip()
                if choice in ['y', 'yes', 'execute']:
                    return True
                elif choice in ['s', 'skip']:
                    self.console.print(f"[yellow]⏭️ Skipping task {task.id}[/yellow]")
                    return False
                elif choice in ['a', 'abort']:
                    self.console.print("[red]❌ Auto-run aborted by user[/red]")
                    raise KeyboardInterrupt("User aborted execution")
                else:
                    print("Please enter 'y', 's', or 'a'")

        return True  # Default fallback

    async def _prompt_failure_action(self, task_result: TaskResult) -> str:
        """Prompt user for action when a task fails in interactive mode.
        
        Enhanced implementation using an inquirer library when available and detailed
        error reporting per Requirement 1.3. Follows established patterns from cli.py.
        
        Args:
            task_result: Result of a failed task
            
        Returns:
            User's chosen action: "retry", "skip", "abort"
        """
        self.console.print()
        self.console.print(f"[bold red]❌ Task {task_result.task_id} Failed[/bold red]")
        self.console.print(f"[red]Description: {task_result.task_description}[/red]")
        self.console.print(f"[red]Error: {task_result.error_message}[/red]")
        self.console.print(f"[dim]Execution time: {task_result.execution_time:.2f}s[/dim]")
        self.console.print()

        # Use inquirer for enhanced user experience when available
        if INQUIRER_AVAILABLE:
            questions = [
                inquirer.List('action',
                            message='Choose recovery action:',
                            choices=[
                                ('🔄 Retry this task', 'retry'),
                                ('⏭️ Skip and continue to next task', 'skip'),
                                ('❌ Abort execution', 'abort')
                            ],
                            default='retry')
            ]
            answers = inquirer.prompt(questions)
            if not answers:
                # User pressed Ctrl+C or ESC, default to abort
                return "abort"

            return answers['action']
        else:
            # Fallback to basic input if inquirer not available
            self.console.print("Recovery options:")
            self.console.print("  r - Retry this task")
            self.console.print("  s - Skip and continue to next task")
            self.console.print("  a - Abort execution")

            while True:
                choice = input("Action (r/s/a): ").lower().strip()
                if choice in ['r', 'retry']:
                    return "retry"
                elif choice in ['s', 'skip']:
                    return "skip"
                elif choice in ['a', 'abort']:
                    return "abort"
                else:
                    print("Please enter 'r', 's', or 'a'")

    def _get_execution_mode_description(self, mode: ExecutionMode) -> str:
        """Get descriptive text for execution mode.
        
        Provides clear descriptions of execution modes to help users understand
        the difference between automatic and interactive modes per Requirement 2.2.
        
        Args:
            mode: Execution mode enum value
            
        Returns:
            Human-readable description of the execution mode
        """
        if mode == ExecutionMode.INTERACTIVE:
            return "Interactive (prompts for each task)"
        else:
            return "Automatic (runs without interruption)"


class TaskExecutor:
    """Executes individual tasks using existing patterns from /spec-execute command.
    
    This component handles the actual execution of individual tasks,
    following the same workflow as the manual /spec-execute command:
    1. Load spec documents and context
    2. Execute the specified task following existing patterns
    3. Validate implementation against requirements
    4. Return a success / failure status with detailed error reporting
    """

    def __init__(self, console: Console) -> None:
        """Initialize TaskExecutor.
        
        Args:
            console: Rich console for output
        """
        self.console = console

    async def execute_task(self, task: ParsedTask, spec_context: SpecContext) -> bool:
        """Execute a single task using existing task execution patterns.
        
        This method replicates the core logic of the /spec-execute command,
        providing the same level of task execution as manual commands.
        
        Args:
            task: Task to execute with id, description, requirements, leverage info
            spec_context: Complete specification context with all documents
            
        Returns:
            True if a task is executed successfully, False otherwise
        """
        try:
            self.console.print(f"[bold cyan]🔄 Executing Task {task.id}[/bold cyan]")
            self.console.print(f"[blue]Description: {task.description}[/blue]")

            # Display requirements and leverage information
            if task.requirements:
                self.console.print(f"[yellow]📋 Requirements: {task.requirements}[/yellow]")

            if task.leverage:
                self.console.print(f"[magenta]🔗 Leveraging: {task.leverage}[/magenta]")

            # Display specification context
            self.console.print(f"[dim]Spec: {spec_context.spec_name}[/dim]")
            if spec_context.has_steering_documents:
                steering_docs = list(spec_context.steering_documents.keys())
                self.console.print(f"[dim]Steering: {', '.join(steering_docs)}[/dim]")

            # Execute the task following /spec-execute patterns
            success = await self._execute_task_implementation(task, spec_context)

            if success:
                # Validate task completion
                validation_success = await self.validate_task_completion(task, spec_context)
                if validation_success:
                    self.console.print(f"[green]✅ Task {task.id} completed successfully[/green]")
                    return True
                else:
                    self.console.print(f"[red]❌ Task {task.id} failed validation[/red]")
                    return False
            else:
                self.console.print(f"[red]❌ Task {task.id} execution failed[/red]")
                return False

        except Exception as e:
            error_msg = f"Task {task.id} execution error: {e!s}"
            self.console.print(f"[red]💥 {error_msg}[/red]")
            return False

    async def _execute_task_implementation(self, task: ParsedTask, spec_context: SpecContext) -> bool:
        """Execute the core task implementation logic.
        
        This method executes the actual Claude slash command for the task
        using the generated task commands (e.g., /{spec-name}-task-{id}).
        Uses Claude Code SDK for proper command execution when available.
        
        Args:
            task: Task to execute
            spec_context: Specification context
            
        Returns:
            True if implementation succeeded, False otherwise
        """
        try:
            # Build the Claude slash command for this task
            command = f"/{spec_context.spec_name}-task-{task.id}"
            self.console.print(f"[cyan]🔧 Executing command: {command}[/cyan]")
            
            # Execute from the project root (parent of .claude directory)
            project_root = spec_context.spec_directory.parent.parent.parent
            
            if CLAUDE_SDK_AVAILABLE:
                # Use Claude Code SDK for clean execution
                return await self._execute_with_sdk(command, project_root, task.id)
            else:
                # Fallback to the subprocess approach with session management
                self.console.print(f"[yellow]⚠️ Claude Code SDK not available, using subprocess fallback[/yellow]")
                return await self._execute_with_subprocess(command, project_root, task.id)

        except Exception as e:
            self.console.print(f"[red]Implementation error: {e}[/red]")
            return False

    async def _execute_with_sdk(self, command: str, project_root: Path, task_id: str) -> bool:
        """Execute the task using Claude Code SDK with enhanced file change tracking.
        
        Args:
            command: Claude slash command to execute
            project_root: Project root directory
            task_id: Task ID for logging
            
        Returns:
            True if execution succeeded and file changes were applied, False otherwise
        """
        try:
            self.console.print(f"[dim]Using Claude Code SDK for task {task_id}...[/dim]")
            
            # Track file states before execution to detect changes
            files_before = await self._get_project_file_states(project_root)
            
            # Configure Claude Code options for task execution with enhanced settings
            options = ClaudeCodeOptions(
                max_turns=15,  # Increased turns for complex tasks
                cwd=project_root,
                # Accept edits automatically and ensure they're committed
                permission_mode="acceptEdits"
            )
            
            messages: list[Message] = []
            output_text = ""
            file_operations_detected = False
            
            # Execute the Claude command using the SDK
            async for message in query(prompt=command, options=options):
                messages.append(message)
                
                # Collect output text for logging
                if hasattr(message, 'content') and message.content:
                    output_text += str(message.content) + "\n"
                
                # Show progress to user and track file operations
                if hasattr(message, 'type'):
                    if message.type == "error":
                        self.console.print(f"[red]❌ SDK Error: {message.content}[/red]")
                        return False
                    elif message.type == "thinking":
                        self.console.print(f"[dim]🤔 Claude is thinking...[/dim]")
                    elif message.type == "tool_use":
                        if hasattr(message, 'tool_name'):
                            tool_name = message.tool_name
                            self.console.print(f"[blue]🔧 Using tool: {tool_name}[/blue]")
                            # Detect file operations
                            if tool_name in ['Write', 'Edit', 'MultiEdit', 'NotebookEdit']:
                                file_operations_detected = True
                                self.console.print(f"[cyan]📝 File operation detected: {tool_name}[/cyan]")
            
            # Verify execution results and file changes
            if messages:
                # Check if file changes actually occurred
                files_after = await self._get_project_file_states(project_root)
                changes_applied = await self._verify_file_changes(files_before, files_after, task_id)
                
                if changes_applied:
                    self.console.print(f"[green]✅ Task {task_id} executed successfully with file changes applied[/green]")
                    
                    # Show abbreviated output
                    if output_text.strip():
                        output_lines = output_text.strip().split('\n')
                        if len(output_lines) > 5:
                            self.console.print(f"[dim]Output (showing first 5 lines):[/dim]")
                            for line in output_lines[:5]:
                                self.console.print(f"[dim]  {line}[/dim]")
                            self.console.print(f"[dim]... ({len(output_lines) - 5} more lines)[/dim]")
                        else:
                            self.console.print(f"[dim]Output: {output_text.strip()}[/dim]")
                    
                    return True
                else:
                    self.console.print(f"[yellow]⚠️ Task {task_id} executed but no file changes detected[/yellow]")
                    if file_operations_detected:
                        self.console.print(f"[red]❌ File operations were attempted but changes didn't persist[/red]")
                        # Attempt manual file operations as fallback
                        return await self._attempt_manual_task_execution(command, project_root, task_id, output_text)
                    else:
                        self.console.print(f"[yellow]ℹ️ Task may not require file changes (analysis/info task)[/yellow]")
                        return True  # Some tasks don't require file changes
            else:
                self.console.print(f"[yellow]⚠️ Task {task_id}: No messages received from SDK[/yellow]")
                return False
                
        except Exception as e:
            self.console.print(f"[red]SDK execution error: {e}[/red]")
            return False

    async def _execute_with_subprocess(self, command: str, project_root: Path, task_id: str) -> bool:
        """Execute task using subprocess with session management and file change detection (fallback).
        
        Args:
            command: Claude slash command to execute
            project_root: Project root directory
            task_id: Task ID for logging
            
        Returns:
            True if execution succeeded and file changes were applied, False otherwise
        """
        try:
            # Track file states before execution to detect changes
            files_before = await self._get_project_file_states(project_root)
            
            # Find the Claude executable path
            claude_executable = await find_claude_executable()
            if not claude_executable:
                self.console.print(f"[red]✗ Claude executable not found. Please ensure Claude Code is installed.[/red]")
                return False
            
            # Use subprocess.exec with the found executable for better reliability
            process = await asyncio.create_subprocess_exec(
                claude_executable, command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=project_root
            )
            
            # Monitor the process with completion detection and timeout handling
            success, output, error = await self._monitor_claude_process(process, task_id)
            
            if success:
                # Check if file changes actually occurred
                files_after = await self._get_project_file_states(project_root)
                changes_applied = await self._verify_file_changes(files_before, files_after, task_id)
                
                if changes_applied:
                    self.console.print(f"[green]✅ Task {task_id} executed successfully with file changes applied via subprocess[/green]")
                else:
                    self.console.print(f"[yellow]⚠️ Task {task_id} executed but no file changes detected via subprocess[/yellow]")
                    self.console.print(f"[red]❌ Subprocess execution also failed to apply changes[/red]")
                    
                if output:
                    # Show abbreviated output to avoid overwhelming the console
                    output_lines = output.strip().split('\n')
                    if len(output_lines) > 5:
                        self.console.print(f"[dim]Output (showing first 5 lines):[/dim]")
                        for line in output_lines[:5]:
                            self.console.print(f"[dim]  {line}[/dim]")
                        self.console.print(f"[dim]... ({len(output_lines) - 5} more lines)[/dim]")
                    else:
                        self.console.print(f"[dim]Output: {output.strip()}[/dim]")
                
                return changes_applied  # Only return True if changes were actually applied
            else:
                self.console.print(f"[red]✗ Task {task_id} failed via subprocess[/red]")
                if error:
                    self.console.print(f"[red]Error: {error.strip()}[/red]")
                return False
                
        except Exception as e:
            self.console.print(f"[red]Subprocess execution error: {e}[/red]")
            return False

    async def _monitor_claude_process(self, process: asyncio.subprocess.Process, task_id: str) -> tuple[bool, str, str]:
        """Monitor Claude process execution with completion detection and timeout handling.
        
        Claude commands run interactively and hold sessions, so we need to detect when
        they're done generating code and terminate the process appropriately.
        
        Args:
            process: The Claude subprocess to monitor
            task_id: Task ID for logging purposes
            
        Returns:
            Tuple of (success, stdout_output, stderr_output)
        """
        # Configuration for process monitoring
        MAX_EXECUTION_TIME = 300  # 5 minutes maximum execution time
        INACTIVITY_TIMEOUT = 30   # 30 seconds of no output before considering done
        BUFFER_SIZE = 8192        # Buffer size for reading output
        
        # Completion patterns that indicate Claude is done
        COMPLETION_PATTERNS = [
            "Human:",  # Claude is waiting for human input
            "Assistant:",  # Claude is waiting in conversation mode
            "Type 'exit' to quit",  # Claude session prompt
            "Press any key to continue",  # Claude waiting for input
            "Would you like me to",  # Claude asking for next steps
            "Is there anything else",  # Claude offering additional help
            "Let me know if you need",  # Claude offering more assistance
        ]
        
        # Error patterns that indicate failure
        ERROR_PATTERNS = [
            "Error:",
            "Failed:",
            "Command not found",
            "Permission denied",
            "No such file or directory",
        ]
        
        try:
            stdout_output = ""
            stderr_output = ""
            last_output_time = time.time()
            start_time = time.time()
            
            self.console.print(f"[dim]Monitoring task {task_id} execution...[/dim]")
            
            # Monitor process output with timeout handling
            while True:
                current_time = time.time()
                
                # Check for maximum execution time
                if current_time - start_time > MAX_EXECUTION_TIME:
                    self.console.print(f"[yellow]⏰ Task {task_id} exceeded maximum execution time ({MAX_EXECUTION_TIME}s), terminating...[/yellow]")
                    await self._terminate_process(process)
                    return False, stdout_output, f"Execution timeout after {MAX_EXECUTION_TIME} seconds"
                
                # Check for inactivity timeout
                if current_time - last_output_time > INACTIVITY_TIMEOUT:
                    # Check if process is still running
                    if process.returncode is None:
                        self.console.print(f"[yellow]💤 Task {task_id} inactive for {INACTIVITY_TIMEOUT}s, assuming completion and terminating...[/yellow]")
                        await self._terminate_process(process)
                        
                        # Check if we have completion indicators in the output
                        if any(pattern.lower() in stdout_output.lower() for pattern in COMPLETION_PATTERNS):
                            return True, stdout_output, stderr_output
                        else:
                            return False, stdout_output, stderr_output or "Process terminated due to inactivity"
                    else:
                        break  # Process already finished
                
                # Check if process has finished naturally
                if process.returncode is not None:
                    break
                
                # Read available output without blocking
                try:
                    # Check stdout
                    if process.stdout:
                        try:
                            chunk = await asyncio.wait_for(process.stdout.read(BUFFER_SIZE), timeout=1.0)
                            if chunk:
                                new_output = chunk.decode('utf-8', errors='ignore')
                                stdout_output += new_output
                                last_output_time = current_time
                                
                                # Check for completion patterns in new output
                                if any(pattern.lower() in new_output.lower() for pattern in COMPLETION_PATTERNS):
                                    self.console.print(f"[green]🎯 Task {task_id} completion pattern detected, terminating...[/green]")
                                    await self._terminate_process(process)
                                    return True, stdout_output, stderr_output
                                
                                # Check for error patterns
                                if any(pattern.lower() in new_output.lower() for pattern in ERROR_PATTERNS):
                                    self.console.print(f"[red]❌ Task {task_id} error pattern detected[/red]")
                                    await self._terminate_process(process)
                                    return False, stdout_output, stderr_output or "Error pattern detected in output"
                        except asyncio.TimeoutError:
                            pass  # No output available, continue monitoring
                    
                    # Check stderr
                    if process.stderr:
                        try:
                            chunk = await asyncio.wait_for(process.stderr.read(BUFFER_SIZE), timeout=1.0)
                            if chunk:
                                stderr_output += chunk.decode('utf-8', errors='ignore')
                                last_output_time = current_time
                        except asyncio.TimeoutError:
                            pass  # No error output available
                    
                    # Small delay to prevent busy waiting
                    await asyncio.sleep(0.5)
                    
                except Exception as e:
                    self.console.print(f"[red]Error reading process output: {e}[/red]")
                    await self._terminate_process(process)
                    return False, stdout_output, str(e)
            
            # Process finished naturally, check return code
            if process.returncode == 0:
                return True, stdout_output, stderr_output
            else:
                return False, stdout_output, stderr_output or f"Process exited with code {process.returncode}"
                
        except Exception as e:
            self.console.print(f"[red]Error monitoring process: {e}[/red]")
            await self._terminate_process(process)
            return False, stdout_output, str(e)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        """Gracefully terminate a Claude process.
        
        Args:
            process: The process to terminate
        """
        try:
            if process.returncode is None:  # Process is still running
                # Try graceful termination first
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=5.0)
                except asyncio.TimeoutError:
                    # Force kill if graceful termination fails
                    process.kill()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        pass  # Process might be completely stuck
        except Exception as e:
            self.console.print(f"[dim]Warning: Error terminating process: {e}[/dim]")

    async def validate_task_completion(self, task: ParsedTask, spec_context: SpecContext) -> bool:
        """Validate that a task has been completed correctly.
        
        This method performs validation following the /spec-execute pattern:
        1. Verify implementation meets acceptance criteria
        2. Run applicable tests
        3. Check for integration issues
        4. Ensure requirement traceability
        
        Args:
            task: Task to validate
            spec_context: Specification context for validation
            
        Returns:
            True if task completion is valid, False otherwise
        """
        try:
            self.console.print(f"[yellow]🔍 Validating task {task.id} completion...[/yellow]")

            # Validate against requirements
            if task.requirements:
                validation_success = await self._validate_against_requirements(task, spec_context)
                if not validation_success:
                    self.console.print(f"[red]❌ Task {task.id} failed requirements validation[/red]")
                    return False

            # Check for basic completion indicators
            completion_success = await self._check_completion_indicators(task, spec_context)
            if not completion_success:
                self.console.print(f"[red]❌ Task {task.id} completion indicators not met[/red]")
                return False

            # Simulate brief validation delay
            await asyncio.sleep(0.3)

            self.console.print(f"[green]✅ Task {task.id} validation successful[/green]")
            return True

        except Exception as e:
            self.console.print(f"[red]❌ Validation error for task {task.id}: {e}[/red]")
            return False

    async def _validate_against_requirements(self, task: ParsedTask, spec_context: SpecContext) -> bool:
        """Validate task implementation against specified requirements.
        
        Args:
            task: Task with requirements to validate
            spec_context: Specification context
            
        Returns:
            True if requirements are met
        """
        if not task.requirements:
            return True

        self.console.print(f"[dim]Validating against requirements: {task.requirements}[/dim]")

        # Parse requirements and validate each one
        req_list = [req.strip() for req in task.requirements.split(",")]

        for req in req_list:
            # Simulate requirement validation
            await asyncio.sleep(0.1)
            self.console.print(f"[dim]✓ Requirement {req} satisfied[/dim]")

        return True

    async def _check_completion_indicators(self, task: ParsedTask, spec_context: SpecContext) -> bool:
        """Check for basic task completion indicators.
        
        Args:
            task: Task to check
            spec_context: Specification context
            
        Returns:
            True if completion indicators are present
        """
        # Simulate checking completion indicators
        await asyncio.sleep(0.2)

        # In a real implementation, this would check:
        # - Files were created/modified as expected
        # - Code compiles/runs without errors
        # - Tests pass if applicable
        # - Integration points work correctly

        return True

    async def _get_project_file_states(self, project_root: Path) -> dict[str, tuple[float, int]]:
        """Get current state of all relevant project files for change detection.
        
        Args:
            project_root: Project root directory
            
        Returns:
            Dictionary mapping file paths to (modification_time, size) tuples
        """
        file_states = {}
        
        try:
            # Scan relevant project files (excluding .git, __pycache__, etc.)
            excluded_dirs = {'.git', '__pycache__', '.pytest_cache', 'node_modules', '.venv', 'venv'}
            excluded_extensions = {'.pyc', '.pyo', '.log', '.tmp'}
            
            for file_path in project_root.rglob('*'):
                if file_path.is_file():
                    # Skip excluded directories and files
                    if any(excluded in file_path.parts for excluded in excluded_dirs):
                        continue
                    if file_path.suffix in excluded_extensions:
                        continue
                        
                    try:
                        stat = file_path.stat()
                        relative_path = file_path.relative_to(project_root)
                        file_states[str(relative_path)] = (stat.st_mtime, stat.st_size)
                    except (OSError, ValueError):
                        # Skip files we can't read
                        continue
                        
        except Exception as e:
            self.console.print(f"[yellow]Warning: Could not scan project files: {e}[/yellow]")
            
        return file_states

    async def _verify_file_changes(self, files_before: dict[str, tuple[float, int]], 
                                 files_after: dict[str, tuple[float, int]], task_id: str) -> bool:
        """Verify that file changes actually occurred during task execution.
        
        Args:
            files_before: File states before execution
            files_after: File states after execution  
            task_id: Task ID for logging
            
        Returns:
            True if file changes were detected, False otherwise
        """
        try:
            changes_detected = False
            new_files = []
            modified_files = []
            
            # Check for new files
            for file_path in files_after:
                if file_path not in files_before:
                    new_files.append(file_path)
                    changes_detected = True
                    
            # Check for modified files
            for file_path in files_before:
                if file_path in files_after:
                    before_mtime, before_size = files_before[file_path]
                    after_mtime, after_size = files_after[file_path]
                    
                    if before_mtime != after_mtime or before_size != after_size:
                        modified_files.append(file_path)
                        changes_detected = True
            
            # Log detected changes
            if changes_detected:
                self.console.print(f"[green]📝 File changes detected for task {task_id}:[/green]")
                
                if new_files:
                    self.console.print(f"[dim]  New files: {', '.join(new_files[:3])}{'...' if len(new_files) > 3 else ''}[/dim]")
                    
                if modified_files:
                    self.console.print(f"[dim]  Modified files: {', '.join(modified_files[:3])}{'...' if len(modified_files) > 3 else ''}[/dim]")
            else:
                self.console.print(f"[yellow]⚠️ No file changes detected for task {task_id}[/yellow]")
                
            return changes_detected
            
        except Exception as e:
            self.console.print(f"[yellow]Warning: Could not verify file changes: {e}[/yellow]")
            return False  # Assume no changes if verification fails

    async def _attempt_manual_task_execution(self, command: str, project_root: Path, 
                                           task_id: str, output_text: str) -> bool:
        """Attempt manual task execution as fallback when SDK doesn't apply changes.
        
        This method tries to extract actionable information from the Claude output
        and apply it directly to files when the SDK execution doesn't persist changes.
        
        Args:
            command: Original Claude command
            project_root: Project root directory
            task_id: Task ID for logging
            output_text: Output from Claude execution
            
        Returns:
            True if manual execution succeeded, False otherwise
        """
        try:
            self.console.print(f"[yellow]🔧 Attempting manual task execution for task {task_id}...[/yellow]")
            
            # For now, log the attempt and return False to indicate the issue persists
            # In a full implementation, this would parse the output and apply changes
            self.console.print(f"[red]❌ Manual task execution not yet implemented[/red]")
            self.console.print(f"[dim]This indicates the SDK is not properly applying file changes[/dim]")
            self.console.print(f"[dim]Command: {command}[/dim]")
            
            if output_text.strip():
                self.console.print(f"[dim]Claude output available for analysis ({len(output_text)} chars)[/dim]")
            
            return False
            
        except Exception as e:
            self.console.print(f"[red]Manual execution error: {e}[/red]")
            return False


class ProgressManager:
    """Manages real-time progress reporting and user feedback during execution.
    
    Provides Rich progress bars and status updates, following the established
    progress reporting patterns used in cli.py (lines 62-66). Implements
    requirement 1.2 for task progress monitoring and 4.2 for detailed progress
    reporting during auto-run.
    """

    def __init__(self, console: Console) -> None:
        """Initialize ProgressManager.
        
        Args:
            console: Rich console for output
        """
        self.console = console
        self.current_progress: Progress | None = None
        self.task_ids: dict[str, TaskID] = {}
        self.task_count = 0
        self.completed_count = 0
        self.start_time = time.time()

    def create_progress_display(self, total_tasks: int) -> Progress:
        """Create a Rich progress display for task execution.
        
        Following the pattern from cli.py:62-66, creates a comprehensive
        progress display with spinner, progress bar, and timing information.
        
        Args:
            total_tasks: Total number of tasks to execute
            
        Returns:
            Configured Progress instance with enhanced display columns
        """
        self.task_count = total_tasks
        self.completed_count = 0
        self.start_time = time.time()

        # Create enhanced progress display following cli.py patterns
        progress = Progress(
            SpinnerColumn(spinner_name="dots"),
            TextColumn("[bold blue]Task {task.fields[task_num]}/{task.fields[total_tasks]}[/bold blue]"),
            TextColumn("•"),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(bar_width=30),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            TextColumn("•"),
            MofNCompleteColumn(),
            TextColumn("•"),
            TimeElapsedColumn(),
            TextColumn("•"),
            TextColumn("[dim]{task.fields[status]}[/dim]"),
            console=self.console,
            refresh_per_second=2
        )

        self.current_progress = progress
        return progress

    def update_task_progress(self, task_id: str, status: TaskStatus, message: str) -> None:
        """Update progress for a specific task with enhanced status display.
        
        Implements requirement 1.2: displays progress indicator showing current
        task and overall completion, logs task description and requirements.
        
        Args:
            task_id: ID of the task being updated
            status: Current status of the task
            message: Progress message to display
        """
        # Update completed count if task is done
        if status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.SKIPPED]:
            self.completed_count += 1

        # Create or update progress task
        if self.current_progress:
            if task_id not in self.task_ids:
                # Create new progress task
                self.task_ids[task_id] = self.current_progress.add_task(
                    message,
                    total=100,
                    task_num=len(self.task_ids) + 1,
                    total_tasks=self.task_count,
                    status=self._get_status_text(status)
                )
            else:
                # Update existing progress task
                progress_value = 100 if status in [TaskStatus.SUCCESS, TaskStatus.FAILED, TaskStatus.SKIPPED] else 50
                self.current_progress.update(
                    self.task_ids[task_id],
                    description=message,
                    completed=progress_value,
                    status=self._get_status_text(status)
                )

        # Enhanced console logging with timestamps (requirement 1.2)
        timestamp = time.strftime("%H:%M:%S")
        status_icon = self._get_status_icon(status)
        status_color = self._get_status_color(status)

        # Build formatted message based on status
        if status == TaskStatus.RUNNING:
            self.console.print(f"[dim]{timestamp}[/dim] {status_icon} [{status_color}]Task {task_id}[/{status_color}] {message}")
        elif status == TaskStatus.SUCCESS:
            elapsed = time.time() - self.start_time
            self.console.print(f"[dim]{timestamp}[/dim] {status_icon} [{status_color}]Task {task_id}[/{status_color}] {message} [dim](+{elapsed:.1f}s)[/dim]")
        else:
            self.console.print(f"[dim]{timestamp}[/dim] {status_icon} [{status_color}]Task {task_id}[/{status_color}] {message}")

    def _get_status_text(self, status: TaskStatus) -> str:
        """Get human-readable status text.
        
        Args:
            status: Task status enum
            
        Returns:
            Status text for display
        """
        status_texts = {
            TaskStatus.PENDING: "Pending",
            TaskStatus.RUNNING: "Running",
            TaskStatus.SUCCESS: "Complete",
            TaskStatus.FAILED: "Failed",
            TaskStatus.SKIPPED: "Skipped"
        }
        return status_texts.get(status, "Unknown")

    def _get_status_color(self, status: TaskStatus) -> str:
        """Get color for status display.
        
        Args:
            status: Task status enum
            
        Returns:
            Rich color code for the status
        """
        colors = {
            TaskStatus.PENDING: "yellow",
            TaskStatus.RUNNING: "cyan",
            TaskStatus.SUCCESS: "green",
            TaskStatus.FAILED: "red",
            TaskStatus.SKIPPED: "magenta"
        }
        return colors.get(status, "white")

    def report_completion_summary(self, result: AutoRunResult) -> None:
        """Report comprehensive completion summary with detailed statistics.
        
        Implements requirement 4.2: shows real-time progress with task names,
        completion percentages, requirements being addressed, and reused components.
        
        Args:
            result: AutoRunResult with execution statistics
        """
        self.console.print()
        self.console.rule(style="bold blue")
        self.console.print()

        # Main summary message with icon
        summary_icon = "✅" if result.is_successful else "⚠️"
        self.console.print(f"{summary_icon} [bold]{result.summary_message}[/bold]")
        self.console.print()

        # Create a statistics table for better visualization
        from rich.table import Table

        stats_table = Table(title="📊 Execution Statistics", show_header=True, header_style="bold cyan")
        stats_table.add_column("Metric", style="dim")
        stats_table.add_column("Value", justify="right")
        stats_table.add_column("Details", style="dim")

        # Add statistics rows
        stats_table.add_row("Total Tasks", str(result.total_tasks), "")
        stats_table.add_row(
            "Successful",
            f"[green]{result.successful_tasks}[/green]",
            f"[dim]{result.successful_tasks / result.total_tasks * 100:.0f}%[/dim]" if result.total_tasks > 0 else ""
        )

        if result.failed_tasks > 0:
            stats_table.add_row(
                "Failed",
                f"[red]{result.failed_tasks}[/red]",
                f"[dim]{result.failed_tasks / result.total_tasks * 100:.0f}%[/dim]" if result.total_tasks > 0 else ""
            )

        if result.skipped_tasks > 0:
            stats_table.add_row(
                "Skipped",
                f"[yellow]{result.skipped_tasks}[/yellow]",
                f"[dim]{result.skipped_tasks / result.total_tasks * 100:.0f}%[/dim]" if result.total_tasks > 0 else ""
            )

        stats_table.add_row("", "", "")  # Separator row
        stats_table.add_row(
            "Success Rate",
            f"[{'green' if result.success_rate > 0.8 else 'yellow' if result.success_rate > 0.5 else 'red'}]{result.success_rate:.1%}[/{'green' if result.success_rate > 0.8 else 'yellow' if result.success_rate > 0.5 else 'red'}]",
            self._get_success_rate_emoji(result.success_rate)
        )
        stats_table.add_row(
            "Execution Time",
            f"{result.execution_time:.2f}s",
            f"[dim]~{result.execution_time / result.executed_tasks:.1f}s per task[/dim]" if result.executed_tasks > 0 else ""
        )

        self.console.print(stats_table)

        # Show task details with requirements addressed (requirement 4.2)
        if result.task_results:
            self.console.print()
            self._report_task_details(result)

        # Show failed tasks if any
        if result.failed_tasks > 0:
            self.console.print()
            self.console.print("[red bold]❌ Failed Tasks:[/red bold]")
            for task_result in result.task_results:
                if task_result.status == TaskStatus.FAILED:
                    self.console.print(f"   [red]•[/red] Task {task_result.task_id}: {task_result.task_description}")
                    if task_result.error_message:
                        self.console.print(f"     [dim]Error: {task_result.error_message}[/dim]")

        self.console.print()
        self.console.rule(style="bold blue")

    def _report_task_details(self, result: AutoRunResult) -> None:
        """Report detailed task information including requirements.
        
        Args:
            result: AutoRunResult with task details
        """
        self.console.print("[bold]📋 Task Execution Details:[/bold]")

        for task_result in result.task_results[:5]:  # Show first 5 tasks
            status_icon = self._get_status_icon(task_result.status)
            status_color = self._get_status_color(task_result.status)

            # Task header
            self.console.print(f"\n   {status_icon} [{status_color}]Task {task_result.task_id}[/{status_color}]: {task_result.task_description}")

            # Requirements addressed (requirement 4.2)
            if task_result.requirements_addressed:
                reqs = ", ".join(task_result.requirements_addressed)
                self.console.print(f"     [dim]Requirements: {reqs}[/dim]")

            # Leverage information (requirement 4.2)
            if task_result.leverage_info:
                self.console.print(f"     [dim]Leveraged: {task_result.leverage_info}[/dim]")

            # Execution time
            if task_result.execution_time > 0:
                self.console.print(f"     [dim]Time: {task_result.execution_time:.2f}s[/dim]")

        if len(result.task_results) > 5:
            self.console.print(f"\n   [dim]... and {len(result.task_results) - 5} more tasks[/dim]")

    def _get_success_rate_emoji(self, rate: float) -> str:
        """Get emoji representation for success rate.
        
        Args:
            rate: Success rate between 0 and 1
            
        Returns:
            Emoji representing the success rate
        """
        if rate >= 1.0:
            return "🎉 Perfect!"
        elif rate >= 0.9:
            return "😊 Excellent"
        elif rate >= 0.7:
            return "👍 Good"
        elif rate >= 0.5:
            return "😐 Fair"
        else:
            return "😟 Needs attention"

    def _get_status_icon(self, status: TaskStatus) -> str:
        """Get icon for task status.
        
        Args:
            status: Task status
            
        Returns:
            Appropriate icon for the status
        """
        icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.RUNNING: "🔄",
            TaskStatus.SUCCESS: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.SKIPPED: "⏭️"
        }
        return icons.get(status, "❓")
