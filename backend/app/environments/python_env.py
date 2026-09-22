import subprocess
import tempfile
import os
import sys
from .base import Environment, EnvironmentState, ActionResult

class PythonEnvironment(Environment):
    name = "python_env"
    description = "Python code execution sandbox"

    def __init__(self, timeout: int = 5):
        self.timeout = timeout
        self.last_state = EnvironmentState(description="Initialized")
        self.execution_count = 0

    async def observe(self) -> EnvironmentState:
        return self.last_state

    async def act(self, action: dict) -> ActionResult:
        code = action.get("code")
        if not code:
            return ActionResult(success=False, error="No code provided")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            # Basic sandbox could limit modules, but here we just run in a fresh process
            result = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            output = result.stdout
            error = result.stderr if result.returncode != 0 else None
            
            self.execution_count += 1
            self.last_state = EnvironmentState(
                description=f"Execution {self.execution_count} finished.",
                raw={"stdout": output, "stderr": error, "returncode": result.returncode}
            )
            
            return ActionResult(
                success=result.returncode == 0,
                output=output,
                error=error,
                metadata={"returncode": result.returncode}
            )
        except subprocess.TimeoutExpired:
            return ActionResult(success=False, error=f"Execution timed out after {self.timeout}s")
        except Exception as e:
            return ActionResult(success=False, error=str(e))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    async def reset(self) -> EnvironmentState:
        self.execution_count = 0
        self.last_state = EnvironmentState(description="Reset")
        return self.last_state

    async def is_finished(self) -> bool:
        return False

    def get_available_actions(self) -> list[dict]:
        return [{"name": "execute_code", "schema": {"code": "string"}}]
