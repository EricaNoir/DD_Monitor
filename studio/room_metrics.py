"""Live-room statistics with explicit time zones and audience semantics."""
from datetime import datetime, timedelta, timezone
import math
import re


def live_start(value):
    try:
        if isinstance(value, str) and '-' in value:
            value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S').replace(
                tzinfo=timezone(timedelta(hours=8))).timestamp()
        number = float(value)
        return number if math.isfinite(number) and number > 0 else None
    except (TypeError, ValueError, OverflowError):
        return None


def audience_update(command):
    # Ranking count, heartbeat popularity and WATCHED_CHANGE are not online users.
    if command.get('cmd') != 'ONLINE_RANK_COUNT':
        return None
    data = command.get('data')
    if not isinstance(data, dict):
        return None
    value = data.get('online_count')
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        value = int(value)
    except ValueError:
        return None
    if value < 0:
        return None
    display = data.get('online_count_text')
    if not isinstance(display, str) or not re.fullmatch(r'[0-9]{1,9}(?:\.[0-9]{1,2})?[万亿]?\+?', display):
        display = f'{value / 10000:.1f}万' if value >= 10000 else str(value)
    return {'count': value, 'text': display}


def elapsed_text(start, now, compact=False):
    start = live_start(start)
    if start is None or start > now:
        return '—'
    hours, remainder = divmod(int(now - start), 3600)
    minutes, seconds = divmod(remainder, 60)
    return f'{hours:02d}:{minutes:02d}' if compact else f'{hours:02d}:{minutes:02d}:{seconds:02d}'
