"""Force eager evaluation of every type annotation in the backend.

Python 3.14 defers annotations (PEP 649), so a missing import used only inside
an annotation stays hidden locally but raises NameError on import under Python
3.12 (Render). This sweep imports every module and evaluates all type hints,
reproducing the 3.12 behavior.

Run as a script (from backend/):  python -m scripts.check_annotations
Or via pytest:                    pytest tests/test_annotations.py
"""
import importlib
import inspect
import pkgutil
import sys
import typing

sys.path.insert(0, ".")

import app  # noqa: E402


def check_annotations() -> tuple[int, list[str]]:
    """Return (number of callables checked, list of error strings)."""
    errors: list[str] = []
    checked = 0

    for module_info in pkgutil.walk_packages(app.__path__, prefix="app."):
        name = module_info.name
        if "scripts" in name:
            continue
        try:
            module = importlib.import_module(name)
        except Exception as exc:
            errors.append(f"{name}: IMPORT FAILED -> {type(exc).__name__}: {exc}")
            continue

        targets = []
        for attr_name, obj in vars(module).items():
            if inspect.isfunction(obj) and getattr(obj, "__module__", "") == module.__name__:
                targets.append((attr_name, obj))
            elif inspect.isclass(obj) and getattr(obj, "__module__", "") == module.__name__:
                for method_name, method in vars(obj).items():
                    if inspect.isfunction(method):
                        targets.append((f"{attr_name}.{method_name}", method))

        for attr_name, func in targets:
            checked += 1
            try:
                typing.get_type_hints(func)
            except Exception as exc:
                errors.append(f"{name}.{attr_name}: {type(exc).__name__}: {exc}")

    return checked, errors


def main() -> int:
    checked, errors = check_annotations()
    print(f"modules imported, functions/methods checked: {checked}")
    if errors:
        print("ANNOTATION ERRORS:")
        for err in errors:
            print("  -", err)
        return 1
    print("all annotations evaluate cleanly (Python 3.12-equivalent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
