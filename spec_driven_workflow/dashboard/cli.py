"""Dashboard CLI entry point for spec monitoring.

This module provides the CLI interface for the dashboard functionality,
replacing the TypeScript dashboard server with a Rich-based terminal interface.
"""

import asyncio
import signal
import sys
from pathlib import Path
from typing import Optional

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from .parser import SpecParser
from .watcher import SpecWatcher, SpecChangeEvent, GitChangeEvent, SteeringChangeEvent
from .terminal import TerminalDashboard

console = Console()


class DashboardManager:
    """Manager for the dashboard functionality."""
    
    def __init__(self, project_path: Path, port: int = 3000, auto_open: bool = False):
        self.project_path = project_path
        self.port = port
        self.auto_open = auto_open
        self.parser = SpecParser(project_path)
        self.watcher: Optional[SpecWatcher] = None
        self._running = False
    
    async def start(self) -> None:
        """Start the dashboard monitoring."""
        console.print("🚀 [bold cyan]Claude Code Spec Dashboard[/bold cyan]")
        console.print("[dim]Real-time spec and task monitoring[/dim]")
        console.print()
        
        # Check if .claude directory exists
        claude_path = self.project_path / '.claude'
        if not claude_path.exists():
            console.print("❌ [red]Error: .claude directory not found[/red]")
            console.print("[yellow]Make sure you are in a project with Claude Code Spec Workflow installed[/yellow]")
            console.print("[dim]Run: uvx spec-driven-workflow setup[/dim]")
            return
        
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
        ) as progress:
            task = progress.add_task("Starting dashboard server...", total=None)
            
            try:
                # Initialize the file watcher
                self.watcher = SpecWatcher(self.project_path, self._handle_change)
                await self.watcher.start_watching()
                
                progress.update(task, description="Dashboard started successfully")
                progress.stop_task(task)
                progress.remove_task(task)
                
                console.print(f"✅ [green]Dashboard running for project: {self.project_path}[/green]")
                console.print()
                console.print("[dim]Press Ctrl+C to stop the dashboard[/dim]")
                console.print()
                
                # Display initial spec status
                await self._display_specs()
                
                # Keep the dashboard running
                self._running = True
                while self._running:
                    await asyncio.sleep(1)
                
            except Exception as error:
                progress.stop()
                console.print(f"[red]Failed to start dashboard: {error}[/red]")
                raise
    
    async def stop(self) -> None:
        """Stop the dashboard monitoring."""
        self._running = False
        if self.watcher:
            await self.watcher.stop_watching()
    
    async def _handle_change(self, event) -> None:
        """Handle file system change events."""
        if isinstance(event, SpecChangeEvent):
            console.print(f"📝 [cyan]Spec change detected:[/cyan] {event.spec}/{event.file} ({event.type})")
            if event.data:
                status_color = self._get_status_color(event.data.status)
                console.print(f"   Status: [{status_color}]{event.data.status}[/{status_color}]")
        
        elif isinstance(event, GitChangeEvent):
            console.print(f"🔀 [blue]Git change detected:[/blue] {event.type}")
            if event.branch:
                console.print(f"   Branch: [bold]{event.branch}[/bold]")
            if event.commit:
                console.print(f"   Commit: [dim]{event.commit}[/dim]")
        
        elif isinstance(event, SteeringChangeEvent):
            console.print(f"📋 [magenta]Steering change detected:[/magenta] {event.file} ({event.type})")
    
    async def _display_specs(self) -> None:
        """Display current spec status."""
        specs = await self.parser.get_all_specs()
        
        if not specs:
            console.print("[dim]No specs found in this project.[/dim]")
            return
        
        console.print(f"[bold]Found {len(specs)} spec(s):[/bold]")
        console.print()
        
        for spec in specs:
            status_color = self._get_status_color(spec.status)
            console.print(f"📊 [bold]{spec.display_name}[/bold]")
            console.print(f"   Status: [{status_color}]{spec.status}[/{status_color}]")
            
            if spec.tasks and spec.tasks.get('total', 0) > 0:
                completed = spec.tasks.get('completed', 0)
                total = spec.tasks.get('total', 0)
                progress_pct = (completed / total * 100) if total > 0 else 0
                console.print(f"   Progress: {completed}/{total} tasks ({progress_pct:.1f}%)")
            
            if spec.last_modified:
                console.print(f"   Last modified: [dim]{spec.last_modified.strftime('%Y-%m-%d %H:%M')}[/dim]")
            
            console.print()
    
    def _get_status_color(self, status: str) -> str:
        """Get color for spec status."""
        color_map = {
            'not-started': 'dim',
            'requirements': 'yellow',
            'design': 'blue',
            'tasks': 'cyan',
            'in-progress': 'magenta',
            'completed': 'green'
        }
        return color_map.get(status, 'white')


@click.group()
def main() -> None:
    """Spec Dashboard - Monitor spec progress and status."""
    pass


@main.command()
@click.option('-d', '--dir', default=None, help='Project directory containing .claude')
@click.option('--legacy', is_flag=True, help='Use legacy simple dashboard interface')
def start(dir: Optional[str], legacy: bool) -> None:
    """Start the dashboard monitoring."""
    project_path = Path(dir) if dir else Path.cwd()
    
    async def run_dashboard():
        if legacy:
            # Use the legacy simple dashboard manager
            dashboard = DashboardManager(project_path, 3000, False)
        else:
            # Use the new Rich terminal dashboard
            dashboard = TerminalDashboard(project_path)
        
        # Set up signal handlers for graceful shutdown
        def signal_handler():
            console.print("\n[yellow]Shutting down dashboard...[/yellow]")
            asyncio.create_task(dashboard.stop())
        
        if sys.platform != 'win32':
            loop = asyncio.get_event_loop()
            for sig in [signal.SIGINT, signal.SIGTERM]:
                loop.add_signal_handler(sig, signal_handler)
        
        try:
            await dashboard.start()
        except KeyboardInterrupt:
            console.print("\n[yellow]Dashboard stopped by user[/yellow]")
        except Exception as e:
            console.print(f"[red]Dashboard error: {e}[/red]")
        finally:
            await dashboard.stop()
    
    # Run the async dashboard
    try:
        asyncio.run(run_dashboard())
    except KeyboardInterrupt:
        console.print("\n[yellow]Dashboard stopped[/yellow]")


if __name__ == "__main__":
    main()