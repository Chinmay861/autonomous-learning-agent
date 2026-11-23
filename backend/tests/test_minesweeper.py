"""Game engine invariants."""
import pytest

from app.game.minesweeper import PRESETS, BoardConfig, GameStatus, Minesweeper, MoveOutcome


def safe_cells(game: Minesweeper):
    return [(r, c) for r in range(game.rows) for c in range(game.cols) if (r, c) not in game.mines]


def test_same_seed_same_board():
    a, b = Minesweeper(PRESETS["beginner"], 7), Minesweeper(PRESETS["beginner"], 7)
    assert a.mines == b.mines and a.start == b.start and a.grid() == b.grid()
    assert Minesweeper(PRESETS["beginner"], 8).mines != a.mines


@pytest.mark.parametrize("seed", range(30))
def test_opening_is_safe_and_revealed(seed):
    game = Minesweeper(PRESETS["beginner"], seed)
    assert len(game.mines) == 10
    assert game.start not in game.mines
    assert all(n not in game.mines for n in game.neighbors(*game.start))
    assert game.count(*game.start) == 0 and game.start in game.revealed
    assert game.moves == 0 and game.status == GameStatus.PLAYING


def test_revealing_a_mine_loses():
    game = Minesweeper(PRESETS["small"], 3)
    mine = next(iter(game.mines))
    result = game.reveal(*mine)
    assert result.outcome == MoveOutcome.MINE and game.status == GameStatus.LOST
    assert game.exploded == mine and game.moves == 1
    assert game.grid(show_mines=True)[mine[0]][mine[1]] == "X"


def test_revealing_every_safe_cell_wins_and_min_clicks_is_achievable():
    for seed in range(20):
        game = Minesweeper(PRESETS["beginner"], seed)
        target = game.initial_min_clicks
        # Greedy 3BV play: click zero cells first, then remaining numbers.
        cells = sorted(safe_cells(game), key=lambda cell: game.count(*cell) != 0)
        for cell in cells:
            if cell not in game.revealed:
                assert game.reveal(*cell).valid
        assert game.status == GameStatus.WON
        assert game.reveals == target, f"seed {seed}: used {game.reveals}, 3BV {target}"


def test_invalid_moves_cost_a_move_and_have_codes():
    game = Minesweeper(PRESETS["small"], 1)
    r, c = game.start
    cases = [
        (game.reveal(r, c), "already_revealed"),
        (game.reveal(99, 0), "out_of_bounds"),
        (game.flag(r, c), "already_revealed"),
        (game.unflag(0, 0), "not_flagged"),
        (game.register_invalid("garbage"), "unparseable"),
    ]
    for result, code in cases:
        assert not result.valid and result.error_code == code
    assert game.moves == len(cases) == game.invalid_moves


def test_flags_block_reveal_and_count_as_moves():
    game = Minesweeper(PRESETS["small"], 2)
    hidden = next(cell for cell in safe_cells(game) if cell not in game.revealed)
    assert game.flag(*hidden).valid
    assert game.reveal(*hidden).error_code == "flagged"
    assert game.unflag(*hidden).valid
    assert game.reveal(*hidden).valid
    assert game.flag_moves == 2 and game.moves == 4


def test_public_state_hides_mines_until_game_over():
    game = Minesweeper(PRESETS["small"], 4)
    assert "*" not in "".join(game.to_public_dict()["grid"])
    game.reveal(*next(iter(game.mines)))
    assert "X" in "".join(game.to_public_dict()["grid"])


def test_board_config_validation():
    with pytest.raises(ValueError):
        BoardConfig(3, 3, 1)  # no room outside the 3x3 opening
    with pytest.raises(ValueError):
        BoardConfig(50, 9, 10)
