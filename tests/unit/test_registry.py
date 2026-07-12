import pytest

from pg_data_yaml.registry import TableRegistry


class DummyPg:
    pass


def test_comment_label_filter():
    registry = TableRegistry(DummyPg(), comment_label='global directory')
    filter_sql, params = registry._build_table_filter()

    assert 'ilike $1' in filter_sql
    assert params == ['%global directory%']


def test_table_list_predicate_filter():
    predicate = "c.relname like 'ref_%'"
    registry = TableRegistry(DummyPg(), table_list_predicate=predicate)
    filter_sql, params = registry._build_table_filter()

    assert predicate in filter_sql
    assert 'ilike' not in filter_sql
    assert params == []


def test_comment_label_and_predicate_are_mutually_exclusive():
    with pytest.raises(ValueError, match='mutually exclusive'):
        TableRegistry(
            DummyPg(),
            comment_label='global directory',
            table_list_predicate='true',
        )


def test_either_comment_label_or_predicate_is_required():
    with pytest.raises(ValueError, match='is required'):
        TableRegistry(DummyPg())


def test_predicate_mode_ignores_comments():
    registry = TableRegistry(DummyPg(), table_list_predicate='true')
    assert registry._parse_row_comment('global directory(not is_deleted)') is None


def test_comment_label_mode_parses_comments():
    registry = TableRegistry(DummyPg(), comment_label='global directory')
    parsed = registry._parse_row_comment('global directory(not is_deleted)')
    assert parsed is not None
    assert parsed.where_filter == 'not is_deleted'
