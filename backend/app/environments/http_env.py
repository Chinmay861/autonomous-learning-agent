import httpx
from .base import Environment, EnvironmentState, ActionResult

class HTTPEnvironment(Environment):
    name = "http_env"
    description = "HTTP request execution environment"

    def __init__(self):
        self.last_response = None
        self.request_history = []

    async def observe(self) -> EnvironmentState:
        if self.last_response:
            return EnvironmentState(
                description=f"Last status: {self.last_response.status_code}",
                raw={
                    "status_code": self.last_response.status_code,
                    "headers": dict(self.last_response.headers),
                    "text": self.last_response.text
                }
            )
        return EnvironmentState(description="No requests made yet.")

    async def act(self, action: dict) -> ActionResult:
        method = action.get("method", "GET").upper()
        url = action.get("url")
        headers = action.get("headers", {})
        body = action.get("body")
        
        if not url:
            return ActionResult(success=False, error="URL is required")
            
        async with httpx.AsyncClient() as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=body)
                else:
                    response = await client.request(method, url, headers=headers, json=body)
                
                self.last_response = response
                self.request_history.append({"method": method, "url": url, "status": response.status_code})
                
                return ActionResult(
                    success=True,
                    output=response.text,
                    metadata={"status_code": response.status_code}
                )
            except Exception as e:
                return ActionResult(success=False, error=str(e))

    async def reset(self) -> EnvironmentState:
        self.last_response = None
        self.request_history = []
        return await self.observe()

    async def is_finished(self) -> bool:
        return False

    def get_available_actions(self) -> list[dict]:
        return [{
            "name": "make_request",
            "schema": {
                "method": "string",
                "url": "string",
                "headers": "dict",
                "body": "dict"
            }
        }]
