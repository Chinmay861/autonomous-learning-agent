from typing import AsyncGenerator
from fastapi import Request

async def get_redis(request: Request):
    return request.app.state.redis

async def get_job_manager(request: Request):
    return request.app.state.job_manager

async def get_memory_manager(request: Request):
    return request.app.state.memory_manager

async def get_file_storage(request: Request):
    return request.app.state.file_storage

