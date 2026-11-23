from fastapi import Request

from app.experiments.manager import ExperimentManager


async def get_manager(request: Request) -> ExperimentManager:
    return request.app.state.manager
