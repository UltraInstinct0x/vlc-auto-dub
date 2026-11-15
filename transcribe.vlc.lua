-- transcribe.vlc.lua -- VLC extension for vlc-auto-dub
--
-- Adds "Auto-Dub" to VLC's Extensions menu. It dubs and/or subtitles the
-- currently playing video with the local vlc-auto-dub CLI. By default the new
-- tracks are added inside the video file itself (every original track is
-- kept); untick "Add tracks into this file" to write "<base>_dubbed<ext>" and
-- "<base>.srt" beside it instead.
--
-- Paths are configurable; there is NO hardcoded placeholder path here.
-- Configure once in ~/.config/vlc-auto-dub/config.lua:
--
--     return {
--       python = "/usr/bin/python3",           -- interpreter
--       script = "/opt/vlc-auto-dub/main.py",  -- absolute path to main.py
--     }
--
-- or set VLC_AUTODUB_PYTHON / VLC_AUTODUB_SCRIPT (and optionally
-- VLC_AUTODUB_CONFIG) environment variables before starting VLC.

function descriptor()
    return {
        title = "Auto-Dub (vlc-auto-dub)",
        version = "3.0.2",
        author = "vlc-auto-dub",
        shortdesc = "Dub and/or subtitle the current video",
        capabilities = { "menu" }
    }
end

-- Languages offered in the dialog: { code, label }.
local LANGUAGES = {
    { "en", "English" }, { "tr", "Turkish" }, { "de", "German" },
    { "fr", "French" }, { "es", "Spanish" }, { "it", "Italian" },
    { "pt", "Portuguese" }, { "ru", "Russian" }, { "nl", "Dutch" },
    { "pl", "Polish" }, { "ar", "Arabic" }, { "ja", "Japanese" },
    { "ko", "Korean" }, { "zh", "Chinese" }, { "hi", "Hindi" },
    { "uk", "Ukrainian" },
}

local MODES = {
    { "both", "Dub + subtitles" },
    { "dub", "Dub only" },
    { "subs", "Subtitles only" },
}

-- Formats --in-place can rewrite (must match autodub/media.py).
local IN_PLACE_EXTENSIONS = { mp4 = true, m4v = true, mov = true, mkv = true }

local dlg = nil
local job = nil  -- { video, uri, log, in_place } of the last started run

-- POSIX single-quote shell escaping: safe for spaces, quotes and $ in paths.
local function shquote(value)
    return "'" .. tostring(value):gsub("'", "'\\''") .. "'"
end

local function load_config()
    local path = os.getenv("VLC_AUTODUB_CONFIG")
        or ((os.getenv("HOME") or "") .. "/.config/vlc-auto-dub/config.lua")
    local ok, cfg = pcall(dofile, path)
    if ok and type(cfg) == "table" then
        return cfg
    end
    return {}
end

local function strip_extension(path)
    return (path:gsub("%.[^%./]+$", ""))
end

local function extension_of(path)
    return (path:match("%.([^%./]+)$") or ""):lower()
end

local function current_item()
    local item = vlc.input.item()
    if not item then
        return nil, nil
    end
    local uri = item:uri()
    local path = vlc.strings.decode_uri(uri):gsub("^file://", "")
    return path, uri
end

-- Build the CLI argument list (everything after "<python> <script>").
-- Mirrored by tests/test_vlc_invocation.py; keep the two in sync.
function build_args(video, source, target, mode, in_place, sound_tags)
    local args = { video }
    if in_place then
        table.insert(args, "--in-place")
    else
        table.insert(args, "--output-base")
        table.insert(args, strip_extension(video))
    end
    if source ~= "auto" then
        table.insert(args, "--source-lang")
        table.insert(args, source)
    end
    if target ~= "same" then
        table.insert(args, "--target-lang")
        table.insert(args, target)
    end
    if mode == "dub" then
        table.insert(args, "--dub-only")
    elseif mode == "subs" then
        table.insert(args, "--subtitle-only")
    end
    if sound_tags == false and mode ~= "dub" then
        table.insert(args, "--no-sound-tags")
    end
    return args
end

local function read_file(path)
    local fh = io.open(path, "r")
    if not fh then
        return nil
    end
    local text = fh:read("*a")
    fh:close()
    return text
end

local function close_dialog()
    if dlg then
        dlg:delete()
        dlg = nil
    end
end

local function job_for(video, uri, in_place, mode)
    local base = strip_extension(video)
    return {
        video = video, uri = uri, in_place = in_place, mode = mode,
        log = base .. ".autodub.log", pidfile = base .. ".autodub.pid",
        -- Where the CLI writes without --in-place (must match autodub/pipeline.py:
        -- <base>_dubbed<ext>, <base>_dubbed.wav for audio-only input, <base>.srt).
        dubbed = base .. "_dubbed" .. (video:match("(%.[^%./]+)$") or ".mp4"),
        dubbed_audio = base .. "_dubbed.wav",
        srt = base .. ".srt",
    }
