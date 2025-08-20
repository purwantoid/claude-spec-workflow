"""Data models and configuration classes for auto-run task execution.

This module defines the core data structures used by the auto-run system,
including configuration options, task results, and execution status tracking.
Following established project patterns with dataclass-based models for
compatibility with existing task parsing infrastructure.
"""

import time

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class ExecutionMode(Enum):
    """Execution mode for auto-run operations.
    
    AUTOMATIC: Execute all tasks without user intervention
    INTERACTIVE: Prompt user before each task execution
    """
    AUTOMATIC = "automatic"
    INTERACTIVE = "interactive"


class TaskStatus(Enum):
    """Status enumeration for individual task execution.
    
    SUCCESS: Task completed successfully
    FAILED: Task execution failed with error
    SKIPPED: Task was skipped due to user choice or dependency
    RUNNING: Task is currently executing
    PENDING: Task has not started execution yet
    """
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RUNNING = "running"
    PENDING = "pending"


@dataclass
class AutoRunOptions:
    """Configuration options for automated task execution.
    
    This class encapsulates all user preferences and execution parameters
    for the auto-run system, following the established dataclass patterns
    used in task_generator.py.
    """
    execution_mode: ExecutionMode = ExecutionMode.AUTOMATIC
    task_selection: str | None = None  # "all", "1-3", "2,4,6", specific task IDs
    continue_on_error: bool = False
    show_detailed_progress: bool = True
    resume_from_task: str | None = None

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.task_selection is None:
            self.task_selection = "all"


@dataclass
class TaskResult:
    """Result of individual task execution.
    
    Captures execution details, status, and metadata for a single task
    to enable comprehensive reporting and error handling.
    """
    task_id: str
    task_description: str
    status: TaskStatus
    execution_time: float = 0.0
    error_message: str | None = None
    requirements_addressed: list[str] | None = None
    leverage_info: str | None = None
    start_time: float | None = field(default_factory=time.time)
    end_time: float | None = None

    def mark_started(self) -> None:
        """Mark the task as started and record the start time."""
        self.status = TaskStatus.RUNNING
        self.start_time = time.time()

    def mark_completed(self, success: bool = True, error_message: str | None = None) -> None:
        """Mark the task as completed with success or failure status.
        
        Args:
            success: Whether the task completed successfully
            error_message: Error message if a task failed
        """
        self.end_time = time.time()
        if self.start_time:
            self.execution_time = self.end_time - self.start_time

        if success:
            self.status = TaskStatus.SUCCESS
        else:
            self.status = TaskStatus.FAILED
            self.error_message = error_message

    def mark_skipped(self, reason: str | None = None) -> None:
        """Mark the task as skipped with an optional reason.
        
        Args:
            reason: Reason why the task was skipped
        """
        self.status = TaskStatus.SKIPPED
        self.error_message = reason
        self.end_time = time.time()


@dataclass
class AutoRunResult:
    """Comprehensive result of auto-run execution.
    
    Provides summary statistics and detailed results for all tasks
    executed during an auto-run session.
    """
    spec_name: str
    total_tasks: int
    executed_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    skipped_tasks: int = 0
    execution_time: float = 0.0
    task_results: list[TaskResult] = field(default_factory=list)
    summary_message: str = ""
    start_time: float | None = field(default_factory=time.time)
    end_time: float | None = None

    def add_task_result(self, result: TaskResult) -> None:
        """Add a task result and update summary statistics.
        
        Args:
            result: TaskResult to add to the collection
        """
        self.task_results.append(result)
        self.executed_tasks += 1

        if result.status == TaskStatus.SUCCESS:
            self.successful_tasks += 1
        elif result.status == TaskStatus.FAILED:
            self.failed_tasks += 1
        elif result.status == TaskStatus.SKIPPED:
            self.skipped_tasks += 1

    def update_last_task_result(self, result: TaskResult) -> None:
        """Update the last task result (for retry scenarios).
        
        This method replaces the last task result with a new one,
        adjusting the summary statistics accordingly.
        
        Args:
            result: New TaskResult to replace the last one
        """
        if not self.task_results:
            # No previous results, just add the new one
            self.add_task_result(result)
            return

        # Get the old result and update statistics
        old_result = self.task_results[-1]

        # Adjust counters for the old result
        if old_result.status == TaskStatus.SUCCESS:
            self.successful_tasks -= 1
        elif old_result.status == TaskStatus.FAILED:
            self.failed_tasks -= 1
        elif old_result.status == TaskStatus.SKIPPED:
            self.skipped_tasks -= 1

        # Replace the last result
        self.task_results[-1] = result

        # Update counters for the new result
        if result.status == TaskStatus.SUCCESS:
            self.successful_tasks += 1
        elif result.status == TaskStatus.FAILED:
            self.failed_tasks += 1
        elif result.status == TaskStatus.SKIPPED:
            self.skipped_tasks += 1

    def finalize(self) -> None:
        """Finalize the auto-run result with timing and summary message."""
        self.end_time = time.time()
        if self.start_time:
            self.execution_time = self.end_time - self.start_time

        # Generate summary message
        if self.failed_tasks == 0:
            self.summary_message = f"✅ Auto-run completed successfully: {self.successful_tasks}/{self.total_tasks} tasks completed"
        else:
            self.summary_message = f"⚠️ Auto-run completed with issues: {self.successful_tasks} successful, {self.failed_tasks} failed, {self.skipped_tasks} skipped"

    @property
    def success_rate(self) -> float:
        """Calculate the success rate as a percentage.
        
        Returns:
            Success rate as a float between 0.0 and 1.0
        """
        if self.executed_tasks == 0:
            return 0.0
        return self.successful_tasks / self.executed_tasks

    @property
    def is_successful(self) -> bool:
        """Check if the auto-run was completely successful.
        
        Returns:
            True if all executed tasks were successful
        """
        return self.failed_tasks == 0 and self.executed_tasks > 0


