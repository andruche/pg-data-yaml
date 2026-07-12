from __future__ import annotations

import glob
import os


def list_table_yaml_files(root_dir: str) -> dict[str, str]:
    """Return mapping rel_path (schema/table.yaml) -> absolute path."""
    files = {}
    for path in glob.glob(os.path.join(root_dir, '*', '*.yaml')):
        rel_path = os.path.relpath(path, root_dir)
        files[rel_path] = path
    return files
