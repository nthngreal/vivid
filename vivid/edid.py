"""Human-readable monitor names from the kernel's EDID blobs."""
import glob


def _parse(blob):
    if len(blob) < 128 or blob[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    name = None
    for off in (54, 72, 90, 108):
        d = blob[off:off + 18]
        if d[0:3] == b"\x00\x00\x00" and d[3] == 0xFC:    # display product name
            name = d[5:18].split(b"\x0a")[0].decode("ascii", "replace").strip()
            break
    if name:
        return name
    v = (blob[8] << 8) | blob[9]                          # PNP manufacturer id
    vendor = "".join(chr(((v >> s) & 0x1F) + 64) for s in (10, 5, 0))
    return f"{vendor} {blob[11] << 8 | blob[10]:04X}"


def monitor_name(output):
    """Name for a KWin output such as "DP-2" (sysfs: /sys/class/drm/card1-DP-2)."""
    for path in glob.glob(f"/sys/class/drm/card*-{output}/edid"):
        try:
            with open(path, "rb") as f:
                name = _parse(f.read())
        except OSError:
            continue
        if name:
            return name
    return None
