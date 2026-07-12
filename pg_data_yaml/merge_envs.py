from __future__ import annotations

import argparse
import os
import shutil
import sys

from .paths import list_table_yaml_files


class MergeEnvs:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.sources = [os.path.abspath(path) for path in args.source]
        self.out_dir = os.path.abspath(args.out_dir)

    def run(self) -> None:
        self._validate()
        env_files = [list_table_yaml_files(path) for path in self.sources]
        common_paths = set.intersection(*[set(files) for files in env_files])
        if not common_paths:
            print('Nothing to merge: no common table files across environments')
            return

        merged = 0
        skipped_diff = 0
        skipped_base_conflict = 0

        for rel_path in sorted(common_paths):
            source_paths = [files[rel_path] for files in env_files]
            if not self._files_identical(source_paths):
                print(
                    f'SKIP: {rel_path} differs between environments',
                    file=sys.stderr,
                )
                skipped_diff += 1
                continue

            base_path = os.path.join(self.out_dir, rel_path)
            if os.path.exists(base_path):
                if not self._files_identical([source_paths[0], base_path]):
                    print(
                        f'SKIP: {rel_path} in base dir differs from environments',
                        file=sys.stderr,
                    )
                    skipped_base_conflict += 1
                    continue
                self._remove_from_sources(rel_path, source_paths)
                print(f'merged (already in base): {rel_path}')
            else:
                self._move_to_base(rel_path, source_paths)
                print(f'merged: {rel_path}')
            merged += 1

        print(
            f'Done: merged {merged}, '
            f'skipped {skipped_diff} (differs between envs), '
            f'skipped {skipped_base_conflict} (conflicts with base)'
        )

    def _validate(self) -> None:
        if len(self.sources) < 2:
            print('ERROR: specify at least two --source directories', file=sys.stderr)
            sys.exit(1)

        seen = set()
        for path in self.sources:
            if path in seen:
                print(f'ERROR: duplicate source directory: {path}', file=sys.stderr)
                sys.exit(1)
            seen.add(path)
            if not os.path.isdir(path):
                print(f'ERROR: source directory not found: {path}', file=sys.stderr)
                sys.exit(1)

        if self.out_dir in self.sources:
            print('ERROR: --out-dir must not be one of --source directories', file=sys.stderr)
            sys.exit(1)

        for path in self.sources:
            if os.path.commonpath([path, self.out_dir]) == self.out_dir:
                print(
                    f'ERROR: source directory inside --out-dir is not supported: {path}',
                    file=sys.stderr,
                )
                sys.exit(1)
            if os.path.commonpath([path, self.out_dir]) == path:
                print(
                    f'ERROR: --out-dir inside source directory is not supported: {path}',
                    file=sys.stderr,
                )
                sys.exit(1)

        if not self.args.dry_run:
            os.makedirs(self.out_dir, exist_ok=True)

    @staticmethod
    def _files_identical(paths: list[str]) -> bool:
        with open(paths[0], 'rb') as first:
            content = first.read()
        for path in paths[1:]:
            with open(path, 'rb') as other:
                if other.read() != content:
                    return False
        return True

    def _move_to_base(self, rel_path: str, source_paths: list[str]) -> None:
        base_path = os.path.join(self.out_dir, rel_path)
        if self.args.dry_run:
            return
        os.makedirs(os.path.dirname(base_path), exist_ok=True)
        shutil.move(source_paths[0], base_path)
        for path in source_paths[1:]:
            os.remove(path)

    def _remove_from_sources(self, rel_path: str, source_paths: list[str]) -> None:
        if self.args.dry_run:
            return
        for path in source_paths:
            os.remove(path)
        self._remove_empty_dirs(source_paths)

    @staticmethod
    def _remove_empty_dirs(file_paths: list[str]) -> None:
        dirs = {os.path.dirname(path) for path in file_paths}
        for directory in sorted(dirs, key=len, reverse=True):
            if os.path.isdir(directory) and not os.listdir(directory):
                os.rmdir(directory)
