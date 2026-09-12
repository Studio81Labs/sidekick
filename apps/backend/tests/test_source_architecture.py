"""Guardrails for backend packages reserved for the layered migration."""

import ast
import re
from pathlib import Path

BACKEND_ROOT = Path(__file__).parents[1]
APP_ROOT = BACKEND_ROOT / "app"
STARTUP_MODULE_INVOCATION = re.compile(r"python\s+-m\s+(app(?:\.[A-Za-z_]\w*)+)")
LAYERS = {"api", "application", "domain", "infrastructure"}
ALLOWED_IMPORTS = {
    "api": {"api", "application", "domain"},
    "application": {"application", "domain"},
    "domain": {"domain"},
    "infrastructure": {"infrastructure", "application", "domain"},
}
FORBIDDEN_APP_IMPORTS = {
    "fastapi",
    "starlette",
    "pydantic_settings",
    "pathlib",
    "os",
    "shutil",
    "tempfile",
    "glob",
    "fnmatch",
    "fcntl",
    "subprocess",
    "app.config",
    "app.infrastructure",
    # Repository ports live in the application layer and adapters import
    # them, never the reverse: app/application/imported_hand_ports.py
    # declares ImportedHandRepository and app/storage/imported_hand_store.py
    # implements it. package_target() cannot catch this on its own, because
    # "app.storage" resolves to no layer at all, so the direction has to be
    # named here.
    "app.storage",
}
ROUTER_FORBIDDEN_IMPORT_PREFIXES = {
    "app.config",
    "app.storage",
    "app.data_lock",
    "app.pipeline",
    "app.parsers.registry",
    "app.providers.registry",
    "app.solvers.registry",
}


def future_sources() -> list[Path]:
    return sorted(
        path
        for layer in LAYERS
        for path in (APP_ROOT / layer).rglob("*.py")
        if path.name != "__init__.py"
    ) if any((APP_ROOT / layer).is_dir() for layer in LAYERS) else []


def layer_for(path: Path) -> str:
    return path.relative_to(APP_ROOT).parts[0]


def imported_modules(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(), filename=str(path))
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            prefix = "." * node.level
            modules.append(prefix + (node.module or ""))
    return modules


def imports_app_models(path: Path) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == "app.models" for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom):
            if node.module == "app.models":
                return True
            if node.module == "app" and any(
                alias.name == "models" for alias in node.names
            ):
                return True
    return False


def imports_app_package_root(path: Path, package: str) -> bool:
    tree = ast.parse(path.read_text(), filename=str(path))
    package_name = f"app.{package}"
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(
            alias.name == package_name for alias in node.names
        ):
            return True
        if isinstance(node, ast.ImportFrom):
            if node.module == package_name:
                return True
            if node.module == "app" and any(
                alias.name == package for alias in node.names
            ):
                return True
    return False


def first_party_python_sources() -> list[Path]:
    return sorted(
        path
        for root in (
            APP_ROOT,
            APP_ROOT.parent / "tests",
            APP_ROOT.parents[2] / "scripts",
        )
        for path in root.rglob("*.py")
    )


def package_target(module: str, path: Path) -> str | None:
    if module.startswith("."):
        relative_parts = list(path.relative_to(APP_ROOT).parts[:-1])
        for _ in range(module.count(".") - 1):
            if relative_parts:
                relative_parts.pop()
        relative_parts.extend(part for part in module.lstrip(".").split(".") if part)
        return relative_parts[0] if relative_parts and relative_parts[0] in LAYERS else None
    parts = module.split(".")
    if parts[0] == "app" and len(parts) > 1 and parts[1] in LAYERS:
        return parts[1]
    return parts[0] if parts[0] in LAYERS else None


def module_source_exists(module: str) -> bool:
    relative = Path(*module.split(".")[1:])
    return (APP_ROOT / relative.with_suffix(".py")).exists() or (
        APP_ROOT / relative / "__init__.py"
    ).exists()


