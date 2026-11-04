"""The runtime must not reintroduce a database backend or release binding."""
import ast
from pathlib import Path

def test_runtime_has_no_retired_modules_or_database_imports():
    root=Path(__file__).resolve().parents[1]/'app'
    assert not list(root.glob('sqlite*.py'))
    for path in root.glob('*.py'):
        for node in ast.walk(ast.parse(path.read_text())):
            modules=[a.name for a in node.names] if isinstance(node,ast.Import) else [node.module or ''] if isinstance(node,ast.ImportFrom) else []
            assert not any(name=='sqlite3' or name.startswith(('app.sqlite','sqlite_')) for name in modules),path.name

def test_active_documentation_has_no_retired_backend_references():
    root=Path(__file__).resolve().parents[1]
    for path in [root/'README.md',*list((root/'docs').glob('*.md'))]:
        assert 'sqlite' not in path.read_text().lower(),path.name
