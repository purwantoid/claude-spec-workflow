"""Command line interface for spec-driven workflow.

This module provides the main CLI entry point using Click framework,
replacing the TypeScript Commander.js functionality with Python equivalents.
"""

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

try:
    import inquirer
    INQUIRER_AVAILABLE = True
except ImportError:
    INQUIRER_AVAILABLE = False

from spec_driven_workflow.setup import SpecWorkflowSetup
from spec_driven_workflow.utils import detect_project_type, validate_claude_code
from spec_driven_workflow.task_generator import parse_tasks_from_markdown, generate_task_command
from spec_driven_workflow.auto_runner import TaskAutoRunner
from spec_driven_workflow.auto_run_models import AutoRunOptions, ExecutionMode

console = Console()

# Package version - ideally read from pyproject.toml or __init__.py
VERSION = "1.3.4"


@click.group()
@click.version_option(version=VERSION, prog_name="spec-driven-workflow")
def main() -> None:
    """Spec Driven Workflow - Automated workflows for Claude Code.
    
    Includes spec-driven development (Requirements → Design → Tasks → Implementation)
    and streamlined bug fix workflow (Report → Analyze → Fix → Verify).
    """
    pass


@main.command()
@click.option('-p', '--project', default=None, help='Project directory (default: current directory)')
@click.option('-f', '--force', is_flag=True, help='Force overwrite existing files')
@click.option('-y', '--yes', is_flag=True, help='Skip confirmation prompts')
def setup(project: Optional[str], force: bool, yes: bool) -> None:
    """Set up Claude Code Spec Workflow in your project."""
    asyncio.run(_setup_async(project, force, yes))