def test_future_backend_layers_follow_direction_and_boundaries() -> None:
    violations: list[str] = []
    for path in future_sources():
        layer = layer_for(path)
        modules = imported_modules(path)
        if layer in {"application", "domain"}:
            for module in modules:
                if module in FORBIDDEN_APP_IMPORTS or any(
                    module.startswith(root + ".") for root in FORBIDDEN_APP_IMPORTS
                ):
                    violations.append(f"{path}: {module}")
        for module in modules:
            target = package_target(module, path)
            if target is not None and target not in ALLOWED_IMPORTS[layer]:
                violations.append(f"{path}: {layer} may not import {target}")
    assert violations == []


def test_api_routers_do_not_import_runtime_wiring_dependencies() -> None:
    violations: list[str] = []
    for path in sorted((APP_ROOT / "api" / "routers").glob("*.py")):
        if path.name == "__init__.py":
            continue
        for module in imported_modules(path):
            if module in ROUTER_FORBIDDEN_IMPORT_PREFIXES or any(
                module.startswith(prefix + ".")
                for prefix in ROUTER_FORBIDDEN_IMPORT_PREFIXES
            ):
                violations.append(f"{path}: {module}")
    assert violations == []


def test_models_compatibility_facade_is_retired() -> None:
    assert not (APP_ROOT / "models.py").exists()

    violations = [
        str(path)
        for path in first_party_python_sources()
        if imports_app_models(path)
    ]
    assert violations == []


def test_package_root_compatibility_exports_are_retired() -> None:
    packages = ("api", "storage")
    assert all(
        imported_modules(APP_ROOT / package / "__init__.py") == []
        for package in packages
    )

    violations = [
        f"{path}: app.{package}"
        for path in first_party_python_sources()
        for package in packages
        if imports_app_package_root(path, package)
    ]
    assert violations == []


def test_training_aggregation_monolith_is_retired() -> None:
    assert not (APP_ROOT / "training.py").exists()


def test_grading_domain_does_not_import_application_execution() -> None:
    forbidden = {"app.application"}
    violations = [
        f"{path}: {module}"
        for path in sorted((APP_ROOT / "domain" / "grading").glob("*.py"))
        for module in imported_modules(path)
        if module in forbidden
        or any(module.startswith(prefix + ".") for prefix in forbidden)
    ]
    assert violations == []


def test_legacy_recommendation_execution_is_retired() -> None:
    retired_source_paths = (
        APP_ROOT / "recommendation_benchmark.py",
        APP_ROOT / "deployment_cleanup.py",
    )

    assert all(not path.exists() for path in retired_source_paths)
    assert not list((APP_ROOT / "domain" / "recommendations").glob("*.py"))
    assert not list((APP_ROOT / "providers").glob("*.py"))
    assert not list((APP_ROOT / "solvers").glob("*.py"))


def test_container_startup_only_runs_modules_that_exist() -> None:
    # The entrypoint runs under `set -eu` before the server binds, so a stale
    # `python -m` target aborts the container instead of failing a test: the
    # healthcheck then never passes and the deployment rolls back.
    entrypoint = BACKEND_ROOT / "docker-entrypoint.sh"

    missing = [
        module
        for module in STARTUP_MODULE_INVOCATION.findall(entrypoint.read_text())
        if not module_source_exists(module)
    ]

    assert missing == []


def test_remote_reference_domain_has_only_pure_dependencies() -> None:
    allowed = {
        "__future__",
        "app.domain.imported_hands.decisions",
        "app.domain.imported_hands.models",
        "app.domain.learning_content.models",
        "app.domain.remote_references.models",
        "app.domain.remote_references.services",
        "datetime",
        "decimal",
        "hashlib",
        "ipaddress",
        "json",
        "pydantic",
        "typing",
        "unicodedata",
        "urllib.parse",
    }
    violations = [
        f"{path}: {module}"
        for path in sorted(
            (APP_ROOT / "domain" / "remote_references").glob("*.py")
        )
        for module in imported_modules(path)
        if module not in allowed
    ]
    assert violations == []
