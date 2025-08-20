"""File system monitoring for spec changes.

This module provides file watching functionality using the watchdog library,
porting the TypeScript watcher.ts functionality to Python with identical patterns.
"""

import asyncio
import sys
from pathlib import Path
from typing import Callable, Optional, Union

from watchdog.events import FileSystemEventHandler, FileSystemEvent, DirCreatedEvent, DirDeletedEvent
from watchdog.observers import Observer
from watchdog.observers.polling import PollingObserver

from .parser import SpecParser, SpecStatus, SteeringStatus
from ..git import GitUtils


def debug(message: str) -> None:
    """Debug logging function matching TypeScript implementation."""
    print(f"[DEBUG] {message}", file=sys.stderr)


class SpecChangeEvent:
    """Event representing a change to a spec file."""
    
    def __init__(self, change_type: str, spec: str, file: str, data: Optional[SpecStatus] = None):
        self.type = change_type  # 'added', 'changed', 'removed'
        self.spec = spec
        self.file = file
        self.data = data


class GitChangeEvent:
    """Event representing a Git repository change."""
    
    def __init__(self, change_type: str, branch: Optional[str] = None, commit: Optional[str] = None):
        self.type = change_type  # 'branch-changed', 'commit-changed'
        self.branch = branch  
        self.commit = commit


class SteeringChangeEvent:
    """Event representing a steering document change."""
    
    def __init__(self, change_type: str, file: str, steering_status: Optional[SteeringStatus] = None):
        self.type = change_type  # 'added', 'changed', 'removed'
        self.file = file
        self.steering_status = steering_status


class SpecFileHandler(FileSystemEventHandler):
    """Handler for spec file system events."""
    
    def __init__(self, callback: Callable, parser: SpecParser):
        self.callback = callback
        self.parser = parser
    
    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            asyncio.create_task(self._handle_file_change('added', event.src_path))
    
    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            asyncio.create_task(self._handle_file_change('changed', event.src_path))
    
    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            asyncio.create_task(self._handle_file_change('removed', event.src_path))
    
    async def _handle_file_change(self, change_type: str, file_path: str):
        """Handle file system change events."""
        path = Path(file_path)
        parts = path.relative_to(path.parents[1]).parts  # Get relative path from specs directory
        
        if len(parts) >= 2:
            spec_name = parts[0]
            file_name = parts[1]
            
            if file_name in ['requirements.md', 'design.md', 'tasks.md']:
                # Add delay for file write completion
                if change_type == 'changed':
                    await asyncio.sleep(0.1)
                
                spec = await self.parser.get_spec(spec_name) if change_type != 'removed' else None
                
                event = SpecChangeEvent(
                    change_type=change_type,
                    spec=spec_name,
                    file=file_name,
                    data=spec
                )
                
                await self.callback(event)


class SteeringFileHandler(FileSystemEventHandler):
    """Handler for steering document file system events."""
    
    def __init__(self, callback: Callable, parser: SpecParser):
        self.callback = callback
        self.parser = parser
    
    def on_created(self, event: FileSystemEvent):
        if not event.is_directory:
            asyncio.create_task(self._handle_steering_change('added', event.src_path))
    
    def on_modified(self, event: FileSystemEvent):
        if not event.is_directory:
            asyncio.create_task(self._handle_steering_change('changed', event.src_path))
    
    def on_deleted(self, event: FileSystemEvent):
        if not event.is_directory:
            asyncio.create_task(self._handle_steering_change('removed', event.src_path))
    
    async def _handle_steering_change(self, change_type: str, file_path: str):
        """Handle steering document change events."""
        file_name = Path(file_path).name
        
        if file_name in ['product.md', 'tech.md', 'structure.md']:
            steering_status = await self.parser.get_project_steering_status()
            
            event = SteeringChangeEvent(
                change_type=change_type,
                file=file_name,
                steering_status=steering_status
            )
            
            await self.callback(event)


