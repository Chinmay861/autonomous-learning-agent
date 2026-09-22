from enum import Enum
from pydantic import BaseModel
from abc import ABC, abstractmethod
from typing import Any

class PermissionLevel(Enum):
    NONE = 0
    READ_ONLY = 1
    LIMITED = 2
    FULL = 3

class ToolResult(BaseModel):
    success: bool
    output: str
    error: str | None = None

class BaseTool(ABC):
    name: str
    description: str
    parameters: dict
    safety_level: str = "MEDIUM"
    permission_level: PermissionLevel = PermissionLevel.LIMITED

    @abstractmethod
    async def execute(self, parameters: dict) -> ToolResult:
        ...

class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register_tool(self, tool: BaseTool):
        self._tools[tool.name] = tool

    def get_tool(self, name: str) -> BaseTool:
        if name not in self._tools:
            raise ValueError(f"Tool {name} not found")
        return self._tools[name]

    def list_tools(self) -> list[dict]:
        return [
            {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters
            } for t in self._tools.values()
        ]

    def filter_by_permission(self, max_level: PermissionLevel) -> list[BaseTool]:
        return [t for t in self._tools.values() if t.permission_level.value <= max_level.value]