async def _setup_async(project: Optional[str], force: bool, yes: bool) -> None:
    """Async implementation of setup command."""
    console.print("🚀 [bold cyan]Claude Code Spec Workflow Setup[/bold cyan]")
    console.print("[dim]Claude Code Automated spec-driven development workflow[/dim]")
    console.print()

    project_path = Path(project) if project else Path.cwd()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task("Analyzing project...", total=None)
        
        try:
            # Detect project type
            project_types = await detect_project_type(project_path)
            progress.update(task, description=f"Project analyzed: {project_path}")
            progress.stop_task(task)
            progress.remove_task(task)
            
            if project_types:
                console.print(f"📊 [blue]Detected project type(s): {', '.join(project_types)}[/blue]")
            
            # Check Claude Code availability
            claude_available = await validate_claude_code()
            if claude_available:
                console.print("✓ [green]Claude Code is available[/green]")
            else:
                console.print("⚠️  [yellow]Claude Code not found. Please install Claude Code first.[/yellow]")
                console.print("[dim]   Visit: https://docs.anthropic.com/claude-code[/dim]")
            
            # Ensure context7 MCP server is configured
            await _ensure_context7_mcp_server(console, project_path, project_types)
            
            # Check for existing .claude directory and handle migration
            setup = SpecWorkflowSetup(project_path)
            claude_exists = await setup.claude_directory_exists()
            
            if claude_exists and not force:
                # Get migration information
                migration_info = await setup.get_migration_info()
                has_existing = migration_info["has_existing_claude"]
                has_typescript = migration_info["has_typescript_installation"]
                existing_specs = migration_info["existing_specs"]
                existing_bugs = migration_info["existing_bugs"]
                is_compatible, issues = migration_info["compatibility_check"]
                
                if has_existing:
                    console.print("[yellow]⚠️  Existing .claude directory found![/yellow]")
                    
                    if has_typescript:
                        console.print("[blue]📦 TypeScript installation detected - migration mode enabled[/blue]")
                    
                    if existing_specs:
                        console.print(f"[dim]  📊 Found {len(existing_specs)} existing spec(s)[/dim]")
                    
                    if existing_bugs:
                        console.print(f"[dim]  🐛 Found {len(existing_bugs)} existing bug report(s)[/dim]")
                    
                    if not is_compatible and issues:
                        console.print("[red]⚠️  Compatibility issues detected:[/red]")
                        for issue in issues:
                            console.print(f"[dim]  • {issue}[/dim]")
                
                if not yes:
                    message = '.claude directory already exists.'
                    if has_existing and has_typescript:
                        message += ' Migrate from TypeScript version?'
                    else:
                        message += ' Update with latest commands?'
                    
                    if INQUIRER_AVAILABLE:
                        questions = [
                            inquirer.Confirm('proceed',
                                           message=message,
                                           default=True)
                        ]
                        answers = inquirer.prompt(questions)
                        if not answers or not answers.get('proceed'):
                            console.print("[yellow]Setup cancelled.[/yellow]")
                            return
                    else:
                        console.print("[yellow]⚠️  .claude directory already exists. Use --force to overwrite or --yes to skip prompts.[/yellow]")
                        return
            
            # Confirm setup
            if not yes:
                console.print()
                console.print("[cyan]This will create:[/cyan]")
                console.print("[dim]  📁 .claude/ directory structure[/dim]")
                console.print("[dim]  📝 14 slash commands (9 spec workflow + 5 bug fix workflow)[/dim]")
                console.print("[dim]  🤖 Auto-generated task commands[/dim]")
                console.print("[dim]  📋 Document templates[/dim]")
                console.print("[dim]  🔧 Python-based task command generation (no NPX required)[/dim]")
                console.print("[dim]  ⚙️  Configuration files[/dim]")
                console.print("[dim]  📖 Complete workflow instructions embedded in each command[/dim]")
                console.print()
                
                if INQUIRER_AVAILABLE:
                    questions = [
                        inquirer.Confirm('confirm',
                                       message='Proceed with setup?',
                                       default=True)
                    ]
                    answers = inquirer.prompt(questions)
                    if not answers or not answers.get('confirm'):
                        console.print("[yellow]Setup cancelled.[/yellow]")
                        return
                else:
                    console.print("[dim]Run with --yes to skip confirmation prompts[/dim]")
            
            # Run setup
            setup_task = progress.add_task("Setting up spec workflow...", total=None)
            await setup.run_setup()
            progress.stop_task(setup_task)
            progress.remove_task(setup_task)
            
            # Success message
            console.print()
            console.print("✅ [bold green]Spec Workflow installed successfully![/bold green]")
            console.print()
            console.print("[cyan]Available commands:[/cyan]")
            console.print("[bold white]📊 Spec Workflow (for new features):[/bold white]")
            console.print("[dim]  /spec-create <feature-name>  - Create a new spec[/dim]")
            console.print("[dim]  /spec-requirements           - Generate requirements[/dim]")
            console.print("[dim]  /spec-design                 - Generate design[/dim]")
            console.print("[dim]  /generate-task-commands      - Generate tasks & offer auto-run[/dim]")
            console.print("[dim]  /spec-execute <task-id>      - Execute individual tasks[/dim]")
            console.print("[dim]  /auto-run-tasks <spec-name>  - Execute all tasks automatically[/dim]")
            console.print("[dim]  /{spec-name}-task-{id}       - Auto-generated task commands[/dim]")
            console.print("[dim]  /spec-status                 - Show status[/dim]")
            console.print("[dim]  /spec-list                   - List all specs[/dim]")
            console.print()
            console.print("[bold white]🐛 Bug Fix Workflow (for bug fixes):[/bold white]")
            console.print("[dim]  /bug-create <bug-name>       - Start bug fix[/dim]")
            console.print("[dim]  /bug-analyze                 - Analyze root cause[/dim]")
            console.print("[dim]  /bug-fix                     - Implement fix[/dim]")
            console.print("[dim]  /bug-verify                  - Verify fix[/dim]")
            console.print("[dim]  /bug-status                  - Show bug status[/dim]")
            console.print()
            console.print("[yellow]Next steps:[/yellow]")
            console.print("[dim]1. Run: claude[/dim]")
            console.print("[dim]2. For new features: /spec-create my-feature[/dim]")
            console.print("[dim]3. For bug fixes: /bug-create my-bug[/dim]")
            console.print()
            console.print("[blue]📖 For help, see the README or run /spec-list[/blue]")
            
        except Exception as error:
            progress.stop()
            console.print(f"[red]Error: {error}[/red]")
            raise click.ClickException(str(error))


