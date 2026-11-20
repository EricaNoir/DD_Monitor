import json
import tempfile
from pathlib import Path


def load_state(path):
    default = {'rooms': [], 'slots': [None] * 4, 'layout': 4, 'chat_visible': True,
               'controls_visible': True, 'chat_font': 13,
               'chat_follow': True, 'volume': 35, 'audio_balance': True, 'slot_settings': {}}
    try:
        default.update(json.loads(Path(path).read_text(encoding='utf-8')))
    except (OSError, ValueError):
        pass
    return default


def save_json(path, state):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, ensure_ascii=False, indent=2)
    temp = None
    try:
        # Separate writers must never truncate or rename one another's temp file.
        # Close it before replace: Windows does not rename an open NamedTemporaryFile.
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8',
                                         dir=path.parent, prefix=path.name + '.',
                                         suffix='.tmp', delete=False) as stream:
            temp = Path(stream.name)
            stream.write(payload)
        temp.replace(path)
    finally:
        if temp is not None:
            temp.unlink(missing_ok=True)


def load_credentials(root):
    path = Path(root) / 'user-data' / 'credentials.json'
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        if (Path(root) / 'portable-mode').is_file():
            return {}
        # Import only from the user's existing DD Monitor installation.
        legacy = Path(root).parent / 'DD-Monitor' / 'app' / 'utils' / 'config.json'
        try:
            data = json.loads(legacy.read_text(encoding='utf-8-sig'))
            return {'SESSDATA': data['sessionData']} if data.get('sessionData') else {}
        except (OSError, ValueError, KeyError):
            return {}
