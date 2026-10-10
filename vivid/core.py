"""Profile generation and kscreen-doctor control. No GUI imports here.

The ICC math is taken from plasma-vibrance by Matias Celiz (MIT):
https://github.com/Celiz/plasma-vibrance

The generated profile is ICC v2 with a lut16 B2A tag: XYZ->linear sRGB matrix,
1D curves that encode to gamma 2.2, a CLUT that applies the saturation matrix in
gamma space (chroma * s around BT.709 Y', like AMD/NVIDIA output CSC) and 1D
output curves that clip. The CLUT holds a linear function only, so KWin's
trilinear interpolation reproduces it exactly.
"""
import ctypes
import glob
import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from . import edid

ICC_DIR = os.path.expanduser("~/.local/share/color/icc")
MAX_PCT = 100  # slider 0..100  ->  saturation x1.0 .. x2.0


class VibranceError(Exception):
    """Error with a message key the GUI can translate."""

    def __init__(self, key, detail=""):
        super().__init__(f"{key}: {detail}" if detail else key)
        self.key, self.detail = key, detail


# ---------------------------------------------------------------- ICC ----
def _matmul(A, B):
    return [[sum(A[i][k] * B[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def _inv(m):
    a, b, c = m[0]; d, e, f = m[1]; g, h, i = m[2]
    det = a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)
    return [[(e * i - f * h) / det, (c * h - b * i) / det, (b * f - c * e) / det],
            [(f * g - d * i) / det, (a * i - c * g) / det, (c * d - a * f) / det],
            [(d * h - e * g) / det, (b * g - a * h) / det, (a * e - b * d) / det]]


M_SRGB = [[0.4124564, 0.3575761, 0.1804375],          # linear sRGB -> XYZ (D65)
          [0.2126729, 0.7151522, 0.0721750],
          [0.0193339, 0.1191920, 0.9503041]]
XYZ_TO_SRGB = _inv(M_SRGB)
BRADFORD_D50_TO_D65 = [[ 0.9555766, -0.0230393,  0.0631636],
                       [-0.0282895,  1.0099416,  0.0210077],
                       [ 0.0122982, -0.0204830,  1.3299098]]
PCS_TO_SRGB = _matmul(XYZ_TO_SRGB, BRADFORD_D50_TO_D65)   # XYZ D50 (PCS) -> linear sRGB
W = (0.2126, 0.7152, 0.0722)                              # BT.709 luma
GAMMA = 2.2
D65 = (0.3127, 0.3290)
SRGB_PRIMS = ((0.64, 0.33), (0.30, 0.60), (0.15, 0.06))
# KWin scales XYZ like this before it enters the B2A tag. This mirrors KWin
# internals, not a public API: if KWin changes it, colors shift silently.
KWIN_XYZ_MULT = 65536 / (2 * 65535)
CLUT_OFF, CLUT_SPAN = 2.0, 5.0        # CLUT stores [-2, 3]: no clipping up to s = 3
CLUT_GRID = 17


class _xyY(ctypes.Structure):
    _fields_ = [("x", ctypes.c_double), ("y", ctypes.c_double), ("Y", ctypes.c_double)]


class _xyYTRIPLE(ctypes.Structure):
    _fields_ = [("Red", _xyY), ("Green", _xyY), ("Blue", _xyY)]


_lcms = None


def _lcms_lib():
    global _lcms
    if _lcms is None:
        vp, u16p, dp = ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(ctypes.c_double)
        try:
            L = ctypes.CDLL("liblcms2.so.2")
        except OSError as e:
            raise VibranceError("err_lcms", str(e))
        L.cmsBuildGamma.restype = vp;                L.cmsBuildGamma.argtypes = [vp, ctypes.c_double]
        L.cmsBuildTabulatedToneCurve16.restype = vp; L.cmsBuildTabulatedToneCurve16.argtypes = [vp, ctypes.c_uint, u16p]
        L.cmsCreateRGBProfile.restype = vp;          L.cmsCreateRGBProfile.argtypes = [ctypes.POINTER(_xyY), ctypes.POINTER(_xyYTRIPLE), ctypes.POINTER(vp)]
        L.cmsSetProfileVersion.argtypes = [vp, ctypes.c_double]
        L.cmsPipelineAlloc.restype = vp;             L.cmsPipelineAlloc.argtypes = [vp, ctypes.c_uint, ctypes.c_uint]
        L.cmsPipelineInsertStage.argtypes = [vp, ctypes.c_int, vp]
        L.cmsPipelineFree.argtypes = [vp]
        L.cmsStageAllocMatrix.restype = vp;          L.cmsStageAllocMatrix.argtypes = [vp, ctypes.c_uint, ctypes.c_uint, dp, dp]
        L.cmsStageAllocToneCurves.restype = vp;      L.cmsStageAllocToneCurves.argtypes = [vp, ctypes.c_uint, ctypes.POINTER(vp)]
        L.cmsStageAllocCLut16bit.restype = vp;       L.cmsStageAllocCLut16bit.argtypes = [vp, ctypes.c_uint, ctypes.c_uint, ctypes.c_uint, u16p]
        L.cmsMLUalloc.restype = vp;                  L.cmsMLUalloc.argtypes = [vp, ctypes.c_uint]
        L.cmsMLUsetASCII.argtypes = [vp, ctypes.c_char_p, ctypes.c_char_p, ctypes.c_char_p]
        L.cmsWriteTag.argtypes = [vp, ctypes.c_uint, vp]
        L.cmsSaveProfileToFile.argtypes = [vp, ctypes.c_char_p]
        L.cmsCloseProfile.argtypes = [vp]
        _lcms = L
    return _lcms


def profile_path(output, pct):
    # Same naming as plasma-vibrance, so profiles it created are recognised.
    return os.path.join(ICC_DIR, f"vibrance-{output}-{pct}.icc")


def make_icc(output, pct):
    os.makedirs(ICC_DIR, exist_ok=True)
    L = _lcms_lib()
    vp = ctypes.c_void_p
    s = 1 + pct / 100
    path = profile_path(output, pct)

    white = _xyY(*D65, 1.0)
    trip = _xyYTRIPLE(*[_xyY(x, y, 1.0) for x, y in SRGB_PRIMS])
    g = L.cmsBuildGamma(None, GAMMA)
    h = L.cmsCreateRGBProfile(ctypes.byref(white), ctypes.byref(trip), (vp * 3)(g, g, g))
    L.cmsSetProfileVersion(h, 2.1)                # v2 -> B2A tag is written as lut16Type
    mlu = L.cmsMLUalloc(None, 1)
    L.cmsMLUsetASCII(mlu, b"en", b"US", f"Vibrance +{pct}% ({output})".encode())
    L.cmsWriteTag(h, 0x64657363, mlu)             # 'desc'

    pipe = L.cmsPipelineAlloc(None, 3, 3)
    AT_END = 1
    # 1) matrix: XYZ D50 (as KWin encodes it) -> linear sRGB
    m = (ctypes.c_double * 9)(*[PCS_TO_SRGB[i][j] / KWIN_XYZ_MULT for i in range(3) for j in range(3)])
    L.cmsPipelineInsertStage(pipe, AT_END, L.cmsStageAllocMatrix(None, 3, 3, m, None))
    # 2) input curves: encode to gamma (1D, exact; negatives clip to 0)
    enc = L.cmsBuildGamma(None, 1 / GAMMA)
    L.cmsPipelineInsertStage(pipe, AT_END, L.cmsStageAllocToneCurves(None, 3, (vp * 3)(enc, enc, enc)))
    # 3) CLUT: saturation in gamma space, stored with an offset so nothing clips
    n = CLUT_GRID
    tab = (ctypes.c_uint16 * (n * n * n * 3))()
    k = 0
    for i in range(n):
        for j in range(n):
            for l in range(n):
                r, gg, b = i / (n - 1), j / (n - 1), l / (n - 1)
                y = W[0] * r + W[1] * gg + W[2] * b
                for q, v in enumerate((y + s * (r - y), y + s * (gg - y), y + s * (b - y))):
                    tab[k + q] = int(min(1.0, max(0.0, (v + CLUT_OFF) / CLUT_SPAN)) * 65535 + 0.5)
                k += 3
    L.cmsPipelineInsertStage(pipe, AT_END, L.cmsStageAllocCLut16bit(None, n, 3, 3, tab))
    # 4) output curves: undo the offset and clip to [0, 1]
    N = 4096
    t = (ctypes.c_uint16 * N)(*[int(min(1.0, max(0.0, (i / (N - 1)) * CLUT_SPAN - CLUT_OFF)) * 65535 + 0.5) for i in range(N)])
    out = L.cmsBuildTabulatedToneCurve16(None, N, t)
    L.cmsPipelineInsertStage(pipe, AT_END, L.cmsStageAllocToneCurves(None, 3, (vp * 3)(out, out, out)))
    L.cmsWriteTag(h, 0x42324130, pipe)  # 'B2A0' (perceptual)
    L.cmsWriteTag(h, 0x42324131, pipe)  # 'B2A1' (relative colorimetric, the one KWin uses)
    L.cmsPipelineFree(pipe)
    L.cmsSaveProfileToFile(h, path.encode())
    L.cmsCloseProfile(h)
    return path


# ------------------------------------------------------- kscreen-doctor ----
@dataclass
class Output:
    name: str       # connector, e.g. DP-2; only used internally and as a hint
    label: str      # human name from EDID, e.g. "DELL U2419H"
    pct: int        # saved saturation, read back from KWin's profile path


def _kscreen_doctor():
    exe = shutil.which("kscreen-doctor")
    if not exe:
        raise VibranceError("err_no_kscreen")
    return exe


def check_session():
    if os.environ.get("XDG_SESSION_TYPE") != "wayland" and not os.environ.get("WAYLAND_DISPLAY"):
        raise VibranceError("err_not_wayland")
    _kscreen_doctor()


def list_outputs():
    try:
        raw = subprocess.check_output([_kscreen_doctor(), "-j"], stderr=subprocess.DEVNULL, timeout=10)
        data = json.loads(raw)
    except (subprocess.SubprocessError, ValueError) as e:
        raise VibranceError("err_list", str(e))
    res = []
    for o in data.get("outputs", []):
        if not (o.get("enabled") and o.get("connected")):
            continue
        name = o["name"]
        m = re.search(rf"vibrance-{re.escape(name)}-(\d+)(?:-linear)?\.icc$", o.get("iccProfilePath") or "")
        res.append(Output(name, edid.monitor_name(name) or name, int(m.group(1)) if m else 0))
    return res


def _cleanup(output, keep):
    # Exact match on "<output>-<digits>", so DP-2 never touches DP-2-1's profiles.
    pat = re.compile(rf"vibrance-{re.escape(output)}-\d+(?:-linear)?\.icc$")
    for f in glob.glob(os.path.join(ICC_DIR, "vibrance-*.icc")):
        base = os.path.basename(f)
        if pat.fullmatch(base) and base != keep:
            try:
                os.remove(f)
            except OSError:
                pass


def apply(output, pct):
    """Generate and enable the profile; KWin persists it across reboots."""
    pct = max(0, min(MAX_PCT, int(pct)))
    # KWin only runs the ICC shader (the one that applies the 3D table) with
    # "prefer accuracy"; with "prefer efficiency" it only offloads the profile's
    # 1D curve to KMS and the table is ignored (drm_output.cpp, m_needsShadowBuffer).
    if pct <= 0:
        path = None
        args = [f"output.{output}.colorProfileSource.sRGB",
                f"output.{output}.colorPowerTradeoff.preferEfficiency"]
    else:
        path = make_icc(output, pct)
        args = [f"output.{output}.iccprofile.{path}", f"output.{output}.colorProfileSource.ICC",
                f"output.{output}.colorPowerTradeoff.preferAccuracy"]
    r = subprocess.run([_kscreen_doctor(), *args], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        raise VibranceError("err_apply", (r.stderr or r.stdout).strip()[-300:])
    _cleanup(output, os.path.basename(path) if path else None)