@main.command()
def test() -> None:
    """Test the setup in a temporary directory."""
    asyncio.run(_test_async())


async def _test_async() -> None:
    """Async implementation of test command."""
    console.print("🧪 [cyan]Testing setup...[/cyan]")
    
    with tempfile.TemporaryDirectory(prefix='spec-workflow-test-') as temp_dir:
        temp_path = Path(temp_dir)
        
        try:
            setup = SpecWorkflowSetup(temp_path)
            await setup.run_setup()
            
            console.print("✅ [green]Test completed successfully![/green]")
            console.print(f"[dim]Test directory: {temp_path}[/dim]")
            
        except Exception as error:
            console.print(f"❌ [red]Test failed: {error}[/red]")
            raise click.ClickException(str(error))


@main.command('migration-info')
@click.option("--format", type=click.Choice(["json", "yaml", "summary"]), default="summary", help="Output format")
def migration_info(format: str) -> None:
    """Display migration compatibility information for existing .claude directory."""
    asyncio.run(_migration_info_async(format))


async def _migration_info_async(format: str) -> None:
    """Async implementation of migration-info command."""
    console = Console()
    
    try:
        project_path = Path.cwd()
        setup = SpecWorkflowSetup(project_path)
        
        with console.status("[bold green]Analyzing existing setup..."):
            migration_info_data = await setup.get_migration_info()
        
        has_existing = migration_info_data["has_existing_claude"]
        has_typescript = migration_info_data["has_typescript_installation"]
        existing_specs = migration_info_data["existing_specs"]
        existing_bugs = migration_info_data["existing_bugs"]
        is_compatible, issues = migration_info_data["compatibility_check"]
        
        if format == "json":
            import json
            console.print_json(json.dumps(migration_info_data, indent=2))
        elif format == "yaml":
            try:
                import yaml
                console.print(yaml.dump(migration_info_data, default_flow_style=False))
            except ImportError:
                console.print("[red]PyYAML not installed. Use 'json' format instead.[/red]")
        else:
            # Summary format
            console.print("[bold cyan]Migration Compatibility Report[/bold cyan]")
            console.print()
            
            if has_existing:
                console.print("✅ [green]Existing .claude directory detected[/green]")
                
                if has_typescript:
                    console.print("📦 [blue]TypeScript installation found[/blue]")
                else:
                    console.print("🐍 [yellow]Python-only installation[/yellow]")
                
                console.print(f"📊 [dim]{len(existing_specs)} existing spec(s)[/dim]")
                console.print(f"🐛 [dim]{len(existing_bugs)} existing bug report(s)[/dim]")
                
                if is_compatible:
                    console.print("✅ [green]Fully compatible with Python version[/green]")
                else:
                    console.print("⚠️  [yellow]Compatibility issues detected:[/yellow]")
                    for issue in issues:
                        console.print(f"   • [dim]{issue}[/dim]")
            else:
                console.print("❌ [yellow]No existing .claude directory found[/yellow]")
                console.print("[dim]Run 'spec-setup' to initialize the workflow[/dim]")
    
    except Exception as e:
        console.print(f"[red]Error analyzing migration info: {e}[/red]")
        raise click.ClickException(f"Migration analysis failed: {e}")


@main.command('generate-task-commands')
@click.argument('spec_name')
@click.option('-p', '--project', default=None, help='Project directory (default: current directory)')
def generate_task_commands(spec_name: str, project: Optional[str]) -> None:
    """Generate individual task commands for a spec."""
    asyncio.run(_generate_task_commands_async(spec_name, project))


