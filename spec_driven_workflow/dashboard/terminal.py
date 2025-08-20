"""Rich-based terminal dashboard for spec monitoring.

This module provides the terminal dashboard implementation, converting the
TypeScript web dashboard server logic to a Rich-based terminal interface.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Union

from rich.align import Align
from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich.layout import Layout
from rich.progress import Progress, BarColumn, TextColumn, TimeElapsedColumn

from .parser import SpecParser, SpecStatus, SteeringStatus
from .watcher import SpecWatcher, SpecChangeEvent, GitChangeEvent, SteeringChangeEvent
from ..git import GitUtils


class TerminalDashboard:
    """Rich-based terminal dashboard for spec monitoring."""
    
    def __init__(self, project_path: Union[str, Path]) -> None:
        """Initialize the terminal dashboard.
        
        Args:
            project_path: Path to the project root directory.
        """
        self.project_path = Path(project_path).resolve()
        self.console = Console()
        self.parser = SpecParser(self.project_path)
        self.git_utils = GitUtils(self.project_path)
        self.watcher: Optional[SpecWatcher] = None
        
        self._specs: List[SpecStatus] = []
        self._git_info: Dict = {}
        self._steering_status: SteeringStatus = SteeringStatus()
        self._project_name = self.project_path.name
        self._last_update = datetime.now()
        self._running = False
        
        # Layout structure
        self.layout = Layout()
        self._setup_layout()
    
    def _setup_layout(self) -> None:
        """Set up the dashboard layout."""
        self.layout.split(
            Layout(name="header", size=3),
            Layout(name="main"),
            Layout(name="footer", size=3)
        )
        
        self.layout["main"].split_row(
            Layout(name="specs", ratio=2),
            Layout(name="details", ratio=1)
        )
    
    async def start(self) -> None:
        """Start the terminal dashboard monitoring."""
        # Load initial data
        await self._load_initial_data()
        
        # Set up file watcher
        self.watcher = SpecWatcher(self.project_path, self.parser)
        
        # Set up event listeners (matching TypeScript EventEmitter pattern)
        self.watcher.on('change', self._handle_spec_change)
        self.watcher.on('git-change', self._handle_git_change)
        self.watcher.on('steering-change', self._handle_steering_change)
        
        await self.watcher.start()
        
        # Start the live display
        self._running = True
        with Live(self._render_dashboard(), console=self.console, refresh_per_second=2) as live:
            self._live = live
            while self._running:
                await asyncio.sleep(0.5)
                live.update(self._render_dashboard())
    
    async def stop(self) -> None:
        """Stop the dashboard monitoring."""
        self._running = False
        if self.watcher:
            await self.watcher.stop()
    
    async def _load_initial_data(self) -> None:
        """Load initial dashboard data."""
        # Load specs
        self._specs = await self.parser.get_all_specs()
        
        # Load git info
        try:
            current_branch = await self.git_utils.get_current_branch()
            remote_url = await self.git_utils.get_remote_url()
            github_url = await self.git_utils.get_github_url()
            is_clean = await self.git_utils.is_repo_clean()
            
            self._git_info = {
                'branch': current_branch,
                'remote_url': remote_url,
                'github_url': github_url,
                'is_clean': is_clean
            }
        except Exception:
            self._git_info = {}
        
        # Load steering status
        self._steering_status = await self.parser.get_project_steering_status()
    
    async def _handle_spec_change(self, event: SpecChangeEvent) -> None:
        """Handle spec file change events."""
        # Update specs data
        self._specs = await self.parser.get_all_specs()
        self._last_update = datetime.now()
    
    async def _handle_git_change(self, event: GitChangeEvent) -> None:
        """Handle git repository change events."""
        # Update git info
        await self._load_git_info()
        self._last_update = datetime.now()
    
    async def _handle_steering_change(self, event: SteeringChangeEvent) -> None:
        """Handle steering document change events."""
        # Update steering status
        self._steering_status = event.steering_status or SteeringStatus()
        self._last_update = datetime.now()
    
    async def _load_git_info(self) -> None:
        """Load git information."""
        try:
            current_branch = await self.git_utils.get_current_branch()
            is_clean = await self.git_utils.is_repo_clean()
            
            self._git_info.update({
                'branch': current_branch,
                'is_clean': is_clean
            })
        except Exception:
            pass
    
    def _render_dashboard(self) -> Layout:
        """Render the complete dashboard."""
        # Update layout content
        self.layout["header"].update(self._render_header())
        self.layout["specs"].update(self._render_specs())
        self.layout["details"].update(self._render_details())
        self.layout["footer"].update(self._render_footer())
        
        return self.layout
    
    def _render_header(self) -> Panel:
        """Render the dashboard header."""
        title = f"🚀 Claude Code Spec Dashboard - {self._project_name}"
        
        # Build status line
        status_parts = []
        
        # Git status
        if self._git_info.get('branch'):
            branch_color = "green" if self._git_info.get('is_clean') else "yellow"
            status_parts.append(f"🔀 [{branch_color}]{self._git_info['branch']}[/{branch_color}]")
        
        # Steering status
        if self._steering_status.exists:
            steering_count = sum([
                self._steering_status.has_product,
                self._steering_status.has_tech,
                self._steering_status.has_structure
            ])
            status_parts.append(f"📋 [{steering_count}/3 steering docs]")
        
        # Spec count
        status_parts.append(f"📊 [{len(self._specs)} specs]")
        
        status_line = " | ".join(status_parts) if status_parts else "Ready"
        
        content = Group(
            Align.center(Text(title, style="bold cyan")),
            Align.center(Text(status_line, style="dim"))
        )
        
        return Panel(content, style="bright_blue")
    
    def _render_specs(self) -> Panel:
        """Render the specs overview."""
        if not self._specs:
            return Panel(
                Align.center("No specs found in this project.", vertical="middle"),
                title="📊 Specifications",
                style="dim"
            )
        
        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Spec", style="cyan", no_wrap=True)
        table.add_column("Status", style="white", no_wrap=True)
        table.add_column("Progress", style="white")
        table.add_column("Last Modified", style="dim", no_wrap=True)
        
        for spec in self._specs:
            # Status with color
            status_colors = {
                'not-started': 'dim',
                'requirements': 'yellow',
                'design': 'blue',
                'tasks': 'cyan',
                'in-progress': 'magenta',
                'completed': 'green'
            }
            status_color = status_colors.get(spec.status, 'white')
            status_text = f"[{status_color}]{spec.status}[/{status_color}]"
            
            # Progress bar
            progress_text = ""
            if spec.tasks and spec.tasks.get('total', 0) > 0:
                completed = spec.tasks.get('completed', 0)
                total = spec.tasks.get('total', 0)
                percentage = (completed / total * 100) if total > 0 else 0
                
                # Create a simple progress bar
                bar_width = 20
                filled_width = int(bar_width * percentage // 100)
                bar = "█" * filled_width + "░" * (bar_width - filled_width)
                progress_text = f"{bar} {completed}/{total} ({percentage:.1f}%)"
            else:
                progress_text = "—"
            
            # Last modified
            modified_text = "—"
            if spec.last_modified:
                modified_text = spec.last_modified.strftime("%m/%d %H:%M")
            
            table.add_row(
                spec.display_name,
                status_text,
                progress_text,
                modified_text
            )
        
        return Panel(table, title="📊 Specifications", style="bright_blue")
    
    def _render_details(self) -> Panel:
        """Render the details panel."""
        # Create sections for different information
        sections = []
        
        # Git Information
        if self._git_info:
            git_table = Table(show_header=False, box=None, padding=(0, 1))
            git_table.add_column("Key", style="bold")
            git_table.add_column("Value")
            
            if self._git_info.get('branch'):
                branch_color = "green" if self._git_info.get('is_clean') else "yellow"
                status_text = "clean" if self._git_info.get('is_clean') else "dirty"
                git_table.add_row("Branch:", f"[{branch_color}]{self._git_info['branch']}[/{branch_color}]")
                git_table.add_row("Status:", f"[{branch_color}]{status_text}[/{branch_color}]")
            
            if self._git_info.get('remote_url'):
                git_table.add_row("Remote:", self._git_info['remote_url'])
            
            sections.append(Panel(git_table, title="🔀 Git Info", style="blue"))
        
        # Steering Documents
        if self._steering_status.exists:
            steering_table = Table(show_header=False, box=None, padding=(0, 1))
            steering_table.add_column("Document", style="bold")
            steering_table.add_column("Status")
            
            docs = [
                ("product.md", self._steering_status.has_product),
                ("tech.md", self._steering_status.has_tech),
                ("structure.md", self._steering_status.has_structure)
            ]
            
            for doc_name, exists in docs:
                status = "[green]✓[/green]" if exists else "[red]✗[/red]"
                steering_table.add_row(doc_name, status)
            
            sections.append(Panel(steering_table, title="📋 Steering", style="magenta"))
        
        # Recent Activity
        activity_text = f"Last updated: {self._last_update.strftime('%H:%M:%S')}"
        sections.append(Panel(activity_text, title="🕒 Activity", style="dim"))
        
        # Combine sections
        if sections:
            return Panel(Group(*sections), title="Details", style="bright_green")
        else:
            return Panel(
                Align.center("No additional details available.", vertical="middle"),
                title="Details",
                style="dim"
            )
    
    def _render_footer(self) -> Panel:
        """Render the dashboard footer."""
        help_text = "Press [bold]Ctrl+C[/bold] to exit dashboard"
        return Panel(
            Align.center(Text(help_text, style="dim")),
            style="bright_black"
        )
    
    def render_spec_progress(self, specs: List[SpecStatus]) -> None:
        """Render spec progress information (for compatibility)."""
        # This method provides compatibility with the design interface
        # The actual rendering is handled by the live dashboard
        self._specs = specs