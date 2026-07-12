import datetime
import decimal
import ipaddress
import uuid
from typing import Any

_IPADDRESS_TYPES = (
    ipaddress.IPv4Address,
    ipaddress.IPv6Address,
    ipaddress.IPv4Network,
    ipaddress.IPv6Network,
    ipaddress.IPv4Interface,
    ipaddress.IPv6Interface,
)

_PG_DATETIME_NEGATIVE_INFINITY = datetime.datetime(1, 1, 1, 0, 0)
_PG_DATETIME_INFINITY = datetime.datetime(9999, 12, 31, 23, 59, 59, 999999)
_PG_DATE_NEGATIVE_INFINITY = datetime.date(1, 1, 1)
_PG_DATE_INFINITY = datetime.date(9999, 12, 31)


def format_timedelta(value: datetime.timedelta) -> str:
    negative = value < datetime.timedelta(0)
    if negative:
        value = -value
    total_seconds = int(value.total_seconds())
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    time_part = f'{hours:02d}:{minutes:02d}:{seconds:02d}'
    if days:
        day_label = 'day' if days == 1 else 'days'
        body = f'{days} {day_label} {time_part}'
    else:
        body = time_part
    return f'-{body}' if negative else body


def _serialize_datetime(value: datetime.datetime) -> str:
    if value == _PG_DATETIME_NEGATIVE_INFINITY:
        return '-infinity'
    if value == _PG_DATETIME_INFINITY:
        return 'infinity'
    return value.isoformat()


def _serialize_date(value: datetime.date) -> str:
    if value == _PG_DATE_NEGATIVE_INFINITY:
        return '-infinity'
    if value == _PG_DATE_INFINITY:
        return 'infinity'
    return value.isoformat()


def serialize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, _IPADDRESS_TYPES):
        return str(value)
    if isinstance(value, datetime.timedelta):
        return format_timedelta(value)
    if isinstance(value, datetime.datetime):
        return _serialize_datetime(value)
    if isinstance(value, datetime.date):
        return _serialize_date(value)
    if isinstance(value, datetime.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, memoryview):
        return bytes(value).hex()
    return value


def ordered_row(row: dict) -> dict:
    return {key: serialize_value(row[key]) for key in row}


def rows_equal(left: dict, right: dict) -> bool:
    if set(left.keys()) != set(right.keys()):
        return False
    return all(left[key] == right[key] for key in left)


def pk_key(row: dict, pk_columns: list[str]) -> tuple:
    return tuple(row[col] for col in pk_columns)