@main.command('auto-run-tasks')
@click.argument('spec_name')
@click.option('-p', '--project', default=None, help='Project directory (default: current directory)')
@click.option('--mode', type=click.Choice(['automatic', 'interactive']), default='automatic', help='Execution mode')
@click.option('--tasks', default=None, help='Task selection (e.g., "all", "1-3", "2,4,6")')
@click.option('--continue-on-error', is_flag=True, help='Continue execution after errors')
@click.option('--resume-from', default=None, help='Resume from specific task ID')
@click.option('--show-progress', is_flag=True, default=True, help='Show detailed progress')
def auto_run_tasks(spec_name: str, project: Optional[str], mode: str, tasks: Optional[str], 
                   continue_on_error: bool, resume_from: Optional[str], show_progress: bool) -> None:
    """Execute all tasks for a spec automatically."""
    asyncio.run(_auto_run_tasks_async(spec_name, project, mode, tasks, continue_on_error, resume_from, show_progress))


async def _generate_task_commands_async(spec_name: str, project: Optional[str]) -> None:
    """Async implementation of generate-task-commands."""
    console.print("🔧 [cyan]Generating task commands...[/cyan]")
    
    project_path = Path(project) if project else Path.cwd()
    spec_dir = project_path / '.claude' / 'specs' / spec_name
    tasks_file = spec_dir / 'tasks.md'
    commands_spec_dir = project_path / '.claude' / 'commands' / spec_name
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        task = progress.add_task(f"Generating commands for spec: {spec_name}", total=None)
        
        try:
            # Check if tasks.md exists
            if not tasks_file.exists():
                progress.stop()
                console.print(f"[red]tasks.md not found at {tasks_file}[/red]")
                raise click.ClickException(f"tasks.md not found at {tasks_file}")
            
            # Read tasks.md
            tasks_content = tasks_file.read_text(encoding='utf-8')
            
            # Create spec commands directory
            commands_spec_dir.mkdir(parents=True, exist_ok=True)
            
            # Parse tasks and generate commands
            tasks = parse_tasks_from_markdown(tasks_content)
            
            task_count = 0
            for parsed_task in tasks:
                await generate_task_command(commands_spec_dir, spec_name, parsed_task)
                task_count += 1
            
            progress.update(task, description=f"Generated {task_count} task commands for spec: {spec_name}")
            progress.stop_task(task)
            progress.remove_task(task)
            
            console.print()
            console.print("[green]Generated commands:[/green]")
            for parsed_task in tasks:
                console.print(f"[dim]  /{spec_name}-task-{parsed_task.id} - {parsed_task.description}[/dim]")
            
            # Workflow Integration: Offer auto-run as an option per Requirement 3.2
            console.print()
            console.print("[bold cyan]🚀 Workflow Options:[/bold cyan]")
            console.print()
            console.print("[yellow]Option 1: Individual Task Execution[/yellow]")
            console.print("[bold yellow]RESTART REQUIRED: You must restart Claude Code for the new commands to be visible[/bold yellow]")
            console.print()
            console.print("[bold cyan]Instructions for the agent:[/bold cyan]")
            console.print("[dim]Tell the user they must exit Claude Code and restart it using:[/dim]")
            console.print("[white]- Run \"claude --continue\" to continue this conversation with new commands[/white]")
            console.print("[white]- Or run \"claude\" to start a fresh session[/white]")
            console.print("[dim]The restart is absolutely necessary for the new task commands to appear.[/dim]")
            console.print()
            console.print("[blue]After restart, you can use commands like:[/blue]")
            if tasks:
                console.print(f"[dim]  /{spec_name}-task-{tasks[0].id}[/dim]")
                if len(tasks) > 1:
                    console.print(f"[dim]  /{spec_name}-task-{tasks[1].id}[/dim]")
                console.print("[dim]  etc.[/dim]")
            
            console.print()
            console.print("[yellow]Option 2: Automated Task Execution (NEW!)[/yellow]")
            console.print("[green]Execute all tasks automatically without restart:[/green]")
            console.print(f"[white]/auto-run-tasks {spec_name}[/white] - Execute all tasks automatically")
            console.print(f"[white]/auto-run-tasks {spec_name} --mode interactive[/white] - Interactive execution with prompts")
            console.print(f"[white]/auto-run-tasks {spec_name} --tasks 1-3[/white] - Execute specific task range")
            console.print()
            console.print("[bold green]✨ Auto-run benefits:[/bold green]")
            console.print("[dim]• No restart required - start immediately[/dim]")
            console.print("[dim]• Execute all tasks sequentially with progress tracking[/dim]")
            console.print("[dim]• Interactive mode for step-by-step control[/dim]")
            console.print("[dim]• Resume functionality if interrupted[/dim]")
            console.print("[dim]• Comprehensive error handling and recovery options[/dim]")
            
            # Integration Enhancement: Offer auto-run prompt per Requirement 3.2
            console.print()
            if await _prompt_for_auto_run(spec_name, len(tasks)):
                console.print("[cyan]🚀 Starting auto-run immediately...[/cyan]")
                # Execute auto-run with default options
                from spec_driven_workflow.auto_run_models import AutoRunOptions, ExecutionMode
                auto_runner = TaskAutoRunner(console)
                options = AutoRunOptions(
                    execution_mode=ExecutionMode.AUTOMATIC,
                    task_selection="all",
                    continue_on_error=False,
                    show_detailed_progress=True
                )
                try:
                    result = await auto_runner.run_all_tasks(spec_name, options)
                    console.print()
                    console.print("[bold green]🎉 Auto-run completed successfully![/bold green]")
                    console.print(f"[green]✅ {result.successful_tasks}/{result.total_tasks} tasks completed[/green]")
                except Exception as e:
                    console.print(f"[red]❌ Auto-run failed: {e}[/red]")
                    console.print("[yellow]💡 You can still use individual task commands after restart[/yellow]")
            else:
                console.print("[blue]💡 You can run auto-run later with: [white]/auto-run-tasks {spec_name}[/white][/blue]")
            
        except Exception as error:
            progress.stop()
            console.print(f"[red]Command generation failed: {error}[/red]")
            raise click.ClickException(str(error))


