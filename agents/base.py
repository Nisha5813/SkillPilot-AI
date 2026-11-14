"""
Base Agent Module for SkillPilot AI Multi-Agent System
All agents inherit from BaseAgent with a clearly defined interface.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict


class BaseAgent(ABC):
    """Abstract base class for all SkillPilot AI specialized agents."""

    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def run(self, input_dict: Dict[str, Any]) -> Dict[str, Any]:
        """
        Execute the agent's core responsibility.
        Args:
            input_dict: Structured dictionary containing context and inputs.
        Returns:
            Dict[str, Any]: Fixed-schema output dictionary.
        """
        pass
