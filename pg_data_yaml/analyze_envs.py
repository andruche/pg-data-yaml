from __future__ import annotations

import argparse
import os
import sys

import yaml

from .paths import list_table_yaml_files


class AnalyzeEnvs:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.sources = [os.path.abspath(path) for path in args.source]

    def run(self) -> None:
        self._validate()
        synchronized_directories = open('/tmp/synchronized_directory.txt').read().split('\n')
        env_files = [list_table_yaml_files(path) for path in self.sources]
        all_paths = set.union(*[set(files) for files in env_files])
        if not all_paths:
            print('Nothing to analyze: no table files across environments')
            return

        for rel_path in sorted(all_paths):
            lines = {}
            postfix = ''
            for env in self.sources:
                file_path = os.path.join(env, rel_path)
                if os.path.isfile(file_path):
                    for line in yaml.safe_load(open(file_path)):
                        line = str(line)
                        lines[line] = lines.get(line, 0) + 1
                else:
                    postfix = '*'
            identical_lines = sum(1 for count in lines.values() if count == len(self.sources))
            table = self.path_to_table_name(rel_path)
            sync_dir = "да" if table in synchronized_directories else ''
            print(f'{table}\t{identical_lines}/{len(lines) - identical_lines}{postfix}\t{sync_dir}')

    # def run_base(self) -> None:
    #     synchronized_directories=open('/tmp/synchronized_directory.txt').read().split('\n')
    #     env_files = [list_table_yaml_files(path) for path in self.sources]
    #     all_paths = set.union(*[set(files) for files in env_files])
    #     if not all_paths:
    #         print('Nothing to analyze: no table files across environments')
    #         return

    #     for rel_path in sorted(all_paths):
    #         env = self.sources[0]
    #         file_path = os.path.join(env, rel_path)
    #         lines_count = len(yaml.safe_load(open(file_path)))
    #         table = self.path_to_table_name(rel_path)
    #         sync_dir="да" if table in synchronized_directories else ''
    #         print(f'{table}\t{lines_count}/0\t{sync_dir}')

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

    @staticmethod
    def path_to_table_name(path: str) -> str:
        return '{}.{}'.format(*path[:-5].split('/'))