async def _prompt_for_auto_run(spec_name: str, task_count: int) -> bool:
    """Prompt user whether to run auto-run immediately after task command generation.
    
    Implements Requirement 3.2: Integration with existing spec workflow phases.
    Uses inquirer when available for enhanced UX, with fallback to basic input.
    
    Args:
        spec_name: Name of the specification
        task_count: Number of tasks that would be executed
        
    Returns:
        True if user wants to run auto-run immediately, False otherwise
    """
    if INQUIRER_AVAILABLE:
        questions = [
            inquirer.List('action',
                        message=f'Would you like to execute all {task_count} tasks now with auto-run?',
                        choices=[
                            ('🚀 Yes, execute all tasks automatically', 'yes'),
                            ('📝 No, I\'ll use individual task commands after restart', 'no'),
                            ('🔧 No, I\'ll run auto-run manually later', 'later')
                        ],
                        default='yes')
        ]
        answers = inquirer.prompt(questions)
        if not answers:
            return False
        return answers['action'] == 'yes'
    else:
        # Fallback to basic input
        console.print(f"[bold]Execute all {task_count} tasks automatically now? (y/n)[/bold]")
        console.print("[dim]Press Enter for Yes, or 'n' for No[/dim]")
        
        while True:
            choice = input("Auto-run now? [Y/n]: ").lower().strip()
            if choice in ['', 'y', 'yes']:
                return True
            elif choice in ['n', 'no']:
                return False
            else:
                print("Please enter 'y' for yes or 'n' for no")


