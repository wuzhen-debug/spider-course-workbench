"""Use one pinned SDK version for all backend XHS adapters."""
from pathlib import Path
import sys

SDK_REVISION = "23dab803a0465e35e01cf87137353a900b47e93d"
SDK_ROOT = Path(__file__).resolve().parents[4] / "vendor" / "spider_xhs_23dab803"
if not (SDK_ROOT / "SDK_SOURCE.json").is_file():
    raise RuntimeError("Pinned Spider_XHS SDK snapshot is missing")

# The upstream SDK uses absolute `apis` / `xhs_utils` imports. Select its
# coherent snapshot before any adapter lazily imports either package.
for name in ("apis", "xhs_utils"):
    loaded = sys.modules.get(name)
    paths = list(getattr(loaded, "__path__", [])) if loaded else []
    if paths and any(not Path(path).resolve().is_relative_to(SDK_ROOT) for path in paths):
        raise RuntimeError("An older XHS SDK was already imported; restart the backend")
if str(SDK_ROOT) not in sys.path:
    sys.path.insert(0, str(SDK_ROOT))
