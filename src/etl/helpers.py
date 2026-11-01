## Helper functions for cleaning and normalizing data

import numpy as np
import pandas as pd


def clean(v):
    """NaN/NaT -> None, numpy scalars -> Python scalars."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v.item() if hasattr(v, "item") else v


def clean_date(v):
    v = clean(v)
    return None if v is None else pd.Timestamp(v).date()


def norm_concept(c: str) -> str:
    """'us-gaap_Revenues' -> 'us-gaap:Revenues'.

    Facts already use the colon form; presentation, calculation and the element catalog
    use the underscore form. Replacing the FIRST underscore is correct as long as the
    namespace prefix itself contains no underscore (unverified for every filer prefix).
    """
    return c if ":" in c else c.replace("_", ":", 1)