"""Build the offline raster-provider review gallery without consuming quota by default."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api" / "src"))

from hcs_api.models import ProviderSettings
from hcs_api.raster_provider_benchmark import create_raster_provider_ab_gallery


if __name__ == "__main__":
    # Intentional default: all five rows demonstrate the deterministic SVG
    # fallback.  To exercise a paid provider, invoke the library function with
    # a deliberately enabled experimental ProviderSettings in a local dev run.
    output = create_raster_provider_ab_gallery(ROOT, ProviderSettings())
    print(output)
