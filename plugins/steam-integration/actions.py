"""Steam integration - adds actions for launching/installing/verifying
games, Big Picture Mode, Friends, Downloads, Screenshots, Settings, and
a clean restart of the Steam client, all via Steam's own steam:// URI
scheme (the same mechanism desktop shortcuts and the Steam overlay use)
plus its "-shutdown" CLI flag.

Needs the `steam` launcher script on PATH (it's what every distro
package/Flatpak wrapper installs). Handing `steam` a steam://... URI is
the standard way to script Steam - if the client is already running,
the command is forwarded to it and this process exits almost
immediately, so every action here uses run_background rather than
run_command so a slow-to-respond client can never hang a shortcut.

Installed-game detection: actions that only make sense on a game you
already have (Launch, Uninstall, Verify, Store Page) show a dropdown
built by scanning Steam's own library files - no Steam Web API key or
network call needed:
  1. every known Steam install root (native, ~/.steam, Flatpak)
  2. that root's steamapps/libraryfolders.vdf, for every library folder
     the user has added (secondary drives, etc.)
  3. each library's steamapps/appmanifest_*.acf files, one per
     installed game, which is where the appid and display name live
The dropdown is a zero-arg callable, so it's re-scanned fresh every
time the field is drawn - install or uninstall something and the list
is right the next time you open the step. Install itself stays a
plain text App ID field on purpose: it's for a game that, by
definition, isn't in the installed-games list yet.
"""
import glob
import os
import re

import plugin_api as api

_PATH_RE = re.compile(r'"path"\s*"([^"]+)"')
_APPID_RE = re.compile(r'"appid"\s*"(\d+)"', re.IGNORECASE)
_NAME_RE = re.compile(r'"name"\s*"([^"]*)"')


def _steam_bin():
    if api.command_available("steam"):
        return "steam"
    raise RuntimeError(
        "\u201csteam\u201d wasn't found on PATH. Install it from your distro's "
        "package manager, Flatpak (com.valvesoftware.Steam), or Snap."
    )


def _steam_uri(uri):
    api.run_background([_steam_bin(), uri])


def _steam_roots():
    """Every plausible Steam install root for this user, deduplicated
    after resolving symlinks (~/.steam/steam is usually one)."""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".local", "share", "Steam"),
        os.path.join(home, ".steam", "steam"),
        os.path.join(home, ".steam", "root"),
        os.path.join(home, ".var", "app", "com.valvesoftware.Steam",
                      ".local", "share", "Steam"),
    ]
    seen, roots = set(), []
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if os.path.isdir(real) and real not in seen:
            seen.add(real)
            roots.append(real)
    return roots


def _library_paths(steam_root):
    """Every library folder registered under one Steam install,
    including the root itself. libraryfolders.vdf's relevant lines are
    flat "path" "..." entries, so a regex is enough - no need to pull
    in a full VDF parser for this."""
    libraries = {steam_root}
    vdf_path = os.path.join(steam_root, "steamapps", "libraryfolders.vdf")
    try:
        with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
    except OSError:
        return libraries
    for path in _PATH_RE.findall(content):
        libraries.add(os.path.normpath(path.replace("\\\\", "\\")))
    return libraries


