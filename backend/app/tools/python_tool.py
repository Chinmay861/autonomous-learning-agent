import subprocess
import sys
import tempfile
import os
from .registry import BaseTool, ToolResult, PermissionLevel

class PythonTool(BaseTool):
    name = "execute_python"
    description = "Executes arbitrary Python code in a subprocess"
    parameters = {
        "type": "object",
        "properties": {
            "code": {"type": "string", "description": "Python code to execute"}
        },
        "required": ["code"]
    }
    safety_level = "HIGH"
    permission_level = PermissionLevel.FULL

    async def execute(self, parameters: dict) -> ToolResult:
        code = parameters.get("code")
        if not code:
            return ToolResult(success=False, output="", error="No code provided")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write(code)
            temp_path = f.name

        try:
            result = subprocess.run(
                [sys.executable, temp_path],
                capture_output=True,
                text=True,
                timeout=10
            )
            if result.returncode == 0:
                return ToolResult(success=True, output=result.stdout)
            else:
                return ToolResult(success=False, output=result.stdout, error=result.stderr)
        except subprocess.TimeoutExpired:
            return ToolResult(success=False, output="", error="Execution timed out")
        except Exception as e:
            return ToolResult(success=False, output="", error=str(e))
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)
