import json
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
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8')
    temp.replace(path)


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
