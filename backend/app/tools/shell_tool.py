import subprocess
from .registry import BaseTool, ToolResult, PermissionLevel

class ShellTool(BaseTool):
    name = "execute_shell"
    description = "Executes shell commands (with allowlist restriction)"
    parameters = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Command to execute"}
        },
        "required": ["command"]
    }
    safety_level = "HIGH"
    permission_level = PermissionLevel.FULL

    def __init__(self):
        self.allowlist = ['echo', 'ls', 'dir', 'pwd', 'whoami', 'date', 'git']

    async def execute(self, parameters: dict) -> ToolResult:
        command = parameters.get("command")
        if not command:
            return ToolResult(success=False, output="", error="No command provided")

        base_cmd = command.split()[0]
        if base_cmd not in self.allowlist:
            return ToolResult(success=False, output="", error=f"Command {base_cmd} not in allowlist")

        try:
            result = subprocess.run(
                command,
                shell=True,
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
