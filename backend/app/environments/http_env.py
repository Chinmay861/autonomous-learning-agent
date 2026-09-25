import httpx
from .base import Environment, EnvironmentState, ActionResult

REQUEST_TIMEOUT_SECONDS = 20.0

# The planner emits actions as {"tool": "make_request", "parameters": {...}},
# so this environment accepts both that wrapper shape and the flat shape.
USAGE_HINT = (
    'Send {"tool": "make_request", "parameters": '
    '{"method": "GET|POST|PUT|DELETE", "url": "https://...", '
    '"headers": {}, "body": {}}}. '
    'The "url" field is required and must be a fully qualified http(s) URL.'
)


def _coalesce(*values):
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict) and value:
            return value
    return None


def _normalize_action(action: dict | str) -> dict:
    """Flatten planner-style {"tool", "parameters"} wrappers into one dict.

    Top-level fields win; nested "parameters"/"arguments"/"args" fill the gaps.
    """
    if isinstance(action, str):
        return {"url": action.strip()}
    if not isinstance(action, dict):
        return {}

    merged: dict = {k: v for k, v in action.items() if k != "parameters"}
    params = action.get("parameters")
    if not isinstance(params, dict):
        params = action.get("arguments")
    if not isinstance(params, dict):
        params = action.get("args")
    if isinstance(params, dict):
        for k, v in params.items():
            merged.setdefault(k, v)
    return merged


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

    async def act(self, action: dict | str) -> ActionResult:
        normalized = _normalize_action(action)
        method = str(normalized.get("method", "GET") or "GET").upper()
        url = normalized.get("url")
        headers = normalized.get("headers") or {}
        body = normalized.get("body")
        if body is None:
            body = normalized.get("json_body")

        if not isinstance(url, str) or not url:
            return ActionResult(
                success=False,
                error=f"URL is required. {USAGE_HINT}"
            )

        if not isinstance(headers, dict):
            return ActionResult(
                success=False,
                error=f"Headers must be an object. {USAGE_HINT}"
            )

        if method not in ("GET", "POST", "PUT", "DELETE"):
            return ActionResult(
                success=False,
                error=f"Unsupported method {method}. Use one of GET, POST, PUT, DELETE. {USAGE_HINT}"
            )

        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT_SECONDS) as client:
            try:
                if method == "GET":
                    response = await client.get(url, headers=headers)
                elif method == "POST":
                    response = await client.post(url, headers=headers, json=body)
                elif method == "PUT":
                    response = await client.put(url, headers=headers, json=body)
                else:
                    response = await client.delete(url, headers=headers)

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
        # HTTP tasks have no natural goal; the orchestrator's iteration
        # budget terminates the run.
        return False

    def get_available_actions(self) -> list[dict]:
        return [{
            "name": "make_request",
            "description": (
                "Perform one HTTP request. Always place the full request inside "
                '"parameters" as {"method", "url", "headers", "body"}. '
                'The "url" field is required and must be a fully qualified http(s) URL.'
            ),
            "parameters": {
                "method": "string (One of: 'GET', 'POST', 'PUT', 'DELETE')",
                "url": "string (required, fully qualified http(s) URL)",
                "headers": "object (optional)",
                "body": "object (optional, sent as JSON for POST/PUT)",
            },
        }]
