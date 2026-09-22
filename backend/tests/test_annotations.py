"""Guard against annotations that only resolve on Python 3.14+.

Locally the venv runs Python 3.14, where annotations are lazy (PEP 649). A
missing typing import used only in an annotation therefore passes locally but
crashes on import under Python 3.12 (e.g. the Render Docker image). This test
evaluates every annotation eagerly, reproducing the stricter behavior.
"""
from scripts.check_annotations import check_annotations


def test_all_annotations_evaluate():
    checked, errors = check_annotations()
    assert checked > 0
    assert errors == [], "Annotations failed to evaluate:\n" + "\n".join(errors)
