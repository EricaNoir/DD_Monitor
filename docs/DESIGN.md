# Studio UI conventions

`studio/theme.py` is the source for semantic colors, typography, control sizes,
icon stroke weight and spacing. `studio/theme.qss` is a template: always load it
through `studio.theme.stylesheet()`, including in preview and test scripts.

- Regular controls are 32 px high; compact player controls are 28 px high.
  `BelowComboBox` and `StudioSpinBox` share these dimensions and custom chevrons.
- Action glyphs use an 18 px box, with a common 24-unit grid, 1.75-unit stroke,
  and rounded line caps/joins. Inline gift and clear glyphs are 16 px; the stepper
  uses 12 px chevrons. Click targets stay larger than the glyphs.
- `icons.icon`, `icons.icon_image`, `icons.paint_icon` and `icons.decorate` share
  the same vector paths, palette and HiDPI rendering. Do not use Unicode or emoji
  substitutes for action icons. Avatar photos and the app logo are content, not
  action glyphs.
- Body text is 13 px; secondary labels use the same size and a muted color.
  Compact chat tabs use 11 px, headings 15 px and the brand 16 px. Chat text may
  still follow the user's chosen size.
- SC bubbles have 8 px padding, 8 px corner radius and a shared message gap.
  Explicit document block formats keep incoming messages and rebuilt history
  identical. Draw the rounded background behind selectable text; Qt rich text
  does not implement CSS `border-radius`.
- The avatar rail starts at the left content edge; the sidebar toggle is centered
  over the collapsed rail. Keep the existing video/chat splitter behavior.

Use the offscreen UI tests to verify real widget geometry and render examples.
These previews contain sample messages, not paid test messages.

# Automated checks

The fork's workflow validates Studio on Windows with Python 3.11, 3.12 and 3.13,
using `requirements-studio.txt` and the complete offline unit/UI suite. It uploads
sample previews with `actions/upload-artifact@v4`; it does not publish releases.
The inherited workflow built the upstream PyQt application and used retired v2
artifact actions, so it failed before checking this branch's Studio code.

Audio-device smoke tests and authenticated read-only API checks remain opt-in:
hosted runners do not provide the user's audio device or Bilibili credentials.
