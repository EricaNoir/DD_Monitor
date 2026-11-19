"""Shared semantic tokens for QSS, custom painting and rich chat text."""
from pathlib import Path
from string import Template

COLORS = {
    'window': '#181818', 'surface': '#202020', 'chat_surface': '#232323',
    'field': '#292929', 'panel': '#272727', 'hover': '#333333',
    'selected': '#383838', 'pressed': '#414141', 'border': '#3b3b3b',
    'border_strong': '#505050', 'focus': '#888888',
    'text': '#e6e6e6', 'text_secondary': '#aaaaaa', 'text_muted': '#929292',
    'text_disabled': '#666666', 'icon': '#dcdcdc', 'inverse': '#202020',
    'primary': '#e7e7e7', 'primary_hover': '#ffffff', 'avatar': '#454545',
    'live': '#55dc91', 'offline': '#777777', 'warning': '#d8a074',
    'danger_hover': '#653333', 'video': '#0d0d0d',
    'gift': '#cbbd98', 'favorite': '#d9c794', 'medal': '#bba5d2',
    'sc_surface': '#34312b', 'sc_border': '#484238',
    'sc_heading': '#e8cd91', 'sc_text': '#f0e9db', 'sc_progress': '#c5a669',
    'sc_overlay': 'rgba(38,35,29,160)',
}
FONTS = {
    'family': '"Microsoft YaHei UI", "Segoe UI"',
    'body': 13, 'caption': 11, 'small': 12, 'heading': 15, 'brand': 16, 'amount': 21,
}
SIZES = {
    'control': 32, 'compact': 28, 'icon': 18, 'inline_icon': 16,
    'stepper_icon': 12, 'radius': 6, 'bubble_radius': 8, 'gap': 8,
    'rail': 42, 'rail_action': 42, 'tile_toolbar': 36, 'control_gap': 3,
    'bubble_padding': 8, 'message_gap': 8,
    'sc_overlay_width': 130, 'sc_overlay_height': 40, 'sc_overlay_gap': 4,
    'sc_overlay_inset': 8,
    'status_dot': 7, 'avatar_status_dot': 10,
}
ICON_STROKE = 1.75


def tokens():
    return {**COLORS, **{f'font_{k}': v for k, v in FONTS.items()},
            **{f'size_{k}': v for k, v in SIZES.items()},
            'control_inner': SIZES['control'] - 2, 'compact_inner': SIZES['compact'] - 2}


def stylesheet():
    return Template(Path(__file__).with_name('theme.qss').read_text(encoding='utf-8')).substitute(tokens())


def horizontal_scrollbar_style():
    # Qt's scroll-area container does not consistently inherit app-level rules.
    # Apply this shared component directly, with the same palette tokens.
    return Template('''
        QScrollBar:horizontal { background: transparent; border: 0; height: 4px; margin: 0; }
        QScrollBar::handle:horizontal { background: $border_strong; border: 0; min-width: 24px; border-radius: 2px; }
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; height: 0; border: 0; background: transparent; }
        QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; border: 0; }
        QScrollBar::left-arrow:horizontal, QScrollBar::right-arrow:horizontal { width: 0; height: 0; border: 0; }
    ''').substitute(tokens())
