"""Regression tests for task-to-environment routing."""

from app.environments import get_environment_for_task
from app.environments.http_env import HTTPEnvironment
from app.environments.universal_env import UniversalSimulationEnvironment


def test_simulation_mentioning_api_is_not_routed_to_http():
    environment = get_environment_for_task({
        "title": "Text survival simulation",
        "description": (
            "State: energy 10, food 2. Available actions: EXPLORE, HUNT, REST. "
            "Return each action in an API-style response."
        ),
    })

    assert isinstance(environment, UniversalSimulationEnvironment)


def test_concrete_url_is_routed_to_http():
    environment = get_environment_for_task({
        "title": "Fetch service status",
        "description": "Make a GET request to https://example.com/api/status.",
    })

    assert isinstance(environment, HTTPEnvironment)
