# Black Label Browser

Local stdio MCP and skill for native Safari/Chrome control on macOS. 14 tools cover status, navigation, snapshots, focused window selection, observed-element actions, text, shortcuts, scrolling, screenshots, file selection, recent text codes and email-code search routing.

Install/build instructions, requirements and public marketplace commands are in [the repository README](https://github.com/mthburnsbarber-web/black-label-plugins#readme). From the repository root: `python3 black-label-browser/install.py`. The helper is installed at `~/Applications/Black Label Browser Bridge.app`; it needs its own Accessibility and Screen Recording grants. Python Messages access is separate.

No Chrome extension, CDP, Apple Events, Automator, telemetry or hosted server. Snapshot element IDs are ephemeral. Failed or successful actions invalidate references; inspect fresh state before continuing. Global keyboard/mouse actions serialize across both browsers. Screen contents are returned to the calling AI host, whose own privacy terms apply.

Saved-session and login workflows require an executing host agent. Email routing does not read the inbox. Text lookup handles matching numeric codes in Messages plain-text rows; messages stored only as attributed bodies are not parsed. Human/device challenges remain user steps. Tested behavior and limits are in [VERIFICATION.md](VERIFICATION.md).
