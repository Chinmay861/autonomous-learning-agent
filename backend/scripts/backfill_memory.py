"""
Backfill the persistent vector memory store from raw learnings.txt files.

Reads storage/tasks/<task_id>/learnings.txt, extracts the per-iteration
Learning / New Discovery / Mistake sections, embeds them and stores them in the
vector memory with the same dedup path the agent uses at synthesis time.

Usage (from backend/):
    python -m scripts.backfill_memory
"""
import asyncio
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.memory.embeddings import EmbeddingService  # noqa: E402
from app.memory.memory_manager import MemoryManager  # noqa: E402
from app.memory.qdrant_store import QdrantStore  # noqa: E402
from app.memory.retriever import MemoryRetriever  # noqa: E402

HEADERS = [
    "Observation", "Hypothesis", "Action", "Expected Result", "Actual Result",
    "Evaluation", "Mistake", "New Discovery", "Learning", "Rule Changes",
    "Strategy Change", "Score",
]
HEADER_RE = re.compile(r"^(%s):$" % "|".join(re.escape(h) for h in HEADERS), re.M)
ENTRY_RE = re.compile(r"^\[Iteration (\d+)\]\s*$(.*?)(?=^\[Iteration \d+\]\s*$|\Z)", re.M | re.S)

CATEGORY_FOR_HEADER = {
    "Learning": "OBSERVATION",
    "New Discovery": "DISCOVERY",
    "Mistake": "MISTAKE",
}
MIN_LENGTH = 30
MAX_LENGTH = 700


def parse_entries(text: str):
    for match in ENTRY_RE.finditer(text):
        yield int(match.group(1)), match.group(2)


def extract_learnings(block: str):
    """Return (category, content) pairs from one iteration block."""
    positions = [(m.start(), m.group(1)) for m in HEADER_RE.finditer(block)]
    for index, (start, header) in enumerate(positions):
        if header not in CATEGORY_FOR_HEADER:
            continue
        end = positions[index + 1][0] if index + 1 < len(positions) else len(block)
        content = block[start + len(header) + 1:end].strip()
        content = re.sub(r"\s+", " ", content)
        if MIN_LENGTH <= len(content):
            yield CATEGORY_FOR_HEADER[header], content[:MAX_LENGTH]


def task_titles() -> dict:
    try:
        db_path = settings.DATABASE_URL.split("///")[-1]
        conn = sqlite3.connect(db_path)
        try:
            rows = conn.execute("SELECT id, title FROM tasks").fetchall()
            return {row[0]: row[1] for row in rows}
        finally:
            conn.close()
    except Exception:
        return {}


async def main() -> None:
    print(f"Vector store: {settings.QDRANT_URL} (collection: {settings.QDRANT_COLLECTION})")

    embedding_service = EmbeddingService(settings.EMBEDDING_MODEL)
    qdrant_store = QdrantStore(
        url=settings.QDRANT_URL,
        collection_name=settings.QDRANT_COLLECTION,
        dimension=settings.EMBEDDING_DIMENSION,
    )
    await qdrant_store.initialize()
    retriever = MemoryRetriever(embedding_service=embedding_service, qdrant_store=qdrant_store)
    memory_manager = MemoryManager(
        embedding_service=embedding_service, qdrant_store=qdrant_store, retriever=retriever
    )

    print("Loading embedding model (first run downloads it)…")
    await embedding_service.embed("warmup")

    titles = task_titles()
    tasks_root = Path(settings.STORAGE_DIR) / "tasks"
    stored = 0
    scanned_tasks = 0

    for task_dir in sorted(tasks_root.iterdir()) if tasks_root.exists() else []:
        learnings_file = task_dir / "learnings.txt"
        if not learnings_file.exists():
            continue
        scanned_tasks += 1
        text = learnings_file.read_text(encoding="utf-8", errors="replace")
        task_title = titles.get(task_dir.name, task_dir.name[:8])

        for iteration, block in parse_entries(text):
            for category, content in extract_learnings(block):
                learning = {
                    "title": f"{task_title} · iteration {iteration}",
                    "knowledge": content,
                    "category": category,
                    "conditions": [],
                    "exceptions": [],
                    "evidence_summary": f"Extracted from raw learnings of {task_title}",
                    "source_iterations": 1,
                    "confidence": 0.55,
                    "generalizable": False,
                    "task_type": "backfill",
                    "iteration_number": iteration,
                }
                await memory_manager.store_synthesized_learning(learning, task_dir.name)
                stored += 1

    stats = await memory_manager.get_memory_stats()
    print(f"Scanned {scanned_tasks} task logs, stored {stored} learnings.")
    print(f"Store now holds {stats['total_memories']} memories "
          f"(avg confidence {stats['avg_confidence']}, task-specific {stats['task_count']}).")


if __name__ == "__main__":
    asyncio.run(main())
