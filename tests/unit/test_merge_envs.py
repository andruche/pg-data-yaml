import argparse
from pathlib import Path

from pg_data_yaml.merge_envs import MergeEnvs


def _run_merge(sources, out_dir, dry_run=False):
    args = argparse.Namespace(source=sources, out_dir=str(out_dir), dry_run=dry_run)
    MergeEnvs(args).run()


def test_merge_identical_files_to_base(tmp_path: Path):
    content = '- id: 1\n  name: test\n'
    dev = tmp_path / 'dev'
    prod = tmp_path / 'prod'
    base = tmp_path / 'base'
    for env in (dev, prod):
        table_dir = env / 'public'
        table_dir.mkdir(parents=True)
        (table_dir / 'countries.yaml').write_text(content)
    (dev / 'public' / 'only_dev.yaml').write_text('- id: 2\n')

    _run_merge([str(dev), str(prod)], base)

    assert (base / 'public' / 'countries.yaml').read_text() == content
    assert not (dev / 'public' / 'countries.yaml').exists()
    assert not (prod / 'public' / 'countries.yaml').exists()
    assert (dev / 'public' / 'only_dev.yaml').exists()


def test_skip_when_envs_differ(tmp_path: Path):
    dev = tmp_path / 'dev'
    prod = tmp_path / 'prod'
    base = tmp_path / 'base'
    for env, value in ((dev, '1'), (prod, '2')):
        table_dir = env / 'public'
        table_dir.mkdir(parents=True)
        (table_dir / 'countries.yaml').write_text(f'- id: {value}\n')

    _run_merge([str(dev), str(prod)], base)

    assert not (base / 'public' / 'countries.yaml').exists()
    assert (dev / 'public' / 'countries.yaml').exists()
    assert (prod / 'public' / 'countries.yaml').exists()


def test_remove_duplicates_when_already_in_base(tmp_path: Path):
    content = '- id: 1\n'
    dev = tmp_path / 'dev'
    prod = tmp_path / 'prod'
    base = tmp_path / 'base'
    base_table = base / 'public'
    base_table.mkdir(parents=True)
    (base_table / 'countries.yaml').write_text(content)
    for env in (dev, prod):
        table_dir = env / 'public'
        table_dir.mkdir(parents=True)
        (table_dir / 'countries.yaml').write_text(content)

    _run_merge([str(dev), str(prod)], base)

    assert (base / 'public' / 'countries.yaml').read_text() == content
    assert not (dev / 'public' / 'countries.yaml').exists()
    assert not (prod / 'public' / 'countries.yaml').exists()