end

local function file_exists(path)
    local fh = io.open(path, "r")
    if fh then
        fh:close()
        return true
    end
    return false
end

local function to_uri(path)
    if vlc and vlc.strings and vlc.strings.make_uri then
        return vlc.strings.make_uri(path)
    end
    return "file://" .. path
end

-- What "Reopen video" should play: the MRL and extra item options.
-- In place, the original file now holds the new tracks. Otherwise the dub is
-- a separate copy beside it, and its subtitles have a different base name, so
-- VLC would not pick them up by itself.
function reopen_target(j, exists)
    exists = exists or file_exists
    if j.in_place then
        return j.uri, {}
    end
    local options = {}
    if j.mode ~= "dub" and exists(j.srt) then
        table.insert(options, "sub-file=" .. j.srt)
    end
    if j.mode ~= "subs" then
        for _, candidate in ipairs({ j.dubbed, j.dubbed_audio }) do
            if exists(candidate) then
                return to_uri(candidate), options
            end
        end
    end
    return j.uri, options  -- subtitles only: the original plus the new .srt
end

local function shell_ok(cmd)
    local r = os.execute(cmd)
    return r == 0 or r == true  -- Lua 5.1 returns 0, Lua 5.2+ returns true
end

-- PID of the running job for this video, or nil if none is running.
local function running_pid(j)
    local text = read_file(j.pidfile)
    local pid = text and text:match("(%d+)")
    if pid and shell_ok("kill -0 " .. pid .. " 2>/dev/null") then
        return pid
    end
    return nil
end

local function last_line(text)
    local last = ""
    for line in text:gmatch("[^\r\n]+") do
        last = line
    end
    return last
end

local function show_status_dialog(message)
    close_dialog()
    dlg = vlc.dialog("Auto-Dub")
    local status = dlg:add_label(message, 1, 1, 4, 1)
    local stop_presses = 0

    dlg:add_button("Check status", function()
        local text = read_file(job.log) or ""
        local code = text:match("AUTODUB_EXIT=(%d+)")
        if code == "0" then
            if job.in_place then
                status:set_text("Done. Click 'Reopen video' to load the new tracks.")
            elseif job.mode == "subs" then
                status:set_text("Done. 'Reopen video' loads the new subtitles.")
            else
                status:set_text("Done. 'Reopen video' plays the dubbed copy.")
            end
        elseif code == "143" or code == "137" then
            status:set_text("Stopped. The original file was not changed.")
        elseif code then
            local err = text:match("error: ([^\n]+)") or ("exit code " .. code)
            status:set_text("Failed: " .. err .. " (log: " .. job.log .. ")")
        elseif running_pid(job) then
            status:set_text("Working... " .. last_line(text))
        else
            status:set_text("Not running. Log: " .. job.log)
        end
        dlg:update()
    end, 1, 2, 1, 1)

    dlg:add_button("Stop job", function()
        local pid = running_pid(job)
        if not pid then
            status:set_text("No job is running for this video.")
        elseif stop_presses == 0 then
            -- SIGTERM: the CLI stops at the next safe point and removes temp files.
            os.execute("kill -TERM " .. pid)
            stop_presses = 1
            status:set_text("Stopping... (press again to force)")
        else
            os.execute("kill -KILL " .. pid)
            status:set_text("Killed. The original file was not changed.")
        end
        dlg:update()
    end, 2, 2, 1, 1)

    dlg:add_button("Reopen video", function()
        -- Reload at the current position: the rewritten file (in place) or the
        -- dubbed copy with its subtitles (separate files).
        local seconds = 0
        local input = vlc.object.input()
        if input then
            local t = vlc.var.get(input, "time") or 0
            -- VLC 3 reports microseconds; older builds reported seconds.
            seconds = (t > 100000) and math.floor(t / 1000000) or math.floor(t)
        end
        local current = vlc.playlist.current()
        local path, options = reopen_target(job)
        table.insert(options, "start-time=" .. seconds)
        vlc.playlist.add({ { path = path, options = options } })
        if current then
            vlc.playlist.delete(current)
        end
        close_dialog()
    end, 3, 2, 1, 1)

    dlg:add_button("Close", close_dialog, 4, 2, 1, 1)
    dlg:show()
end