@dataclass
class SpecContext:
    """Context information for a specification during auto-run execution.
    
    Consolidates all necessary documents and metadata needed for task execution,
    following the pattern established in the existing spec workflow system.
    """
    spec_name: str
    requirements_content: str
    design_content: str
    tasks_content: str
    steering_documents: dict[str, str] = field(default_factory=dict)  # filename -> content
    spec_directory: Path = field(default_factory=Path)

    def __post_init__(self) -> None:
        """Validate that required content is present."""
        if not self.spec_name:
            raise ValueError("spec_name is required")
        if not self.requirements_content:
            raise ValueError("requirements_content is required")
        if not self.design_content:
            raise ValueError("design_content is required")
        if not self.tasks_content:
            raise ValueError("tasks_content is required")

    @property
    def has_steering_documents(self) -> bool:
        """Check if steering documents are available.
        
        Returns:
            True if any steering documents are loaded
        """
        return len(self.steering_documents) > 0

    def get_steering_document(self, filename: str) -> str | None:
        """Get the content of a specific steering document.
        
        Args:
            filename: Name of the steering document (e.g., 'tech.md')
            
        Returns:
            Content of the document if available, None otherwise
        """
        return self.steering_documents.get(filename)


@dataclass
class ExecutionState:
    """Execution state for auto-run persistence and recovery.
    
    This class captures the current state of auto-run execution to enable
    resume functionality after interruptions or failures, implementing
    Requirements 2.3 and 1.3 for execution state tracking and recovery.
    """
    spec_name: str
    start_time: float
    last_updated: float
    options: AutoRunOptions
    completed_task_ids: list[str] = field(default_factory=list)
    failed_task_ids: list[str] = field(default_factory=list)
    skipped_task_ids: list[str] = field(default_factory=list)
    current_task_id: str | None = None
    total_tasks: int = 0
    interruption_reason: str | None = None

    def __post_init__(self) -> None:
        """Set last_updated to the current time if not provided."""
        if not hasattr(self, 'last_updated') or self.last_updated == 0:
            self.last_updated = time.time()

    @property
    def next_task_id(self) -> str | None:
        """Determine the next task ID to resume from.
        
        Returns:
            Task ID to resume from, or None if no resumption is needed
        """
        if self.current_task_id and self.current_task_id not in self.completed_task_ids:
            return self.current_task_id
        return None

    @property
    def completion_rate(self) -> float:
        """Calculate completion rate as percentage.
        
        Returns:
            Completion rate between 0.0 and 1.0
        """
        if self.total_tasks == 0:
            return 0.0
        return len(self.completed_task_ids) / self.total_tasks

    @property
    def is_resumable(self) -> bool:
        """Check if the execution state is resumable.
        
        Returns:
            True if the state can be resumed
        """
        return (
            len(self.completed_task_ids) < self.total_tasks and
            self.total_tasks > 0 and
            (self.current_task_id is not None or len(self.completed_task_ids) > 0)
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization.
        
        Returns:
            Dictionary representation of the state
        """
        return {
            'spec_name': self.spec_name,
            'start_time': self.start_time,
            'last_updated': self.last_updated,
            'options': {
                'execution_mode': self.options.execution_mode.value,
                'task_selection': self.options.task_selection,
                'continue_on_error': self.options.continue_on_error,
                'show_detailed_progress': self.options.show_detailed_progress,
                'resume_from_task': self.options.resume_from_task
            },
            'completed_task_ids': self.completed_task_ids,
            'failed_task_ids': self.failed_task_ids,
            'skipped_task_ids': self.skipped_task_ids,
            'current_task_id': self.current_task_id,
            'total_tasks': self.total_tasks,
            'interruption_reason': self.interruption_reason
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ExecutionState':
        """Create ExecutionState from the dictionary.
        
        Args:
            data: Dictionary with state data
            
        Returns:
            ExecutionState instance
        """
        options_data = data.get('options', {})
        options = AutoRunOptions(
            execution_mode=ExecutionMode(options_data.get('execution_mode', 'automatic')),
            task_selection=options_data.get('task_selection'),
            continue_on_error=options_data.get('continue_on_error', False),
            show_detailed_progress=options_data.get('show_detailed_progress', True),
            resume_from_task=options_data.get('resume_from_task')
        )

        return cls(
            spec_name=data['spec_name'],
            start_time=data.get('start_time', time.time()),
            last_updated=data.get('last_updated', time.time()),
            options=options,
            completed_task_ids=data.get('completed_task_ids', []),
            failed_task_ids=data.get('failed_task_ids', []),
            skipped_task_ids=data.get('skipped_task_ids', []),
            current_task_id=data.get('current_task_id'),
            total_tasks=data.get('total_tasks', 0),
            interruption_reason=data.get('interruption_reason')
        )
