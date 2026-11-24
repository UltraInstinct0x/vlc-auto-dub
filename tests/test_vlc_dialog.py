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
    strings = { decode_uri = function(u) return u end,
                make_uri = function(p) return "file://" .. p end },
    msg = { info = function() end, err = function(m) out("ERR", m) end },
    object = { input = function() return {} end },
    var = { get = function(obj, name) return 42000000 end },    -- 42 s, in microseconds
    playlist = {
        current = function() return 7 end,
        add = function(items)
            for _, it in ipairs(items) do out("ADD", it.path, table.concat(it.options, "|")) end
        end,
        delete = function(id) out("DEL", id) end,
    },
}
os.execute = function(cmd) out("EXEC", cmd); return 0 end
dofile(arg[2])
activate()
for name in string.gmatch(arg[3] or "", "[^,]+") do
    out("PRESS", name)
    buttons[name]()
end
"""


def run_lua(tmp_path, video_name: str, presses: str, config: str = "", **env_extra) -> list:
    """Run activate() and press the named buttons; return the recorded rows."""
    cfg = tmp_path / "config.lua"
    cfg.write_text(f"return {{ {config} }}\n", encoding="utf-8")
    env = dict(os.environ, VLC_AUTODUB_SCRIPT="/opt/autodub/main.py",
               VLC_AUTODUB_PYTHON="/usr/bin/python3", VLC_AUTODUB_CONFIG=str(cfg))
    env.update(env_extra)
    video = tmp_path / video_name
    lines = subprocess.run(
        [LUA, "-", f"file://{video}", os.path.join(ROOT, "transcribe.vlc.lua"), presses],
        input=MOCK, env=env, check=True, capture_output=True, text=True,
    ).stdout.splitlines()
    rows = [line.split("\t") for line in lines]
    assert not [r for r in rows if r[0] == "ERR"], rows
    return rows


def run_dialog(tmp_path, video_name: str, config: str = "") -> tuple[list, list, str]:
    """Return (settings-dialog widgets, each dropdown's values, the Start command)."""
    rows = run_lua(tmp_path, video_name, "Start", config)
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
    assert [v[0] for v in values] == ["Auto-detect", "English (en)", "Dub + subtitles",
                                      "Off", "100%"]
    assert command.startswith("( '/usr/bin/python3' '/opt/autodub/main.py' ")
    assert f"'{tmp_path}/my clip.mp4' '--in-place' '--target-lang' 'en' " \
           "'--dub-volume' '1' '--original-volume' '0' &" in command


def test_config_preselects_volumes(tmp_path):
    _w, values, command = run_dialog(tmp_path, "my clip.mkv",
                                     "original_volume = 0.3, dub_volume = 1.25")
    original, dub = values[3], values[4]
    assert original[0] == "Medium (30%)" and sorted(original) == sorted(
        ["Off", "Quiet (15%)", "Medium (30%)", "Loud (50%)"])    # moved, nothing lost
    assert dub[0] == "125%"
    assert "'--dub-volume' '1.25' '--original-volume' '0.3'" in command


# --- Reopen video ----------------------------------------------------------

def _reopened(rows) -> tuple[str, list[str]]:
    add = next(r for r in rows if r[0] == "ADD")
    assert ["DEL", "7"] in rows                       # the old playlist entry goes
    return add[1], add[2].split("|")


def test_reopen_in_place_reloads_the_original(tmp_path):
    path, options = _reopened(run_lua(tmp_path, "my clip.mp4", "Start,Reopen video"))
    assert path == f"file://{tmp_path}/my clip.mp4"
    assert options == ["start-time=42"]


def test_reopen_separate_files_plays_the_dubbed_copy_with_its_subtitles(tmp_path):
    # .avi cannot take tracks in place, so the dub is written beside it.
    (tmp_path / "old clip_dubbed.avi").write_bytes(b"x")
    (tmp_path / "old clip.srt").write_text("1\n", encoding="utf-8")
    (tmp_path / "old clip.autodub.log").write_text("AUTODUB_EXIT=0\n", encoding="utf-8")
    path, options = _reopened(run_lua(tmp_path, "old clip.avi", "Start,Reopen video"))
    assert path == f"file://{tmp_path}/old clip_dubbed.avi"
    assert options == [f"sub-file={tmp_path}/old clip.srt", "start-time=42"]


@pytest.mark.parametrize("log", [None, "[autodub] dubbing line 1/9\n", "AUTODUB_EXIT=1\n",
                                 "AUTODUB_EXIT=143\n"])
def test_reopen_ignores_the_copy_unless_the_job_succeeded(tmp_path, log):
    """Running, failed or stopped: the copy is partial or from an earlier run."""
    (tmp_path / "old clip_dubbed.avi").write_bytes(b"x")
    (tmp_path / "old clip.srt").write_text("1\n", encoding="utf-8")
    if log is not None:
        (tmp_path / "old clip.autodub.log").write_text(log, encoding="utf-8")
    path, options = _reopened(run_lua(tmp_path, "old clip.avi", "Start,Reopen video"))
    assert path == f"file://{tmp_path}/old clip.avi"
    assert options == ["start-time=42"]


@pytest.mark.parametrize("finished", [False, True])
def test_reopen_after_dialog_restart_remembers_separate_files(tmp_path, finished):
    """A running job found on activate() keeps its mode (read from the pidfile)."""
    (tmp_path / "film_dubbed.avi").write_bytes(b"x")
    (tmp_path / "film.autodub.pid").write_text("12345 separate dub\n", encoding="utf-8")
    (tmp_path / "film.autodub.log").write_text(
        "AUTODUB_EXIT=0\n" if finished else "[autodub] dubbing line 1/9\n", encoding="utf-8")
    rows = run_lua(tmp_path, "film.avi", "Reopen video")
    assert ["D", "Auto-Dub"] in rows                  # status dialog, not settings
    path, options = _reopened(rows)
    # The copy is only played once the job has succeeded.
    assert path == f"file://{tmp_path}/" + ("film_dubbed.avi" if finished else "film.avi")
    assert options == ["start-time=42"]               # dub only: no subtitles attached


REOPEN = r"""
vlc = { strings = { make_uri = function(p) return "file://" .. p end } }
dofile(arg[1])
local files = {}
for f in string.gmatch(arg[3], "[^,]+") do files[f] = true end
local ext = (arg[3]:match("a_dubbed(%.%a+)") or ".mkv")
if ext == ".wav" then ext = ".mkv" end
local j = { in_place = false, mode = arg[2], uri = "file:///v/a" .. ext,
            dubbed = "/v/a_dubbed" .. ext, dubbed_audio = "/v/a_dubbed.wav", srt = "/v/a.srt" }
local path, options = reopen_target(j, function(p) return files[p] == true end, true)
io.write(path, "\t", table.concat(options, "|"))
"""


@pytest.mark.parametrize("mode,files,expected", [
    ("both", "/v/a_dubbed.mkv,/v/a.srt", ("file:///v/a_dubbed.mkv", "")),   # subs inside; old .srt ignored
    ("both", "/v/a_dubbed.avi,/v/a.srt", ("file:///v/a_dubbed.avi", "sub-file=/v/a.srt")),  # .avi: .srt beside
    ("subs", "/v/a_dubbed.mkv,/v/a.srt", ("file:///v/a.mkv", "sub-file=/v/a.srt")),  # stale dub ignored
    ("dub", "/v/a_dubbed.mkv,/v/a.srt", ("file:///v/a_dubbed.mkv", "")),             # stale srt ignored
    ("both", "/v/a_dubbed.wav,/v/a.srt", ("file:///v/a_dubbed.wav", "sub-file=/v/a.srt")),  # audio-only
    ("both", "", ("file:///v/a.mkv", "")),                                           # nothing written
])
def test_reopen_target(mode, files, expected):
    out = subprocess.run([LUA, "-", os.path.join(ROOT, "transcribe.vlc.lua"), mode, files or ","],
                         input=REOPEN, check=True, capture_output=True, text=True).stdout
    assert tuple(out.split("\t")) == expected


def test_real_job_command_records_its_mode_and_cleans_up(tmp_path):
    """Run the exact shell command Start builds, with a stand-in for the CLI."""
    import time
    fake_cli = tmp_path / "fake_cli.sh"
    fake_cli.write_text("sleep 0.5\n", encoding="utf-8")   # stands in for main.py
    rows = run_lua(tmp_path, "clip.avi", "Start",
                   VLC_AUTODUB_PYTHON="/bin/sh", VLC_AUTODUB_SCRIPT=str(fake_cli))
    command = next(r[1] for r in rows if r[0] == "EXEC")
    subprocess.run(["/bin/sh", "-c", command], check=True)
    pidfile, log = tmp_path / "clip.autodub.pid", tmp_path / "clip.autodub.log"
    deadline = time.time() + 5
    # The shell creates the file before it writes to it: wait for the content.
    fields: list[str] = []
    while len(fields) < 3 and time.time() < deadline:
        time.sleep(0.02)
        fields = pidfile.read_text().split() if pidfile.exists() else []
    pid, where, mode = fields
    assert pid.isdigit() and (where, mode) == ("separate", "both")
    while "AUTODUB_EXIT=" not in (log.read_text() if log.exists() else "") \
            and time.time() < deadline:
        time.sleep(0.05)
    assert "AUTODUB_EXIT=0" in log.read_text()
    assert not pidfile.exists()
