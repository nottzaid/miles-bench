"""Bench the game on the user's own "gaming" workspace without ever moving the user's view or focus.

The game opens where the user's config sends it, the named workspace "gaming", so Super+G shows it
whenever the user wants to watch. For the length of one run a runtime window rule (added after the
config's, so it wins) makes that placement silent (no jump to "gaming" when the window opens),
ignores the game's requests to be focused or activated, and keeps the game rendering at 60 Hz while
"gaming" isn't on screen. Going to "gaming" and back stays entirely up to the user. Keys go to the game from inside
its own process (VKD3D_BENCH_INPUT, libs/vkd3d/benchinput.c), so it never needs focus, and
screenshots capture the game window itself, visible or not. teardown() switches the rule off again.

    python3 bench/hyprbench.py setup          # rule on (silent placement, render while hidden)
    python3 bench/hyprbench.py input enter    # key to the game's launcher/menus, no focus needed
    python3 bench/hyprbench.py shot out.png   # 960-px-wide screenshot of the game window
    python3 bench/hyprbench.py menu out.png   # exit 0 if the screenshot shows the main menu
    python3 bench/hyprbench.py hud out.png    # exit 0 if the screenshot shows gameplay (HUD)
    python3 bench/hyprbench.py where          # monitor and size of the game window
    python3 bench/hyprbench.py events FILE    # log Hyprland's event stream until killed
    python3 bench/hyprbench.py teardown       # rule off, render_unfocused_fps as it was
"""
import os
import socket
import json
import pathlib
import subprocess
import sys
import time

GAME_CLASS = "steam_app"
GAME_EXE = "MilesMorales.ex"  # comm is cut to 15 characters
# Rendering a hidden window: Hyprland sends it frame callbacks at this rate, the bench's old
# 60 Hz headless output and the user's monitor alike.
HIDDEN_FPS = 60
STATE = pathlib.Path("/run/user/1000/hyprbench.state")

# The rule also matches on content (".*" matches any content type, "none" included). Hyprland
# re-applies only content-matching rules once a rule has set a window's content type, and the
# user's config sets content=game on the titled game window and then sends content=game windows to
# "gaming" non-silently (Window.cpp:2277, WindowRuleApplicator.cpp:525): a class-only rule loses
# that second pass and the view jumps to "gaming" (seen 2026-10-12, reproduced with a test window).
# no_initial_focus would also stop the jump but skips the initial fullscreen setup.
RULE_ON = f"""
if MILES_BENCH_RULE then MILES_BENCH_RULE:set_enabled(false) end
if MILES_BENCH_GAME_RULE then MILES_BENCH_GAME_RULE:set_enabled(true) else
    MILES_BENCH_GAME_RULE = hl.window_rule({{ name = "miles-bench-game",
        match = {{ class = "^({GAME_CLASS}.*)$", content = ".*" }},
        workspace = "name:gaming silent", render_unfocused = true,
        focus_on_activate = false, suppress_event = "activate activatefocus" }})
end
hl.config({{ misc = {{ render_unfocused_fps = {HIDDEN_FPS} }} }})
"""
RULE_OFF = """
if MILES_BENCH_RULE then MILES_BENCH_RULE:set_enabled(false) end
if MILES_BENCH_GAME_RULE then MILES_BENCH_GAME_RULE:set_enabled(false) end
"""


def hypr(*args):
    return subprocess.run(["hyprctl", *args], capture_output=True, text=True).stdout


def hypr_json(what):
    return json.loads(hypr("-j", what) or "null")


def game_client():
    for c in hypr_json("clients"):
        if c["class"].startswith(GAME_CLASS) and c["title"]:
            return c
    return None


def setup():
    if not STATE.exists():
        fps = hypr("getoption", "misc:render_unfocused_fps").split()[1]
        STATE.write_text(json.dumps({"render_unfocused_fps": int(fps)}))
    hypr("eval", RULE_ON)
    print("rule on: game windows go silently to name:gaming and render while hidden")


def teardown():
    hypr("eval", RULE_OFF)
    if STATE.exists():
        fps = json.loads(STATE.read_text())["render_unfocused_fps"]
        hypr("eval", f"hl.config({{ misc = {{ render_unfocused_fps = {fps} }} }})")
        STATE.unlink()
    print("rule off")


