from abc import ABC, abstractmethod
from typing import Any
from pydantic import BaseModel

class EnvironmentState(BaseModel):
    raw: Any = None
    description: str = ''
    score: float | None = None
    is_terminal: bool = False
    metadata: dict = {}

class ActionResult(BaseModel):
    success: bool
    output: str = ''
    error: str | None = None
    state_change: str = ''
    reward: float = 0.0
    metadata: dict = {}

class Environment(ABC):
    name: str
    description: str
    
    @abstractmethod
    async def observe(self) -> EnvironmentState: ...
    
    @abstractmethod
    async def act(self, action: dict) -> ActionResult: ...
    
    @abstractmethod
    async def reset(self) -> EnvironmentState: ...
    
    @abstractmethod
    async def is_finished(self) -> bool: ...
    
    @abstractmethod
    def get_available_actions(self) -> list[dict]: ...

class EnvironmentRegistry:
    def __init__(self):
        self._environments: dict[str, type[Environment]] = {}
        
    def register(self, env_class: type[Environment]):
        self._environments[env_class.name] = env_class
        
    def get(self, name: str, **kwargs) -> Environment:
        env_class = self._environments.get(name)
        if not env_class:
            raise ValueError(f"Environment {name} not found")
        return env_class(**kwargs)
        
    def list_environments(self) -> list[str]:
        return list(self._environments.keys())
