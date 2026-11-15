"""The extension's settings dialog, run against a stand-in ``vlc`` object.

VLC itself is not available here, so the real ``activate()`` runs under a
plain Lua interpreter with a mock ``vlc`` table that records every widget and
its grid cell; pressing Start records the shell command instead of running it.

The layout rules follow how VLC 3.0.x's macOS dialog (VLCUIWidgets.m) sizes
its grid, starting from a 1x1 window: a column is as wide as its widest
single-cell dropdown/label/button, but a single-cell check box (width-sizable)
or no single-cell widget makes it count as only 128 pt; dropdowns are drawn at
their natural width whatever the column; widgets spanning columns are left out
of the widths (check boxes are stretched across them); and a row without a
single-row widget gets 128 pt of height.
"""
from __future__ import annotations

import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LUA = shutil.which("luajit") or shutil.which("lua")

pytestmark = pytest.mark.skipif(LUA is None, reason="lua/luajit required")

MOCK = r"""
local function out(...) io.write(table.concat({...}, "\t"), "\n") end
local buttons = {}
local function widget(kind, text, col, row, hspan, vspan)
    out("W", kind, text or "", col, row, hspan or 1, vspan or 1)
    local w = { checked = false }
    function w:add_value(label, id) out("V", label) end
    function w:get_value() return 1 end
    function w:get_checked() return self.checked end
    function w:set_text(t) end
    return w
end
vlc = {
    dialog = function(title)
        out("D", title)
        local d = {}
        function d:add_label(t, c, r, h, v) return widget("label", t, c, r, h, v) end
        function d:add_dropdown(c, r, h, v) return widget("dropdown", "", c, r, h, v) end
        function d:add_check_box(t, on, c, r, h, v)
            local w = widget("check", t, c, r, h, v); w.checked = on; return w
        end
        function d:add_button(t, fn, c, r, h, v) buttons[t] = fn; return widget("button", t, c, r, h, v) end
        function d:show() end
        function d:update() end
        function d:delete() end
        return d
    end,
    input = { item = function() return { uri = function() return arg[1] end } end },
    strings = { decode_uri = function(u) return u end },
    msg = { info = function() end, err = function(m) out("ERR", m) end },
}
os.execute = function(cmd) out("EXEC", cmd); return 0 end
dofile(arg[2])
activate()
out("PRESS", "Start")
buttons["Start"]()
"""


def run_dialog(tmp_path, video_name: str, config: str = "") -> tuple[list, list, str]:
    """Return (settings-dialog widgets, each dropdown's values, the Start command)."""
    cfg = tmp_path / "config.lua"
    cfg.write_text(f"return {{ {config} }}\n", encoding="utf-8")
    env = dict(os.environ, VLC_AUTODUB_SCRIPT="/opt/autodub/main.py",
               VLC_AUTODUB_PYTHON="/usr/bin/python3", VLC_AUTODUB_CONFIG=str(cfg))
    video = tmp_path / video_name
    lines = subprocess.run(
        [LUA, "-", f"file://{video}", os.path.join(ROOT, "transcribe.vlc.lua")],
        input=MOCK, env=env, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    rows = [line.split("\t") for line in lines]
    assert not [r for r in rows if r[0] == "ERR"], rows
    settings_end = next(i for i, r in enumerate(rows) if r[0] == "PRESS")
    widgets = [dict(kind=r[1], text=r[2], col=int(r[3]), row=int(r[4]),
                    hspan=int(r[5]), vspan=int(r[6]))
               for r in rows[:settings_end] if r[0] == "W"]
    values: list[list[str]] = []
    for r in rows[:settings_end]:
        if r[0] == "W" and r[1] == "dropdown":
            values.append([])
        elif r[0] == "V":
            values[-1].append(r[1])
    command = next(r[1] for r in rows if r[0] == "EXEC")
    return widgets, values, command


@pytest.mark.parametrize("video_name", ["my clip.mp4", "old clip.avi"])
def test_layout_fits_the_macos_grid(tmp_path, video_name):
    widgets, _values, _cmd = run_dialog(tmp_path, video_name)
    columns = {w["col"] for w in widgets if w["hspan"] == 1}
    assert columns == {1, 2}
    # Dropdowns are single cells in column 2, so they set its width.
    dropdowns = [w for w in widgets if w["kind"] == "dropdown"]
    assert dropdowns and all((w["col"], w["hspan"]) == (2, 1) for w in dropdowns)
    # Check boxes span the whole width: a single-cell one would shrink its
    # column to 128 pt (and cut both it and the dropdowns off).
    checks = [w for w in widgets if w["kind"] == "check"]
    assert checks and all((w["col"], w["hspan"]) == (1, 2) for w in checks)
    assert all(w["vspan"] == 1 for w in widgets)
    rows = sorted({w["row"] for w in widgets})
    assert rows == list(range(1, len(rows) + 1))        # contiguous: no empty row
    cells = [(w["col"] + i, w["row"]) for w in widgets for i in range(w["hspan"])]
    assert len(cells) == len(set(cells))                # no overlapping cells


def test_format_note_only_when_in_place_is_impossible(tmp_path):
    mp4, _v, _c = run_dialog(tmp_path, "a.mp4")
    avi, _v, _c = run_dialog(tmp_path, "b.avi")
    note = "(needs .mp4, .m4v, .mov or .mkv)"
    assert note not in [w["text"] for w in mp4]
    assert note in [w["text"] for w in avi]
    assert len({w["row"] for w in avi}) == len({w["row"] for w in mp4}) + 1


def test_start_runs_the_cli_with_dialog_defaults(tmp_path):
    _w, values, command = run_dialog(tmp_path, "my clip.mp4")
    assert [v[0] for v in values] == ["Auto-detect", "English (en)", "Dub + subtitles"]
    assert command.startswith("( '/usr/bin/python3' '/opt/autodub/main.py' ")
    assert f"'{tmp_path}/my clip.mp4' '--in-place' '--target-lang' 'en' &" in command

