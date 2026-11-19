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
  Cards fill the available chat width. Restore document padding after clearing
  a room so the first card is not clipped; the SC heading uses spaces, not dots.
  Video overlays use 130 px wide cards, minimum 40 px high, growing to fit text,
  11 px text and a translucent background (alpha 160/255). No countdown, progress
  bar or middle-dot separators. Display for one tenth of the server duration,
  with at least 6 seconds and 2 + ceil(non-whitespace characters / 5) seconds
  to read from first receipt (or future start). Chat history is unaffected.
  Explicit document block formats keep incoming messages and rebuilt history
  identical. Draw the rounded background behind selectable text; Qt rich text
  does not implement CSS `border-radius`.
- Favorites occupy a horizontal 42 px high strip in the header, following
  verified account status, with centered 26 px avatars in square cells.
  The add button follows the last avatar. Wheel input and drag-edge scrolling
  reveal overflow; live-first grouping and manual ordering remain intact.
  No left sidebar, splitter or collapse control. Keep video/chat splitters.
- The editable app icon is `assets/studio-icon.svg`; `scripts/build_icon.py`
  exports PNG and the 16–256 px Windows ICO. `scripts/build_launcher.py` embeds
  it in the native launcher; window and shortcut AppIDs match for taskbar pins.
- The global loudness-balance toggle enables VLC's compressor per player.
  `audio_balance.py` bridges the bundled VLC 3 typed variable API because the
  LibVLC media-player filter variable does not inherit CLI/media filter options.
  Native sample capture tests validate actual gain and reversible disabling;
  existing silence-based startup tests cover pause, mute and volume safety.
  Unsupported runtimes fall back to original audio, not a startup failure.
- Live SC without usable timestamps still receives minimum reading time;
  expired restored history is rejected. An oversized card fits the tile with
  an ellipsis and remains complete in chat. Owned native windows remain above
  the video's child HWND without stealing focus or being globally topmost.

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
