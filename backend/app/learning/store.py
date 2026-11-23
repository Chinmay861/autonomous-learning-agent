"""Load and save pattern memory (table `ms_patterns`)."""
from __future__ import annotations

from sqlalchemy import delete, func, select

from app.database.models import PatternStat
from app.learning.patterns import PatternMemory

PERSISTENT_BANK = "user"


def bank_for(scope: str, experiment_id: str) -> str:
    """Persistent memory is shared by all of a user's experiments; fresh memory belongs to one."""
    return PERSISTENT_BANK if scope == "persistent" else f"exp:{experiment_id}"


async def load_memory(session_factory, user_id: int, bank: str) -> PatternMemory:
    async with session_factory() as session:
        result = await session.execute(
            select(PatternStat.pattern, PatternStat.mines, PatternStat.zeros, PatternStat.numbers)
            .where(PatternStat.user_id == user_id, PatternStat.bank == bank)
        )
        return PatternMemory({row[0]: [row[1], row[2], row[3]] for row in result})


def _upsert(dialect: str):
    if dialect == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    return insert


async def save_increments(session_factory, user_id: int, bank: str, increments: dict[str, list[int]]) -> None:
    """Add counts (not overwrite), so concurrent experiments sharing a bank never lose updates."""
    if not increments:
        return
    rows = [
        {"user_id": user_id, "bank": bank, "pattern": key, "mines": m, "zeros": z, "numbers": n}
        for key, (m, z, n) in increments.items()
    ]
    async with session_factory() as session:
        insert = _upsert(session.bind.dialect.name)
        table = PatternStat.__table__
        for start in range(0, len(rows), 500):
            stmt = insert(table).values(rows[start:start + 500])
            stmt = stmt.on_conflict_do_update(
                index_elements=["user_id", "bank", "pattern"],
                set_={
                    "mines": table.c.mines + stmt.excluded.mines,
                    "zeros": table.c.zeros + stmt.excluded.zeros,
                    "numbers": table.c.numbers + stmt.excluded.numbers,
                },
            )
            await session.execute(stmt)
        await session.commit()


async def memory_summary(session_factory, user_id: int, bank: str, limit: int = 12, min_seen: int = 10) -> dict:
    """What the memory knows, for display: size plus the safest and riskiest common 3x3 patterns."""
    from app.learning.overlaps import RULE_MIN_EVIDENCE, RULE_MIN_EVIDENCE_MINE, describe_overlap, is_trivial
    from app.learning.patterns import render_pattern

    async with session_factory() as session:
        total = (await session.execute(
            select(func.count(), func.coalesce(func.sum(PatternStat.mines + PatternStat.zeros + PatternStat.numbers), 0))
            .where(PatternStat.user_id == user_id, PatternStat.bank == bank, PatternStat.pattern.like("1:%"))
        )).one()
        wide = (await session.execute(
            select(func.count()).where(PatternStat.user_id == user_id, PatternStat.bank == bank,
                                       PatternStat.pattern.like("2:%"))
        )).scalar_one()
        seen = PatternStat.mines + PatternStat.zeros + PatternStat.numbers
        rows = (await session.execute(
            select(PatternStat.pattern, PatternStat.mines, PatternStat.zeros, PatternStat.numbers)
            .where(PatternStat.user_id == user_id, PatternStat.bank == bank,
                   PatternStat.pattern.like("1:%"), seen >= min_seen)
        )).all()
        # Overlapping-number situations that never went the other way: the rules it discovered.
        rule_rows = (await session.execute(
            select(PatternStat.pattern, PatternStat.mines, seen)
            .where(PatternStat.user_id == user_id, PatternStat.bank == bank, PatternStat.pattern.like("o:%"),
                   ((PatternStat.mines == 0) & (seen >= RULE_MIN_EVIDENCE))
                   | ((PatternStat.mines == seen) & (seen >= RULE_MIN_EVIDENCE_MINE)))
            .order_by(seen.desc())
        )).all()

    def item(row):
        key, m, z, n = row
        seen_count = m + z + n
        return {"pattern": render_pattern(key), "seen": seen_count,
                "mine_rate": round(m / seen_count, 4), "zero_rate": round(z / seen_count, 4)}

    items = [item(r) for r in rows]
    # Rank by how sure the memory is, not just the raw rate: common patterns first.
    safest = sorted(items, key=lambda i: (i["mine_rate"], -i["seen"]))[:limit]
    riskiest = sorted(items, key=lambda i: (-i["mine_rate"], -i["seen"]))[:limit]
    rules = [{"rule": describe_overlap(key), "outcome": "mine" if mines_count else "safe", "seen": int(count)}
             for key, mines_count, count in rule_rows if not is_trivial(key)]
    return {
        "bank": bank,
        "rules_discovered": len(rules),
        "rules": rules[:limit],
        "patterns_3x3": total[0],
        "patterns_5x5": wide,
        "observations": int(total[1]),
        "safest": safest,
        "riskiest": riskiest,
    }


async def reset_memory(session_factory, user_id: int, bank: str) -> int:
    async with session_factory() as session:
        result = await session.execute(
            delete(PatternStat).where(PatternStat.user_id == user_id, PatternStat.bank == bank)
        )
        await session.commit()
        return result.rowcount or 0
