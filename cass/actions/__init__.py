"""Actions — business logic for cass.

Cross-service matching, pull orchestration, and configuration.
"""

from __future__ import annotations

__docformat__ = "google"

from .config import Config, get_config
from .matching import (
    MatchResult,
    find_candidates,
    match_students,
    normalize,
    slug_match,
    slugify,
)

__all__ = [
    "Config",
    "MatchResult",
    "find_candidates",
    "get_config",
    "match_students",
    "normalize",
    "slug_match",
    "slugify",
]
