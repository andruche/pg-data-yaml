import re
from typing import Any

import yaml

_INTERVAL_STR_RE = re.compile(r'^-?(\d+ days? )?\d+:\d{2}:\d{2}$')


class Formatter:
    _representers_registered = False

    def __init__(self):
        self._register_representers()

    @classmethod
    def _register_representers(cls):
        if cls._representers_registered:
            return

        def str_presenter(dumper, data):
            if '\n' in data:
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='|')
            if _INTERVAL_STR_RE.fullmatch(data):
                return dumper.represent_scalar('tag:yaml.org,2002:str', data, style='')
            return dumper.represent_scalar('tag:yaml.org,2002:str', data)

        yaml.add_representer(str, str_presenter)
        cls._representers_registered = True

    @staticmethod
    def dump(data: Any, file_name: str = None):
        Formatter._register_representers()
        if data is None:
            return ''
        file = None
        if file_name:
            file = open(file_name, 'w')
        return yaml.dump(
            data,
            file,
            allow_unicode=True,
            sort_keys=False,
            width=float('inf'),
        )

    @staticmethod
    def load(file_name: str) -> Any:
        with open(file_name) as file:
            return yaml.safe_load(file)
