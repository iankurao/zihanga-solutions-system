"""Module boundaries of the modular monolith (no database needed).

backend/core holds shared layers and must not depend on any business domain;
backend/domains modules may use core and each other, but without import
cycles, so every module can be read and changed from its dependencies up.
"""
import ast
import pathlib
import unittest

BACKEND = pathlib.Path(__file__).resolve().parents[1] / "backend"


def _module_name(path):
    return ".".join(path.relative_to(BACKEND.parent).with_suffix("").parts)


def _backend_imports(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("backend."):
            found.add(node.module)
        elif isinstance(node, ast.Import):
            found.update(a.name for a in node.names if a.name.startswith("backend."))
    return found


class ArchitectureTest(unittest.TestCase):
    def setUp(self):
        self.graph = {
            _module_name(path): _backend_imports(path)
            for package in ("core", "domains")
            for path in sorted((BACKEND / package).glob("*.py"))
            if path.name != "__init__.py"
        }

    def test_core_does_not_depend_on_domains(self):
        offenders = {
            module: sorted(i for i in imports if i.startswith("backend.domains"))
            for module, imports in self.graph.items()
            if module.startswith("backend.core")
        }
        self.assertEqual({m: i for m, i in offenders.items() if i}, {})

    def test_no_import_cycles(self):
        visiting, done, cycles = set(), set(), []

        def visit(module, path):
            if module in done or module not in self.graph:
                return
            if module in visiting:
                cycles.append(path[path.index(module):] + [module])
                return
            visiting.add(module)
            for target in sorted(self.graph[module]):
                visit(target, path + [module])
            visiting.discard(module)
            done.add(module)

        for module in self.graph:
            visit(module, [])
        self.assertEqual(cycles, [])

    def test_entry_point_stays_thin(self):
        entry = (BACKEND / "app.py").read_text(encoding="utf-8")
        tree = ast.parse(entry)
        definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef))]
        self.assertEqual(definitions, [], "put code in backend/core or backend/domains")


if __name__ == "__main__":
    unittest.main()