class SpecWatcher:
    """File system watcher for monitoring spec and steering document changes.
    
    This class exactly replicates the TypeScript SpecWatcher behavior using the
    watchdog library instead of chokidar, maintaining identical event patterns.
    """
    
    def __init__(self, project_path: Union[str, Path], parser: SpecParser):
        """Initialize the watcher.
        
        Args:
            project_path: Path to the project root directory.
            parser: SpecParser instance for parsing spec files.
        """
        self.project_path = Path(project_path).resolve()
        self.parser = parser
        self.git_utils = GitUtils(self.project_path)
        
        # Watchers for different file types (matching TypeScript names)
        self._watcher: Optional[Observer] = None
        self._git_watcher: Optional[Observer] = None
        self._steering_watcher: Optional[Observer] = None
        
        # Git state tracking
        self._last_branch: Optional[str] = None
        self._last_commit: Optional[str] = None
        
        # Event callbacks
        self._callbacks = []
    
    def on(self, event_type: str, callback: Callable) -> None:
        """Add event listener (matching TypeScript EventEmitter pattern)."""
        self._callbacks.append((event_type, callback))
    
    def emit(self, event_type: str, data) -> None:
        """Emit event to all listeners (matching TypeScript EventEmitter pattern)."""
        for cb_type, callback in self._callbacks:
            if cb_type == event_type:
                asyncio.create_task(callback(data))
    
    async def start(self) -> None:
        """Start watching for file system changes (matching TypeScript method name)."""
        specs_path = self.project_path / '.claude' / 'specs'
        
        debug(f"[Watcher] Starting to watch: {specs_path}")
        
        # Detect platform for optimal watching strategy (matching TypeScript logic)
        is_macos = sys.platform == 'darwin'
        
        if specs_path.exists():
            # Use polling observer on non-macOS or PollingObserver when needed
            observer_class = Observer if is_macos else PollingObserver
            self._watcher = observer_class()
            
            # Create handler with file change logic
            handler = EnhancedSpecFileHandler(self)
            self._watcher.schedule(handler, str(specs_path), recursive=True)
            self._watcher.start()
            
            debug('[Watcher] Initial scan complete. Ready for changes.')
        
        # Start watching git files
        await self._start_git_watcher()
        
        # Start watching steering documents  
        await self._start_steering_watcher()
    
    async def stop(self) -> None:
        """Stop all watchers (matching TypeScript method name)."""
        if self._watcher:
            self._watcher.stop()
            self._watcher.join()
        
        if self._git_watcher:
            self._git_watcher.stop()
            self._git_watcher.join()
        
        if self._steering_watcher:
            self._steering_watcher.stop()
            self._steering_watcher.join()
    
    async def _start_git_watcher(self) -> None:
        """Start watching git repository changes."""
        git_path = self.project_path / '.git'
        
        # Check if it's a git repository
        try:
            current_branch = await self.git_utils.get_current_branch()
            if not current_branch:
                debug(f"[GitWatcher] {self.project_path} is not a git repository")
                return
        except Exception:
            debug(f"[GitWatcher] Could not check git status for {self.project_path}")
            return
        
        # Get initial git state
        try:
            self._last_branch = current_branch
            commit_hash = await self.git_utils.get_current_commit()
            self._last_commit = commit_hash[:7] if commit_hash else None
            
            debug(f"[GitWatcher] Initial state - branch: {self._last_branch}, commit: {self._last_commit}")
        except Exception as error:
            print(f"[GitWatcher] Error getting initial state: {error}", file=sys.stderr)
        
        # Watch specific git files that indicate changes
        if git_path.exists():
            self._git_watcher = Observer()
            git_handler = GitFileHandler(self)
            
            # Watch git directory for HEAD, refs changes
            self._git_watcher.schedule(git_handler, str(git_path), recursive=True)
            self._git_watcher.start()
    
    async def _start_steering_watcher(self) -> None:
        """Start watching steering documents."""
        steering_path = self.project_path / '.claude' / 'steering'
        
        debug(f"[SteeringWatcher] Starting to watch: {steering_path}")
        
        # Use appropriate observer based on platform
        is_macos = sys.platform == 'darwin'
        observer_class = Observer if is_macos else PollingObserver
        
        self._steering_watcher = observer_class()
        handler = EnhancedSteeringFileHandler(self)
        
        if steering_path.exists():
            self._steering_watcher.schedule(handler, str(steering_path), recursive=False)
        
        self._steering_watcher.start()
        debug('[SteeringWatcher] Initial scan complete. Ready for changes.')
    
    async def handle_file_change(self, change_type: str, file_path: str) -> None:
        """Handle file change events (matching TypeScript method name)."""
        debug(f"File change detected: {change_type} - {file_path}")
        path = Path(file_path)
        
        # Get relative path from specs directory
        try:
            specs_path = self.project_path / '.claude' / 'specs'
            relative_path = path.relative_to(specs_path)
            parts = relative_path.parts
            
            if len(parts) >= 2:
                spec_name = parts[0]
                file_name = parts[1]
                
                if file_name in ['requirements.md', 'design.md', 'tasks.md']:
                    # Add delay for file write completion (matching TypeScript)
                    if change_type == 'changed':
                        await asyncio.sleep(0.1)
                    
                    spec = await self.parser.get_spec(spec_name) if change_type != 'removed' else None
                    debug(f"Emitting change for spec: {spec_name}, file: {file_name}")
                    
                    # Log approval status for debugging (matching TypeScript)
                    if file_name == 'tasks.md' and spec and spec.tasks:
                        debug(f"Tasks approved: {spec.tasks.get('approved', False)}")
                    
                    self.emit('change', SpecChangeEvent(
                        change_type=change_type,
                        spec=spec_name,
                        file=file_name,
                        data=spec
                    ))
        except ValueError:
            # Path is not relative to specs directory
            pass
    
    async def handle_steering_change(self, change_type: str, file_name: str) -> None:
        """Handle steering document change events (matching TypeScript method name)."""
        debug(f"Steering change detected: {change_type} - {file_name}")
        
        if file_name in ['product.md', 'tech.md', 'structure.md']:
            steering_status = await self.parser.get_project_steering_status()
            
            self.emit('steering-change', SteeringChangeEvent(
                change_type=change_type,
                file=file_name,
                steering_status=steering_status
            ))
    
    async def check_git_changes(self) -> None:
        """Check for git repository changes (matching TypeScript method name)."""
        try:
            current_branch = await self.git_utils.get_current_branch()
            commit_hash = await self.git_utils.get_current_commit()
            current_commit = commit_hash[:7] if commit_hash else None
            
            changed = False
            event_type = 'branch-changed'
            
            if current_branch != self._last_branch:
                debug(f"[GitWatcher] Branch changed from {self._last_branch} to {current_branch}")
                self._last_branch = current_branch
                changed = True
                event_type = 'branch-changed'
            
            if current_commit != self._last_commit:
                debug(f"[GitWatcher] Commit changed from {self._last_commit} to {current_commit}")
                self._last_commit = current_commit
                changed = True
                event_type = 'commit-changed'
                
            if changed:
                self.emit('git-change', GitChangeEvent(
                    change_type=event_type,
                    branch=current_branch,
                    commit=current_commit
                ))
        except Exception as error:
            print(f"[GitWatcher] Error checking git changes: {error}", file=sys.stderr)
    
    async def check_new_spec_directory(self, dir_path: str) -> None:
        """Check new spec directory for existing files (matching TypeScript method name)."""
        spec_name = Path(dir_path).name
        spec = await self.parser.get_spec(spec_name)
        
        if spec:
            debug(f"Found spec in new directory: {spec_name}")
            self.emit('change', SpecChangeEvent(
                change_type='added',
                spec=spec_name,
                file='directory',
                data=spec
            ))


