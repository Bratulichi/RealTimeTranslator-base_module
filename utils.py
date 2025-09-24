import tomllib
from pathlib import Path

def get_app_version() -> str:
    pyproject = Path.cwd().parent / 'pyproject.toml'
    with pyproject.open('rb') as f:
        data = tomllib.load(f)
    return data['project']['version']