def game_root():
    pid = subprocess.run(["pgrep", "-x", GAME_EXE], capture_output=True, text=True).stdout.split()
    if not pid:
        sys.exit("game not running")
    return pathlib.Path(f"/proc/{pid[0]}/root/run/user/1000")


def send(key):
    """Hand a key to benchinput.c inside the game and wait for its answer."""
    root = game_root()
    done = root / "vkd3d-input.done"
    done.unlink(missing_ok=True)
    (root / "vkd3d-input").write_text(key + "\n")
    wait = 3 + (int(key.split()[1]) / 1000 if key.startswith("hold ") else 0)  # "hold <ms> <keys>"
    for _ in range(int(wait * 10)):
        time.sleep(0.1)
        if done.exists():
            answer = done.read_text().strip()
            print(answer)
            sys.exit(1 if answer.startswith(("none", "unknown")) else 0)
    sys.exit("no answer from the game (VKD3D_BENCH_INPUT not set?)")


def shot(path):
    c = game_client()
    if not c:
        sys.exit("no game window")
    scale = 960 / max(c["size"][0], 1)
    subprocess.run(["grim", "-T", c["stableId"], "-s", f"{scale:.4f}", path], check=True)


def where():
    c = game_client()
    if not c:
        sys.exit("no game window")
    mon = next(m for m in hypr_json("monitors") if m["id"] == c["monitor"])
    print(f"{c['workspace']['name']} on {mon['name']} {mon['width']}x{mon['height']}@{mon['refreshRate']:.0f}, "
          f"window {c['size'][0]}x{c['size'][1]}, visible {mon['activeWorkspace']['name'] == c['workspace']['name']}")


def events(path):
    """Timestamped Hyprland events (workspace, focus, window open/close, fullscreen, urgent), so a
    view change can be traced to the user's own keys or to something the game did."""
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    sock.connect(f"{os.environ['XDG_RUNTIME_DIR']}/hypr/{os.environ['HYPRLAND_INSTANCE_SIGNATURE']}/.socket2.sock")
    keep = ("workspace", "focusedmon", "activewindow>>", "openwindow", "closewindow", "fullscreen",
            "urgent", "movewindow", "activespecial")
    buf = b""
    with open(path, "a", buffering=1) as out:
        while chunk := sock.recv(4096):
            buf += chunk
            *lines, buf = buf.split(b"\n")
            for line in lines:
                text = line.decode(errors="replace")
                if text.startswith(keep):
                    out.write(f"{time.strftime('%T')}.{int(time.time() * 1000) % 1000:03d}\t{text}\n")


def is_hud(path):
    """In gameplay: the HUD's web-shooter bar (top right) is white. Identical pixels in every
    checkpoint seen; cinematics and menus have at most ~30 white pixels there, gameplay 250+."""
    from PIL import Image
    px = Image.open(path).convert("RGB").load()
    return sum(all(c > 200 for c in px[x, y]) for y in range(22, 32) for x in range(740, 940)) >= 250


def is_menu(path):
    """Main menu: the highlighted CONTINUE row is a saturated red bar (half-scale coordinates)."""
    from PIL import Image
    im = Image.open(path).convert("RGB").crop((150, 74, 300, 88))
    px = im.get_flattened_data() if hasattr(im, "get_flattened_data") else im.getdata()
    px = list(px)
    r, g, b = (sum(p[k] for p in px) / len(px) for k in range(3))
    return r > 140 and g < 90 and b < 110


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        setup()
    elif cmd == "teardown":
        teardown()
    elif cmd == "input":
        send(" ".join(sys.argv[2:]))
    elif cmd == "shot":
        shot(sys.argv[2])
    elif cmd == "events":
        events(sys.argv[2])
    elif cmd == "where":
        where()
    elif cmd == "menu":
        sys.exit(0 if is_menu(sys.argv[2]) else 1)
    elif cmd == "hud":
        sys.exit(0 if is_hud(sys.argv[2]) else 1)
    else:
        sys.exit(__doc__)
