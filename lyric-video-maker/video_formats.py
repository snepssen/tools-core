"""Shared output-format contract for rendering and subtitle layout."""

VIDEO_FORMATS = {
    "landscape": {
        "label": "Landscape",
        "detail": "Desktop · YouTube",
        "width": 1920,
        "height": 1080,
        "suffix": "",
        "inactive_y": 950,
        "sizes": {
            "big": (12, 108, 80),
            "default": (24, 72, 54),
            "dense": (36, 54, 42),
        },
    },
    "portrait": {
        "label": "Portrait",
        "detail": "Shorts · Reels",
        "width": 1080,
        "height": 1920,
        "suffix": "-short",
        "inactive_y": 1450,
        "sizes": {
            "big": (10, 96, 72),
            "default": (18, 72, 54),
            "dense": (26, 54, 42),
        },
    },
}


def get_video_format(name):
    """Return a known format or raise a user-facing error."""
    try:
        return VIDEO_FORMATS[name]
    except KeyError as exc:
        choices = ", ".join(VIDEO_FORMATS)
        raise ValueError(f"Unknown video format {name!r}; choose {choices}") from exc


def output_name(audio_name, format_name):
    """Output basename, keeping portrait renders beside landscape ones."""
    import os

    stem = os.path.splitext(os.path.basename(audio_name))[0]
    return stem + get_video_format(format_name)["suffix"] + ".mp4"