def _installed_games():
    """[(app_id, "Name (app_id)"), ...] sorted by name, for an App ID
    dropdown's `choices`. Called fresh every time the field is drawn -
    see the module docstring."""
    games = {}
    for root in _steam_roots():
        for library in _library_paths(root):
            pattern = os.path.join(library, "steamapps", "appmanifest_*.acf")
            for manifest_path in glob.glob(pattern):
                try:
                    with open(manifest_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                except OSError:
                    continue
                appid_match = _APPID_RE.search(content)
                name_match = _NAME_RE.search(content)
                if appid_match and name_match:
                    games[appid_match.group(1)] = name_match.group(1)

    if not games:
        return [("", "No installed games found")]
    return [
        (appid, f"{name} ({appid})")
        for appid, name in sorted(games.items(), key=lambda kv: kv[1].lower())
    ]


def _app_id(params):
    raw = str(params.get("app_id") or "").strip()
    if not raw.isdigit():
        raise RuntimeError(
            "No game selected - pick one from the dropdown, or Steam "
            "hasn't finished installing/scanning it yet."
        )
    return raw


def _launch_game(params, ctx):
    _steam_uri(f"steam://rungameid/{_app_id(params)}")


def _install_game(params, ctx):
    _steam_uri(f"steam://install/{_app_id(params)}")


def _uninstall_game(params, ctx):
    _steam_uri(f"steam://uninstall/{_app_id(params)}")


def _verify_game_files(params, ctx):
    _steam_uri(f"steam://validate/{_app_id(params)}")


def _open_store_page(params, ctx):
    _steam_uri(f"steam://store/{_app_id(params)}")


def _open_big_picture(params, ctx):
    _steam_uri("steam://open/bigpicture")


def _exit_big_picture(params, ctx):
    # Undocumented but long-standing; toggles Big Picture off the same
    # way the in-overlay "Exit Big Picture Mode" button does.
    _steam_uri("steam://exitbigpicture")


def _open_friends(params, ctx):
    _steam_uri("steam://open/friends")


def _open_downloads(params, ctx):
    _steam_uri("steam://open/downloads")


def _open_screenshots(params, ctx):
    _steam_uri("steam://open/screenshots")


def _open_settings(params, ctx):
    _steam_uri("steam://open/settings")


def _restart_steam(params, ctx):
    # "-shutdown" is Steam's own documented flag for a clean client
    # exit (flushes config, unlike killing the process) - give it a
    # little time to finish, then start a fresh client.
    steam = _steam_bin()
    try:
        api.run_command([steam, "-shutdown"], timeout=20)
    except RuntimeError:
        pass  # a non-zero exit here is normal if Steam wasn't running
    api.run_background([steam])


ACTIONS = [
    api.action(
        id="launch_game", name="Launch Game", run=_launch_game,
        icon="media-playback-start-symbolic", color="tile-blue", required_command="steam",
        params=[api.param("app_id", "Game", "choice", "", choices=_installed_games)],
    ),
    api.action(
        id="install_game", name="Install Game", run=_install_game,
        icon="system-software-install-symbolic", color="tile-teal", required_command="steam",
        params=[api.param("app_id", "App ID", "text", "", placeholder="570")],
    ),
    api.action(
        id="uninstall_game", name="Uninstall Game", run=_uninstall_game,
        icon="user-trash-symbolic", color="tile-red", required_command="steam",
        params=[api.param("app_id", "Game", "choice", "", choices=_installed_games)],
    ),
    api.action(
        id="verify_game_files", name="Verify Game Files", run=_verify_game_files,
        icon="checkbox-checked-symbolic", color="tile-teal", required_command="steam",
        params=[api.param("app_id", "Game", "choice", "", choices=_installed_games)],
    ),
    api.action(
        id="open_store_page", name="Open Store Page", run=_open_store_page,
        icon="web-browser-symbolic", color="tile-gray", required_command="steam",
        params=[api.param("app_id", "Game", "choice", "", choices=_installed_games)],
    ),
    api.action(
        id="open_big_picture", name="Open Big Picture Mode", run=_open_big_picture,
        icon="video-display-symbolic", color="tile-purple", required_command="steam",
    ),
    api.action(
        id="exit_big_picture", name="Exit Big Picture Mode", run=_exit_big_picture,
        icon="window-restore-symbolic", color="tile-purple", required_command="steam",
    ),
    api.action(
        id="open_friends", name="Open Friends List", run=_open_friends,
        icon="system-users-symbolic", color="tile-blue", required_command="steam",
    ),
    api.action(
        id="open_downloads", name="Open Downloads", run=_open_downloads,
        icon="folder-download-symbolic", color="tile-orange", required_command="steam",
    ),
    api.action(
        id="open_screenshots", name="Open Screenshots", run=_open_screenshots,
        icon="camera-photo-symbolic", color="tile-yellow", required_command="steam",
    ),
    api.action(
        id="open_settings", name="Open Steam Settings", run=_open_settings,
        icon="preferences-system-symbolic", color="tile-gray", required_command="steam",
    ),
    api.action(
        id="restart_steam", name="Restart Steam", run=_restart_steam,
        icon="view-refresh-symbolic", color="tile-red", required_command="steam",
    ),
]