class EnhancedSpecFileHandler(FileSystemEventHandler):
    """Enhanced spec file handler matching TypeScript chokidar patterns."""
    
    def __init__(self, watcher: SpecWatcher):
        self.watcher = watcher
    
    def on_created(self, event: FileSystemEvent):
        """Handle file creation events."""
        if not event.is_directory:
            debug(f"[Watcher] File added: {event.src_path}")
            asyncio.create_task(self.watcher.handle_file_change('added', event.src_path))
        else:
            debug(f"[Watcher] Directory added: {event.src_path}")
            # Check if this is a top-level spec directory
            path = Path(event.src_path)
            specs_path = self.watcher.project_path / '.claude' / 'specs'
            try:
                relative_path = path.relative_to(specs_path)
                if len(relative_path.parts) == 1:  # Top-level directory
                    asyncio.create_task(self.watcher.check_new_spec_directory(str(relative_path)))
            except ValueError:
                pass
    
    def on_modified(self, event: FileSystemEvent):
        """Handle file modification events."""
        if not event.is_directory:
            debug(f"[Watcher] File changed: {event.src_path}")
            asyncio.create_task(self.watcher.handle_file_change('changed', event.src_path))
    
    def on_deleted(self, event: FileSystemEvent):
        """Handle file deletion events."""
        if not event.is_directory:
            debug(f"[Watcher] File removed: {event.src_path}")
            asyncio.create_task(self.watcher.handle_file_change('removed', event.src_path))
        else:
            debug(f"[Watcher] Directory removed: {event.src_path}")
            # Check if this is a top-level spec directory
            path = Path(event.src_path)
            specs_path = self.watcher.project_path / '.claude' / 'specs'
            try:
                relative_path = path.relative_to(specs_path)
                if len(relative_path.parts) == 1:  # Top-level directory
                    spec_name = relative_path.parts[0]
                    self.watcher.emit('change', SpecChangeEvent(
                        change_type='removed',
                        spec=spec_name,
                        file='directory',
                        data=None
                    ))
            except ValueError:
                pass