local function start_job(video, uri, python, script, source, target, mode, in_place, sound_tags)
    local j = job_for(video, uri, in_place, mode)
    if running_pid(j) then
        job = j
        show_status_dialog("A job is already running for this video.")
        return
    end
    local parts = { shquote(python), shquote(script) }
    for _, arg in ipairs(build_args(video, source, target, mode, in_place, sound_tags)) do
        table.insert(parts, shquote(arg))
    end
    -- Run in the background so VLC's UI thread is not blocked. The PID is kept
    -- in a file so the job can be found and stopped even after VLC restarts;
    -- the exit code is appended to the log for the status button.
    -- The pidfile also records where the output goes ("<pid> in-place|separate
    -- <mode>") so a reopened dialog can still find the dub.
    local where = in_place and "in-place" or "separate"
    local cmd = "( " .. table.concat(parts, " ") .. " & echo $! " .. where .. " " .. mode
        .. " > " .. shquote(j.pidfile)
        .. "; wait $!; code=$?; rm -f " .. shquote(j.pidfile)
        .. "; echo \"AUTODUB_EXIT=$code\" ) > " .. shquote(j.log) .. " 2>&1 &"
    vlc.msg.info("vlc-auto-dub: " .. cmd)
    os.execute(cmd)
    job = j
    show_status_dialog("Started. This can take a while; you can keep watching.")
end

local function show_settings_dialog(video, uri, python, script)
    close_dialog()
    dlg = vlc.dialog("Auto-Dub settings")

    -- Layout for VLC's macOS dialog (modules/gui/macosx/VLCUIWidgets.m), which
    -- starts the window at 1x1 and grows it to the grid's minimum size:
    --  * a column is as wide as its widest single-cell dropdown/label/button,
    --    but one single-cell check box (a width-sizable widget) or no
    --    single-cell widget at all makes it count as only 128 pt;
    --  * dropdowns are drawn at their natural width whatever the column;
    --  * widgets spanning columns are left out of the column widths, and check
    --    boxes are stretched across the columns they span;
    --  * a row without a single-row widget gets 128 pt of height.
    -- So: labels in column 1, dropdowns as single cells in column 2 (setting
    -- its width), check boxes spanning both columns, and no empty rows.
    local row = 0
    local function next_row()
        row = row + 1
        return row
    end
    local function dropdown(label)
        local r = next_row()
        dlg:add_label(label, 1, r, 1, 1)
        return dlg:add_dropdown(2, r, 1, 1)
    end

    local source_dd = dropdown("Spoken language:")
    local sources = { "auto" }
    source_dd:add_value("Auto-detect", 1)
    for i, lang in ipairs(LANGUAGES) do
        table.insert(sources, lang[1])
        source_dd:add_value(lang[2] .. " (" .. lang[1] .. ")", i + 1)
    end

    local target_dd = dropdown("Translate to:")
    local targets = {}
    for i, lang in ipairs(LANGUAGES) do
        table.insert(targets, lang[1])
        target_dd:add_value(lang[2] .. " (" .. lang[1] .. ")", i)
    end
    table.insert(targets, "same")
    target_dd:add_value("No translation", #targets)

    local mode_dd = dropdown("Produce:")
    for i, m in ipairs(MODES) do
        mode_dd:add_value(m[2], i)
    end

    local can_in_place = IN_PLACE_EXTENSIONS[extension_of(video)] == true
    local in_place_cb = dlg:add_check_box("Add tracks into this file", can_in_place,
        1, next_row(), 2, 1)
    if not can_in_place then
        dlg:add_label("(needs .mp4, .m4v, .mov or .mkv)", 1, next_row(), 2, 1)
    end
    local tags_cb = dlg:add_check_box("Sound tags: [laughter], [music]...", true,
        1, next_row(), 2, 1)

    local r = next_row()
    dlg:add_button("Start", function()
        local source = sources[source_dd:get_value()] or "auto"
        local target = targets[target_dd:get_value()] or "same"
        local mode = (MODES[mode_dd:get_value()] or MODES[1])[1]
        local in_place = can_in_place and in_place_cb:get_checked()
        start_job(video, uri, python, script, source, target, mode, in_place,
            tags_cb:get_checked())
    end, 1, r, 1, 1)
    dlg:add_button("Cancel", close_dialog, 2, r, 1, 1)
    dlg:show()
end

function activate()
    local video, uri = current_item()
    if not video then
        vlc.msg.err("vlc-auto-dub: no media item is loaded")
        return
    end

    local cfg = load_config()
    local python = os.getenv("VLC_AUTODUB_PYTHON") or cfg.python or "python3"
    local script = os.getenv("VLC_AUTODUB_SCRIPT") or cfg.script
    if not script or script == "" then
        vlc.msg.err("vlc-auto-dub: set 'script' in ~/.config/vlc-auto-dub/config.lua "
            .. "or the VLC_AUTODUB_SCRIPT environment variable")
        return
    end

    local j = job_for(video, uri, true)
    if running_pid(j) then
        local where, mode = (read_file(j.pidfile) or ""):match("%d+%s+(%S+)%s+(%S+)")
        if where then
            j = job_for(video, uri, where == "in-place", mode)
        end
        job = j
        show_status_dialog("A job is running for this video.")
        return
    end
    show_settings_dialog(video, uri, python, script)
end

function deactivate()
    close_dialog()
end

function close()
    vlc.deactivate()
end

function meta_changed()
end
