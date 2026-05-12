#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from harness_env import load_harness_env  # noqa: E402


load_harness_env(Path(__file__).resolve().parents[1])


def _load_package() -> object:
    package_root = Path(__file__).with_name("harness_autonomy")
    spec = importlib.util.spec_from_file_location(
        "_harness_autonomy_pkg",
        package_root / "__init__.py",
        submodule_search_locations=[str(package_root)],
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"unable to load harness_autonomy package from {package_root}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_PACKAGE = _load_package()


def _propagate_export(name: str, value: object) -> None:
    if name.startswith("__"):
        return
    package_name = _PACKAGE.__name__
    for module_name, module in tuple(sys.modules.items()):
        if module_name != package_name and not module_name.startswith(f"{package_name}."):
            continue
        if hasattr(module, name):
            setattr(module, name, value)


class _HarnessAutonomyModule(types.ModuleType):
    def __setattr__(self, name: str, value: object) -> None:
        super().__setattr__(name, value)
        _propagate_export(name, value)


_MODULE_METADATA_NAMES = {
    "__builtins__",
    "__cached__",
    "__doc__",
    "__file__",
    "__loader__",
    "__name__",
    "__package__",
    "__path__",
    "__spec__",
}


def _export_module_attrs(module: object) -> None:
    for _name, _value in vars(module).items():
        if _name in _MODULE_METADATA_NAMES:
            continue
        globals()[_name] = _value


_export_module_attrs(_PACKAGE)

for _module_name, _module in tuple(sys.modules.items()):
    if not _module_name.startswith(f"{_PACKAGE.__name__}."):
        continue
    _export_module_attrs(_module)

sys.modules[__name__].__class__ = _HarnessAutonomyModule


if __name__ == "__main__":
    raise SystemExit(_PACKAGE.main())
