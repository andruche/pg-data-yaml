import datetime
import ipaddress

import yaml

from pg_data_yaml.formatter import Formatter
from pg_data_yaml.values import ordered_row, serialize_value


def test_inet_serialized_as_string():
    row = ordered_row({'ip': ipaddress.IPv4Address('107.170.65.67')})
    assert row['ip'] == '107.170.65.67'


def test_inet_yaml_dump_is_plain_string():
    rows = [ordered_row({'ip': ipaddress.IPv4Address('107.170.65.67')})]
    dumped = Formatter.dump(rows)
    assert '!!python/object' not in dumped
    assert "ip: 107.170.65.67" in dumped
    assert yaml.safe_load(dumped) == [{'ip': '107.170.65.67'}]


def test_serialize_value_inet_network():
    assert serialize_value(ipaddress.IPv4Network('10.0.0.0/8')) == '10.0.0.0/8'


def test_timedelta_serialized_as_hms():
    assert serialize_value(datetime.timedelta(0, 3600, 0)) == '01:00:00'
    assert serialize_value(datetime.timedelta(hours=1)) == '01:00:00'


def test_timedelta_with_days():
    assert serialize_value(datetime.timedelta(days=1, seconds=3600)) == '1 day 01:00:00'


def test_timedelta_yaml_dump_is_plain_string():
    rows = [ordered_row({'duration': datetime.timedelta(hours=1)})]
    dumped = Formatter.dump(rows)
    assert '!!python/object' not in dumped
    assert 'duration: 01:00:00' in dumped
    assert yaml.safe_load(dumped) == [{'duration': '01:00:00'}]


def test_datetime_infinity_serialized():
    assert serialize_value(datetime.datetime(1, 1, 1, 0, 0)) == '-infinity'
    assert serialize_value(
        datetime.datetime(9999, 12, 31, 23, 59, 59, 999999)
    ) == 'infinity'


def test_date_infinity_serialized():
    assert serialize_value(datetime.date(1, 1, 1)) == '-infinity'
    assert serialize_value(datetime.date(9999, 12, 31)) == 'infinity'


def test_timestamptz_infinity_yaml_roundtrip():
    rows = [ordered_row({
        'tstz': datetime.datetime(1, 1, 1, 0, 0),
    })]
    dumped = Formatter.dump(rows)
    assert yaml.safe_load(dumped) == [{'tstz': '-infinity'}]
