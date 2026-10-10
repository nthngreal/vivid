"""Menu entry for the AppImage: written on every launch so it follows the file if it moves."""
import os
import shutil

ASSETS = os.path.join(os.path.dirname(__file__), "assets")
ICON = os.path.join(ASSETS, "vivid.svg")
DATA = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
DESKTOP_FILE = os.path.join(DATA, "applications", "vivid.desktop")
ICON_FILE = os.path.join(DATA, "icons", "hicolor", "scalable", "apps", "vivid.svg")

ENTRY = """[Desktop Entry]
Type=Application
Name=Vivid
Comment=Color saturation per monitor
Comment[uk]=Насиченість кольору для кожного монітора
Exec="{exe}"
Icon=vivid
Categories=Settings;HardwareSettings;
Keywords=saturation;vibrance;color;monitor;
Terminal=false
"""


def install_menu_entry():
    exe = os.environ.get("APPIMAGE")
    if not exe:
        return  # running from source: nothing to point the entry at
    try:
        os.makedirs(os.path.dirname(DESKTOP_FILE), exist_ok=True)
        os.makedirs(os.path.dirname(ICON_FILE), exist_ok=True)
        shutil.copyfile(ICON, ICON_FILE)
        text = ENTRY.format(exe=exe)
        if not os.path.exists(DESKTOP_FILE) or open(DESKTOP_FILE).read() != text:
            with open(DESKTOP_FILE, "w") as f:
                f.write(text)
    except OSError:
        pass
