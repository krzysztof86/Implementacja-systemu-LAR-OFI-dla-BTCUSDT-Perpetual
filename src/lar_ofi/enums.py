"""Closed vocabularies shared by every module."""

from enum import StrEnum

UNKNOWN = "UNKNOWN"
CONFLICT = "CONFLICT"
NOT_CALIBRATED = "NOT_CALIBRATED"


class Decision(StrEnum):
    LONG = "LONG"
    SHORT = "SHORT"
    WAIT = "WAIT"


class SetupState(StrEnum):
    NONE = "NONE"
    CANDIDATE_LONG = "CANDIDATE_LONG"
    CANDIDATE_SHORT = "CANDIDATE_SHORT"
    CONFIRMED_LONG = "CONFIRMED_LONG"
    CONFIRMED_SHORT = "CONFIRMED_SHORT"
    INVALIDATED = "INVALIDATED"
    WAIT = "WAIT"


class EvidenceKind(StrEnum):
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    HYPOTHESIS = "HYPOTHESIS"
    UNKNOWN = "UNKNOWN"


class Readability(StrEnum):
    CLEAR = "CLEAR"
    UNCERTAIN = "UNCERTAIN"
    UNREADABLE = "UNREADABLE"


class Tri(StrEnum):
    """Three-valued logic used by setup conditions."""

    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class DataStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"
    NO_DATA = "NO_DATA"


class Outcome(StrEnum):
    HIT = "HIT"
    MISS = "MISS"
    NEUTRAL = "NEUTRAL"
    MOVE_UP = "MOVE_UP"
    MOVE_DOWN = "MOVE_DOWN"
    NO_SIGNIFICANT_MOVE = "NO_SIGNIFICANT_MOVE"
    UNSCORABLE = "UNSCORABLE"