class EnhancedSteeringFileHandler(FileSystemEventHandler):
    """Enhanced steering file handler matching TypeScript patterns."""
    
    def __init__(self, watcher: SpecWatcher):
        self.watcher = watcher
    
    def on_created(self, event: FileSystemEvent):
        """Handle steering file creation."""
        if not event.is_directory:
            file_name = Path(event.src_path).name
            debug(f"[SteeringWatcher] File added: {file_name}")
            asyncio.create_task(self.watcher.handle_steering_change('added', file_name))
    
    def on_modified(self, event: FileSystemEvent):
        """Handle steering file modification."""
        if not event.is_directory:
            file_name = Path(event.src_path).name
            debug(f"[SteeringWatcher] File changed: {file_name}")
            asyncio.create_task(self.watcher.handle_steering_change('changed', file_name))
    
    def on_deleted(self, event: FileSystemEvent):
        """Handle steering file deletion."""
        if not event.is_directory:
            file_name = Path(event.src_path).name
            debug(f"[SteeringWatcher] File removed: {file_name}")
            asyncio.create_task(self.watcher.handle_steering_change('removed', file_name))


class GitFileHandler(FileSystemEventHandler):
    """Git file handler for detecting repository changes."""
    
    def __init__(self, watcher: SpecWatcher):
        self.watcher = watcher
    
    def on_modified(self, event: FileSystemEvent):
        """Handle git file modifications."""
        if not event.is_directory:
            file_name = Path(event.src_path).name
            src_path = event.src_path
            
            # Watch for specific git files that indicate changes (matching TypeScript logic)
            if (file_name in ['HEAD', 'index'] or 
                'refs/heads' in src_path or 
                'logs/HEAD' in src_path):
                debug(f"[GitWatcher] Git file changed: {src_path}")
                asyncio.create_task(self.watcher.check_git_changes())
    
    def on_created(self, event: FileSystemEvent):
        """Handle git file creation."""
        if not event.is_directory:
            file_name = Path(event.src_path).name
            src_path = event.src_path
            
            if (file_name in ['HEAD', 'index'] or 
                'refs/heads' in src_path or 
                'logs/HEAD' in src_path):
                debug(f"[GitWatcher] Git file added: {src_path}")
                asyncio.create_task(self.watcher.check_git_changes())