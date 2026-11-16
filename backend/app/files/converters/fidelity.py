"""Fidelity tiers, metrics and user-facing warnings (plan §4)."""
from dataclasses import dataclass, field
from typing import List, Optional

TIER_A = "A"  # exact or lossless
TIER_B = "B"  # high fidelity, native engine
TIER_C = "C"  # reconstructive, must warn the user

TIER_LABELS = {
    TIER_A: "Lossless",
    TIER_B: "High fidelity",
    TIER_C: "Rebuilt layout",
}

TIER_DESCRIPTIONS = {
    TIER_A: "Content is preserved exactly or embedded unchanged.",
    TIER_B: "A native engine produces the same result; minor differences are possible.",
    TIER_C: "The layout is rebuilt from the source and may differ from the original.",
}

# Formats that re-compress by nature. Converting *to* these is always lossy.
LOSSY_TARGETS = {
    "jpg", "jpeg", "webp", "mp3", "aac", "m4a", "ogg", "opus", "wma",
    "mp4", "webm", "avi", "mkv", "mov", "flv", "wmv", "gif",
}

# Formats that cannot carry transparency.
OPAQUE_TARGETS = {"jpg", "jpeg", "bmp", "pdf"}

ANIMATED_SOURCES = {"gif", "webp", "apng"}
ANIMATED_TARGETS = {"gif", "webp"}

# Formats where location metadata (GPS EXIF) is routinely stripped.
EXIF_TARGETS = {"jpg", "jpeg", "png", "webp", "tiff"}


@dataclass
class FidelityReport:
    """Outcome of a conversion as far as the user needs to know."""

    tier: str = TIER_B
    warnings: List[str] = field(default_factory=list)
    metrics: dict = field(default_factory=dict)

    def add(self, message: str) -> None:
        if message and message not in self.warnings:
            self.warnings.append(message)

    @property
    def label(self) -> str:
        return TIER_LABELS.get(self.tier, self.tier)

    def as_dict(self) -> dict:
        return {
            "tier": self.tier,
            "label": self.label,
            "description": TIER_DESCRIPTIONS.get(self.tier, ""),
            "warnings": list(self.warnings),
            "metrics": dict(self.metrics),
        }


def build_warnings(
    source_ext: str,
    target_ext: str,
    tier: str,
    source_has_alpha: Optional[bool] = None,
    source_frame_count: Optional[int] = None,
    fonts_substituted: Optional[List[str]] = None,
) -> FidelityReport:
    """Derive the warning list shown next to a finished job."""
    src = (source_ext or "").lower().lstrip(".")
    dst = (target_ext or "").lower().lstrip(".")
    report = FidelityReport(tier=tier)

    if tier == TIER_C:
        report.add(
            "This conversion rebuilds the layout from the source file and may differ from the original."
        )

    if dst in LOSSY_TARGETS and src not in LOSSY_TARGETS:
        report.add(f"{dst.upper()} is a lossy format; the content was re-compressed.")
    elif dst in LOSSY_TARGETS and src != dst:
        report.add(f"Converting to {dst.upper()} re-compresses the content.")

    if source_has_alpha and dst in OPAQUE_TARGETS:
        report.add("Transparency was replaced with white.")

    if source_frame_count and source_frame_count > 1 and dst not in ANIMATED_TARGETS:
        report.add("Only the first frame was kept.")

    if (
        src in ANIMATED_SOURCES
        and dst in ANIMATED_TARGETS
        and source_frame_count
        and source_frame_count > 1
    ):
        report.metrics["animated"] = True

    if fonts_substituted:
        report.add("Fonts were substituted: " + ", ".join(fonts_substituted) + ".")

    if dst in EXIF_TARGETS and src in EXIF_TARGETS and src != dst:
        report.add("Location data may have been removed from this photo.")

    return report
