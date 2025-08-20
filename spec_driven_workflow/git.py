"""Git operations wrapper for repository analysis.

This module provides Git operations functionality including branch detection,
remote URL extraction, and repository status checking. Converted from
reference/src/git.ts using GitPython instead of simple-git.
"""

import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

try:
    import git
    from git import Repo, InvalidGitRepositoryError
    GIT_AVAILABLE = True
except ImportError:
    GIT_AVAILABLE = False


@dataclass
class GitInfo:
    """Git repository information.
    
    Matches the TypeScript GitInfo interface for compatibility.
    """
    branch: Optional[str] = None
    remote_url: Optional[str] = None
    github_url: Optional[str] = None


class GitUtils:
    """Git operations utility class.
    
    Provides methods for analyzing Git repositories and extracting
    information needed for the dashboard and workflow context.
    """

    def __init__(self, project_path: Path) -> None:
        """Initialize with project path.
        
        Args:
            project_path: Path to the project root directory.
        """
        self.project_path = project_path

    async def get_current_branch(self) -> Optional[str]:
        """Get the current Git branch name.
        
        Returns:
            Current branch name or None if not in a Git repository.
        """
        if not GIT_AVAILABLE:
            return None
            
        try:
            repo = Repo(self.project_path)
            return repo.active_branch.name
        except (InvalidGitRepositoryError, TypeError):
            return None

    async def get_remote_url(self) -> Optional[str]:
        """Get the remote repository URL.
        
        Returns:
            Remote repository URL or None if no remote configured.
        """
        if not GIT_AVAILABLE:
            return None
            
        try:
            repo = Repo(self.project_path)
            if 'origin' in repo.remotes:
                origin = repo.remotes.origin
                if origin.urls:
                    return next(iter(origin.urls))
        except (InvalidGitRepositoryError, IndexError):
            pass
        return None

    async def is_repo_clean(self) -> bool:
        """Check if the repository has uncommitted changes.
        
        Returns:
            True if the repository is clean, False if there are uncommitted changes.
        """
        if not GIT_AVAILABLE:
            return True
            
        try:
            repo = Repo(self.project_path)
            return not repo.is_dirty()
        except InvalidGitRepositoryError:
            return True

    async def get_github_url(self) -> Optional[str]:
        """Get the GitHub URL for the repository.
        
        Returns:
            GitHub URL or None if not a GitHub repository.
        """
        remote_url = await self.get_remote_url()
        if not remote_url:
            return None
        return self._convert_to_github_url(remote_url)

    async def get_git_info(self) -> GitInfo:
        """Get comprehensive Git repository information.
        
        Returns:
            GitInfo object with branch, remote URL, and GitHub URL.
        """
        info = GitInfo()
        
        if not GIT_AVAILABLE:
            return info
        
        try:
            # Check if it's a git repository
            repo = Repo(self.project_path)
            
            # Get current branch
            try:
                info.branch = repo.active_branch.name
            except TypeError:
                # Detached HEAD state
                info.branch = None
            
            # Get remote origin URL
            if 'origin' in repo.remotes:
                origin = repo.remotes.origin
                if origin.urls:
                    info.remote_url = next(iter(origin.urls))
                    # Convert to GitHub URL if it's a git URL
                    info.github_url = self._convert_to_github_url(info.remote_url)
                    
        except InvalidGitRepositoryError:
            # Not a git repository
            pass
        except Exception:
            # Git not available or other error
            pass
        
        return info

    @staticmethod
    def _convert_to_github_url(remote_url: str) -> Optional[str]:
        """Convert Git remote URL to GitHub web URL.
        
        Args:
            remote_url: Git remote URL (SSH or HTTPS).
            
        Returns:
            GitHub web URL or None if not a supported Git hosting service.
        """
        if not remote_url:
            return None

        # Handle SSH format: git@github.com:user/repo.git
        if remote_url.startswith('git@github.com:'):
            path = remote_url[len('git@github.com:'):].replace('.git', '')
            return f"https://github.com/{path}"

        # Handle HTTPS format: https://github.com/user/repo.git
        if remote_url.startswith('https://github.com/'):
            return remote_url.replace('.git', '')

        # Handle other Git hosting services
        git_host_patterns = [
            # GitLab
            (re.compile(r'git@gitlab\.com:(.+)\.git'), r'https://gitlab.com/\1'),
            (re.compile(r'https://gitlab\.com/(.+)\.git'), r'https://gitlab.com/\1'),
            # Bitbucket
            (re.compile(r'git@bitbucket\.org:(.+)\.git'), r'https://bitbucket.org/\1'),
            (re.compile(r'https://bitbucket\.org/(.+)\.git'), r'https://bitbucket.org/\1'),
            # Github
            (re.compile(r'git@github\.com:(.+)\.git'), r'https://github.com/\1'),
            (re.compile(r'https://github\.com/(.+)\.git'), r'https://github.com/\1'),
        ]

        for pattern, replacement in git_host_patterns:
            match = pattern.match(remote_url)
            if match:
                return pattern.sub(replacement, remote_url)

        return None

    @staticmethod
    async def get_git_info_static(project_path: Path) -> GitInfo:
        """Static method to get Git info for a project path.
        
        Args:
            project_path: Path to the project directory.
            
        Returns:
            GitInfo object with repository information.
        """
        git_utils = GitUtils(project_path)
        return await git_utils.get_git_info()