async def _ensure_context7_mcp_server(console: Console, project_path: Path, project_types: list[str]) -> None:
    """Ensure context7 MCP server is configured in Claude Code.
    
    Checks if the context7 MCP server is already configured and adds it if missing.
    This provides enhanced context capabilities for Claude Code workflows.
    Implements graceful degradation - setup continues even if server addition fails.
    
    Args:
        console: Rich Console instance for output
        project_path: Path to the project being set up (unused but kept for compatibility)
        project_types: List of detected project types (unused but kept for compatibility)
    """
    from spec_driven_workflow.utils import ensure_context7_mcp_server
    
    console.print()
    console.print("[cyan]🔌 Checking context7 MCP server configuration...[/cyan]")
    
    try:
        # Check and configure context7 MCP server
        success, message = await ensure_context7_mcp_server()
        
        if success:
            console.print(f"✓ [green]{message}[/green]")
        else:
            console.print(f"⚠️  [yellow]{message}[/yellow]")
            console.print("[dim]   context7 provides enhanced context for Claude Code workflows[/dim]")
            console.print("[dim]   You can add it manually with: claude mcp add --transport http context7 https://mcp.context7.com/mcp[/dim]")
                
    except Exception as e:
        # Unexpected error - log but continue setup
        console.print(f"⚠️  [yellow]Error checking context7 MCP server: {e}[/yellow]")
        console.print("[dim]   Setup will continue without context7 MCP server[/dim]")


async def _auto_run_tasks_async(spec_name: str, project: Optional[str], mode: str, tasks: Optional[str], 
                               continue_on_error: bool, resume_from: Optional[str], show_progress: bool) -> None:
    """Async implementation of auto-run-tasks command."""
    console.print("🚀 [cyan]Starting auto-run for spec tasks...[/cyan]")
    
    project_path = Path(project) if project else Path.cwd()
    spec_dir = project_path / '.claude' / 'specs' / spec_name
    tasks_file = spec_dir / 'tasks.md'
    
    # Validate spec exists
    if not spec_dir.exists():
        console.print(f"[red]Spec directory not found: {spec_dir}[/red]")
        raise click.ClickException(f"Spec '{spec_name}' not found")
    
    if not tasks_file.exists():
        console.print(f"[red]tasks.md not found at {tasks_file}[/red]")
        raise click.ClickException(f"tasks.md not found for spec '{spec_name}'")
    
    try:
        # Create auto-run options
        execution_mode = ExecutionMode.AUTOMATIC if mode == 'automatic' else ExecutionMode.INTERACTIVE
        options = AutoRunOptions(
            execution_mode=execution_mode,
            task_selection=tasks,
            continue_on_error=continue_on_error,
            show_detailed_progress=show_progress,
            resume_from_task=resume_from
        )
        
        # Initialize auto runner
        auto_runner = TaskAutoRunner()
        
        # Execute tasks
        if resume_from:
            console.print(f"[yellow]Resuming from task: {resume_from}[/yellow]")
            result = await auto_runner.resume_from_task(spec_name, resume_from, options)
        else:
            result = await auto_runner.run_all_tasks(spec_name, options)
        
        # Display results
        console.print()
        if result.failed_tasks == 0:
            console.print("✅ [bold green]Auto-run completed successfully![/bold green]")
        else:
            console.print(f"⚠️  [yellow]Auto-run completed with {result.failed_tasks} failed tasks[/yellow]")
        
        console.print(f"[dim]  📊 {result.successful_tasks}/{result.total_tasks} tasks completed[/dim]")
        console.print(f"[dim]  ⏱️  Total time: {result.execution_time:.2f} seconds[/dim]")
        console.print()
        console.print(result.summary_message)
        
    except Exception as error:
        console.print(f"[red]Auto-run failed: {error}[/red]")
        raise click.ClickException(str(error))


if __name__ == "__main__":
    main()