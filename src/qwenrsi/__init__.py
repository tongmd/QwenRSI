"""QwenRSI: bounded, measured evolution of compiled agent controllers."""

__version__ = "0.1.0"


def enable_chipformer():
    """Load the pinned, MIT-licensed upstream package from source or installed wheel."""
    import sys
    from pathlib import Path

    here = Path(__file__).resolve()
    choices = [here.parent / "_vendor", here.parents[2] / "vendor" / "qwenputer"]
    for root in choices:
        if (root / "chipformer").is_dir():
            if str(root) not in sys.path:
                sys.path.insert(0, str(root))
            return
    raise RuntimeError("Pinned Qwenputer source is missing; reinstall qwenrsi.")
