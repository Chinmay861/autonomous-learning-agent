"""The LLM-facing interface: action parsing, observations and the move budget."""
import pytest

from app.game import PRESETS, MinesweeperEnv, MoveOutcome, parse_action


@pytest.mark.parametrize("raw", [
    {"action": "reveal", "row": 2, "col": 3},
    {"action": "open", "row": "2", "col": "3"},
    {"tool": "reveal", "parameters": {"row": 2, "col": 3}},
    {"action": {"type": "reveal", "row": 2, "col": 3}},
    {"action": "reveal", "cell": [2, 3]},
    {"action": "click", "cell": "(2, 3)"},
    '{"action": "reveal", "row": 2, "col": 3}',
    "reveal 2 3",
    "reveal(2,3)",
])
def test_parse_action_accepts_common_shapes(raw):
    action, error = parse_action(raw)
    assert error == ""
    assert action == {"action": "reveal", "row": 2, "col": 3}


@pytest.mark.parametrize("raw", [{}, {"action": "dance", "row": 1, "col": 1}, {"action": "reveal"}, "hello", 42])
def test_parse_action_rejects_garbage(raw):
    action, error = parse_action(raw)
    assert action is None and error


def test_step_never_raises_and_counts_bad_actions():
    env = MinesweeperEnv(PRESETS["small"], 5)
    step = env.step("not an action")
    assert step.outcome == MoveOutcome.INVALID and step.error_code == "unparseable"
    assert env.game.moves == 1 and not step.done


def test_observation_lists_board_and_frontier():
    env = MinesweeperEnv(PRESETS["beginner"], 9)
    obs = env.observe()
    assert "Board 9x9, 10 mines" in obs.text
    assert "Numbers next to hidden cells" in obs.text
    assert obs.data["grid"] == env.game.grid()
    for fact in env.frontier():
        r, c = fact["cell"]
        assert env.game.count(r, c) == fact["number"]
        assert all(tuple(n) not in env.game.revealed for n in fact["hidden_neighbors"])


def test_move_budget_ends_game_as_timeout():
    env = MinesweeperEnv(PRESETS["small"], 6, max_moves=3)
    r, c = env.game.start
    for _ in range(3):
        step = env.step({"action": "reveal", "row": r, "col": c})  # already revealed: invalid
    assert step.done and step.status.value == "timeout"


def test_model_strings_resolve_to_providers(monkeypatch):
    from app.config import settings
    from app.models.llm_provider import split_model

    monkeypatch.setattr(settings, "LLM_PROVIDER", "groq")
    assert split_model("openai/gpt-oss-20b") == ("groq", "openai/gpt-oss-20b")  # Groq ids start with "openai/"
    assert split_model("groq:openai/gpt-oss-120b") == ("groq", "openai/gpt-oss-120b")
    assert split_model("ollama:qwen3:4b") == ("ollama", "qwen3:4b")
    assert split_model("qwen3:4b") == ("groq", "qwen3:4b")


def test_non_chat_models_are_hidden():
    from app.api.meta import is_chat_model

    playable = ["openai/gpt-oss-20b", "openai/gpt-oss-120b", "qwen/qwen3.8-27b", "allam-2-7b"]
    unplayable = ["whisper-large-v3", "canopylabs/orpheus-v1-english", "meta-llama/llama-prompt-guard-2-86m",
                  "openai/gpt-oss-safeguard-20b"]
    assert all(is_chat_model(m) for m in playable)
    assert not any(is_chat_model(m) for m in unplayable)
