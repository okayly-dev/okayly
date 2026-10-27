"""The layer rules, checked from the source with the standard ast module.

Layers (a layer may import itself and any layer with a lower number, never a higher one):
 1 core  2 providers  3 verification  4 agents  5 workflows  6 executors  7 api (top-level modules)
Extra rules: agents never import providers or executors; verification never imports agents;
workflows import executors only through the approval gate module; only providers and executors
may mention the provider write methods."""
import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[2] / "app"

LAYERS = {"core": 1, "providers": 2, "verification": 3, "agents": 4, "workflows": 5, "executors": 6}
TOP = 7                                         # api.py, main.py, wiring.py, service.py
GATE = "app.workflows.approval_gate"            # the one workflow module that may import executors
WRITE_NAMES = {"post_reply", "create_paused_draft"}
WRITE_OK = ("app.providers", "app.executors")


def layer_of(module: str) -> int | None:
    parts = module.split(".")
    if parts[0] != "app" or len(parts) < 2:
        return None
    return LAYERS.get(parts[1], TOP)


def package_of(module: str) -> str | None:
    parts = module.split(".")
    return parts[1] if len(parts) > 1 and parts[1] in LAYERS else None


def module_name(path: pathlib.Path) -> str:
    rel = path.relative_to(APP.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def imports_of(module: str, tree: ast.AST, is_package: bool) -> set[str]:
    """Every app module this file imports, with relative imports resolved."""
    pkg = module.split(".") if is_package else module.split(".")[:-1]
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = pkg[: len(pkg) - (node.level - 1)]
                target = ".".join(base + ([node.module] if node.module else []))
            else:
                target = node.module or ""
            found.add(target)
            found.update(f"{target}.{a.name}" for a in node.names)   # "from pkg import name": name may be a module
    return {m for m in found if m == "app" or m.startswith("app.")}


def import_map() -> dict[str, set[str]]:
    out = {}
    for path in sorted(APP.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        mod = module_name(path)
        out[mod] = imports_of(mod, tree, path.name == "__init__.py")
    return out


def find_import_violations(imports: dict[str, set[str]]) -> list[str]:
    bad = []
    for src, targets in imports.items():
        ls = layer_of(src)
        if ls is None:
            continue
        for dst in targets:
            ld = layer_of(dst)
            if ld is None or dst == "app":
                continue
            psrc, pdst = package_of(src), package_of(dst)
            if psrc == "workflows" and pdst == "executors":
                if src != GATE:
                    bad.append(f"{src} imports {dst}: workflows may reach executors only through {GATE}")
                continue
            if ld > ls:
                bad.append(f"{src} (layer {ls}) imports {dst} (layer {ld}): imports must go downward")
            if psrc == "agents" and pdst in ("providers", "executors"):
                bad.append(f"{src} imports {dst}: agents must not import {pdst}")
            if psrc == "verification" and pdst == "agents":
                bad.append(f"{src} imports {dst}: verification must not import agents")
    return sorted(set(bad))


def find_write_references(sources: dict[str, str]) -> list[str]:
    """Anything outside providers and executors that names a provider write method."""
    bad = []
    for mod, text in sources.items():
        if mod.startswith(WRITE_OK):
            continue
        for node in ast.walk(ast.parse(text)):
            name = None
            if isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                name = node.name
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                name = node.value
            elif isinstance(node, ast.alias):
                name = node.name
            if name in WRITE_NAMES:
                bad.append(f"{mod} mentions {name}: only providers and executors may")
    return sorted(set(bad))


def app_sources() -> dict[str, str]:
    return {module_name(p): p.read_text(encoding="utf-8") for p in sorted(APP.rglob("*.py"))}


# ---------- the real code ----------
def test_there_is_code_in_every_layer():
    mods = set(import_map())
    for pkg in LAYERS:
        assert any(m.startswith(f"app.{pkg}.") for m in mods), pkg
    assert {"app.api", "app.wiring", "app.main", "app.service"} <= mods


def test_imports_only_go_downward_and_respect_the_extra_rules():
    assert find_import_violations(import_map()) == []


def test_only_providers_and_executors_name_the_write_methods():
    assert find_write_references(app_sources()) == []


def test_agents_do_not_import_providers_or_executors():
    for mod, targets in import_map().items():
        if mod.startswith("app.agents"):
            assert not [t for t in targets if t.startswith(("app.providers", "app.executors"))], mod


def test_only_the_executor_module_imports_the_provider_write_side():
    allowed = {"app.executors.executor", "app.wiring", "app.providers.sandbox", "app.providers.read"}
    for mod, targets in import_map().items():
        if "app.providers.sandbox" in targets:
            assert mod in allowed, mod


# ---------- self-test: the checker really rejects bad code ----------
def test_a_bad_import_map_is_rejected():
    bad = {
        "app.core.store": {"app.workflows.propose"},                       # upward
        "app.providers.read": {"app.verification.policy"},                 # upward
        "app.verification.policy": {"app.agents.loop"},                    # verification -> agents
        "app.agents.reviews": {"app.providers.sandbox"},                   # agents -> providers
        "app.agents.ads": {"app.executors.executor"},                      # agents -> executors
        "app.workflows.propose": {"app.executors.executor"},               # workflows -> executors, not the gate
        "app.workflows.approval_gate": {"app.executors.executor"},         # allowed exception
        "app.service": {"app.executors.executor", "app.core.store"},       # api may use everything below
    }
    problems = find_import_violations(bad)
    for src in ("app.core.store", "app.providers.read", "app.verification.policy", "app.agents.reviews",
                "app.agents.ads", "app.workflows.propose"):
        assert any(p.startswith(src + " ") for p in problems), (src, problems)
    assert not any(p.startswith("app.workflows.approval_gate ") for p in problems)
    assert not any(p.startswith("app.service ") for p in problems)


def test_a_write_method_outside_the_executors_is_rejected():
    bad = {
        "app.workflows.propose": "def f(p):\n    p.post_reply('a', 'b', 'c')\n",
        "app.agents.ads": "x = getattr(p, 'create_paused_draft')\n",
        "app.executors.executor": "def g(p):\n    p.post_reply('a', 'b', 'c')\n",
        "app.providers.sandbox": "def post_reply(self): pass\n",
    }
    problems = find_write_references(bad)
    assert any("app.workflows.propose" in p for p in problems)
    assert any("app.agents.ads" in p for p in problems)
    assert not any("app.executors" in p or "app.providers" in p for p in problems)


def test_relative_imports_are_resolved():
    tree = ast.parse("from ..core import proposals\nfrom . import x\nfrom .y import z\nimport app.core.audit\n")
    got = imports_of("app.workflows.edit", tree, is_package=False)
    assert {"app.core", "app.core.proposals", "app.workflows.y", "app.core.audit"} <= got
