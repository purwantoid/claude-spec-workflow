"""Steering document management for persistent project context.

This module handles steering document creation, parsing, and integration
with the workflow system to maintain project standards and conventions.
"""

import aiofiles
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class SteeringDocuments:
    """Container for steering document contents.
    
    Represents the three core steering documents that provide
    persistent project context for workflow operations.
    """
    product: Optional[str] = None
    tech: Optional[str] = None
    structure: Optional[str] = None


class SteeringManager:
    """Manages steering documents for project context.
    
    Handles creation, validation, and integration of steering documents
    (product.md, tech.md, structure.md) with the workflow system.
    """

    def __init__(self, project_path: Path) -> None:
        """Initialize with project path.
        
        Args:
            project_path: Path to the project root directory.
        """
        self.project_path = project_path
        self.steering_dir = project_path / ".claude" / "steering"

    async def load_steering_documents(self) -> SteeringDocuments:
        """Load all steering documents from the project.
        
        Returns:
            SteeringDocuments instance with loaded content.
        """
        docs = SteeringDocuments()
        
        try:
            # Check if steering directory exists
            if not self.steering_dir.exists():
                return docs
            
            # Try to load each steering document
            product_path = self.steering_dir / "product.md"
            tech_path = self.steering_dir / "tech.md"
            structure_path = self.steering_dir / "structure.md"
            
            if product_path.exists():
                try:
                    async with aiofiles.open(product_path, "r", encoding="utf-8") as f:
                        docs.product = await f.read()
                except OSError:
                    # Product doc couldn't be read, that's okay
                    pass
            
            if tech_path.exists():
                try:
                    async with aiofiles.open(tech_path, "r", encoding="utf-8") as f:
                        docs.tech = await f.read()
                except OSError:
                    # Tech doc couldn't be read, that's okay
                    pass
            
            if structure_path.exists():
                try:
                    async with aiofiles.open(structure_path, "r", encoding="utf-8") as f:
                        docs.structure = await f.read()
                except OSError:
                    # Structure doc couldn't be read, that's okay
                    pass
        
        except Exception:
            # Steering directory access failed, return empty docs
            pass
        
        return docs

    async def steering_documents_exist(self) -> bool:
        """Check if any steering documents exist.
        
        Returns:
            True if at least one steering document exists.
        """
        try:
            if not self.steering_dir.exists():
                return False
            
            steering_files = ["product.md", "tech.md", "structure.md"]
            for file_name in steering_files:
                if (self.steering_dir / file_name).exists():
                    return True
            
            return False
        
        except Exception:
            return False

    def format_steering_context(self, docs: SteeringDocuments) -> str:
        """Format steering documents into context string for workflow integration.
        
        Args:
            docs: SteeringDocuments instance with loaded content.
            
        Returns:
            Formatted context string for workflow use.
        """
        sections: list[str] = []
        
        if docs.product:
            sections.append("## Product Context\n" + docs.product)
        
        if docs.tech:
            sections.append("## Technology Context\n" + docs.tech)
        
        if docs.structure:
            sections.append("## Structure Context\n" + docs.structure)
        
        if not sections:
            return ""
        
        return "# Steering Documents Context\n\n" + "\n\n---\n\n".join(sections)

    async def analyze_project(self) -> dict:
        """Analyze project structure and generate steering context.
        
        Returns:
            Dictionary containing project analysis results with steering context.
        """
        docs = await self.load_steering_documents()
        steering_context = self.format_steering_context(docs)
        
        return {
            "steering_exists": await self.steering_documents_exist(),
            "steering_context": steering_context,
            "has_product": docs.product is not None,
            "has_tech": docs.tech is not None,
            "has_structure": docs.structure is not None,
        }