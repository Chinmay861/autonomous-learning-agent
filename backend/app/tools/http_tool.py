import httpx
from .registry import BaseTool, ToolResult, PermissionLevel

class HttpTool(BaseTool):
    name = "http_request"
    description = "Makes HTTP requests"
    parameters = {
        "type": "object",
        "properties": {
            "method": {"type": "string", "enum": ["GET", "POST", "PUT", "DELETE"]},
            "url": {"type": "string"},
            "headers": {"type": "object"},
            "json_body": {"type": "object"}
        },
        "required": ["method", "url"]
    }
    safety_level = "MEDIUM"
    permission_level = PermissionLevel.LIMITED

    async def execute(self, parameters: dict) -> ToolResult:
        method = parameters.get("method", "GET").upper()
        url = parameters.get("url")
        headers = parameters.get("headers", {})
        json_body = parameters.get("json_body")

        if not url:
            return ToolResult(success=False, output="", error="URL is required")

        async with httpx.AsyncClient(timeout=10.0) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=json_body)
                elif method == "PUT":
                    response = await client.put(url, headers=headers, json=json_body)
                elif method == "DELETE":
                    response = await client.delete(url, headers=headers)
                else:
                    return ToolResult(success=False, output="", error=f"Unsupported method {method}")
                    
                return ToolResult(
                    success=True,
                    output=f"Status: {response.status_code}\nBody: {response.text}"
                )
            except Exception as e:
                return ToolResult(success=False, output="", error=str(e))
