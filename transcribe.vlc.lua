-- transcribe.vlc.lua -- VLC extension for vlc-auto-dub
--
-- Adds a menu item that dubs the currently playing video with the local
-- vlc-auto-dub CLI and writes "<base>.srt" and "<base>_dubbed<ext>" beside it.
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
        version = "2.0",
        author = "vlc-auto-dub",
        shortdesc = "Transcribe and dub the current video",
        capabilities = { "input-listener", "menu" }
    }
end

local dlg = nil

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

local function current_video_path()
    local item = vlc.input.item()
    if not item then
        return nil
    end
    local path = vlc.strings.decode_uri(item:uri())
    path = path:gsub("^file://", "")
    return path
end

function activate()
    local video = current_video_path()
    if not video then
        vlc.msg.err("vlc-auto-dub: no media item is loaded")
        return
    end

    local base = strip_extension(video)
    local srt = base .. ".srt"
    local handle = io.open(srt, "r")
    if handle then
        handle:close()
        vlc.msg.info("vlc-auto-dub: subtitles already exist for this video: " .. srt)
    end

    local cfg = load_config()
    local python = os.getenv("VLC_AUTODUB_PYTHON") or cfg.python or "python3"
    local script = os.getenv("VLC_AUTODUB_SCRIPT") or cfg.script
    if not script or script == "" then
        vlc.msg.err("vlc-auto-dub: set 'script' in ~/.config/vlc-auto-dub/config.lua "
            .. "or the VLC_AUTODUB_SCRIPT environment variable")
        return
    end

    show_language_prompt(video, base, python, script)
end

function deactivate()
    if dlg then
        dlg:delete()
        dlg = nil
    end
end

function meta_changed()
end

function show_language_prompt(video, base, python, script)
    dlg = vlc.dialog("Auto-Dub settings")
    dlg:add_label("Target language code (e.g. en, tr, de):", 1, 1, 2, 1)
    local lang_input = dlg:add_text_input("en", 2, 1, 2, 1)

    dlg:add_button("Dub now", function()
        local target = lang_input:get_text()
        if target == nil or target == "" then
            target = "en"
        end
        dlg:delete()
        dlg = nil

        -- Fire and forget: run in the background so VLC's UI thread is not
        -- blocked while ffmpeg/whisper/piper work. Progress goes to the log.
        local log = base .. ".autodub.log"
        local cmd = table.concat({
            shquote(python), shquote(script), shquote(video),
            "--output-base", shquote(base),
            "--target-lang", shquote(target),
            ">", shquote(log), "2>&1 &",
        }, " ")
        vlc.msg.info("vlc-auto-dub: " .. cmd)
        os.execute(cmd)
        vlc.msg.info("vlc-auto-dub: started; results will appear as " .. base .. ".srt")
    end, 1, 3, 1, 1)

    dlg:add_button("Cancel", function()
        dlg:delete()
        dlg = nil
    end, 2, 3, 1, 1)
end
