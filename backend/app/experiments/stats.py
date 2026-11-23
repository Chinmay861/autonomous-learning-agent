"""Aggregate metrics for an agent's games."""
from __future__ import annotations

from app.database.models import Game

FINISHED = ("won", "lost", "timeout")


def efficiency(game: Game) -> float | None:
    """Minimum reveals / moves used, for won games (1.0 = perfect)."""
    if game.status != "won" or not game.moves:
        return None
    return round(min(1.0, game.min_clicks / game.moves), 4)


def game_to_dict(game: Game) -> dict:
    return {
        "id": game.id,
        "agent": game.agent,
        "game_index": game.game_index,
        "seed": game.seed,
        "status": game.status,
        "moves": game.moves,
        "reveals": game.reveals,
        "flag_moves": game.flag_moves,
        "invalid_moves": game.invalid_moves,
        "min_clicks": game.min_clicks,
        "efficiency": efficiency(game),
        "safe_revealed": game.safe_revealed,
        "safe_total": game.safe_total,
        "progress": round(game.safe_revealed / game.safe_total, 4) if game.safe_total else 0.0,
        "llm_calls": game.llm_calls,
        "llm_errors": game.llm_errors,
        "prompt_tokens": game.prompt_tokens,
        "completion_tokens": game.completion_tokens,
        "lessons_available": game.lessons_available,
        "lessons_cited": game.lessons_cited or [],
        "mistakes": game.mistakes or [],
        "final_grid": game.final_grid or [],
        "duration_ms": game.duration_ms,
        "started_at": game.started_at.isoformat() if game.started_at else None,
        "finished_at": game.finished_at.isoformat() if game.finished_at else None,
    }


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(games: list[Game], recent: int = 20) -> dict:
    finished = sorted((g for g in games if g.status in FINISHED), key=lambda g: g.game_index)
    won = [g for g in finished if g.status == "won"]
    last = finished[-recent:]
    return {
        "games_played": len(finished),
        "wins": len(won),
        "losses": sum(1 for g in finished if g.status == "lost"),
        "timeouts": sum(1 for g in finished if g.status == "timeout"),
        "win_rate": round(len(won) / len(finished), 4) if finished else None,
        "recent_win_rate": round(sum(1 for g in last if g.status == "won") / len(last), 4) if last else None,
        "avg_moves_won": _mean([g.moves for g in won]),
        "avg_min_clicks_won": _mean([g.min_clicks for g in won]),
        "avg_efficiency_won": _mean([e for g in won if (e := efficiency(g)) is not None]),
        "avg_progress": _mean([g.safe_revealed / g.safe_total for g in finished if g.safe_total]),
        "total_moves": sum(g.moves for g in finished),
        "invalid_moves": sum(g.invalid_moves for g in finished),
        "mines_hit": sum(1 for g in finished if g.status == "lost"),
        "llm_calls": sum(g.llm_calls for g in games),
        "tokens": sum(g.prompt_tokens + g.completion_tokens for g in games),
    }
