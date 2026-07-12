from pg_data_yaml.sync_comment import parse_table_comment


def test_plain_marker():
    parsed = parse_table_comment('reference data, synchronized directory')
    assert parsed is not None
    assert parsed.custom_select is None
    assert parsed.where_filter is None


def test_custom_select():
    comment = (
        'synchronized directory(select id, name from mytable order by name)'
    )
    parsed = parse_table_comment(comment)
    assert parsed is not None
    assert parsed.custom_select == 'select id, name from mytable order by name'
    assert parsed.where_filter is None


def test_where_filter():
    parsed = parse_table_comment(
        'synchronized directory(not is_deleted)'
    )
    assert parsed is not None
    assert parsed.custom_select is None
    assert parsed.where_filter == 'not is_deleted'


def test_filter_with_subselect_in_value_is_custom_select():
    parsed = parse_table_comment(
        "synchronized directory(id in (select id from other))"
    )
    assert parsed.custom_select == 'id in (select id from other)'
    assert parsed.where_filter is None


def test_without_marker():
    assert parse_table_comment('ordinary table') is None


def test_custom_label():
    parsed = parse_table_comment('global directory(not is_deleted)', 'global directory')
    assert parsed is not None
    assert parsed.where_filter == 'not is_deleted'
    assert parse_table_comment('global directory(not is_deleted)') is None
