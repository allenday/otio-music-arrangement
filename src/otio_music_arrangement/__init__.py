# SPDX-License-Identifier: MIT
# Copyright Contributors to the OpenTimelineIO project

"""OpenTimelineIO Music Arrangement Package.

This library builds OpenTimelineIO timelines specifically tailored for music video
editing workflows. It takes musical timing information (segments like verse/chorus,
beats, downbeats) and generates an OTIO timeline structure that can be exported to
FCPXML and other NLE formats via OTIO adapters.

Key Features:
- Primary audio track with music file
- Video tracks with placeholder clips representing song sections (verse, chorus, etc.)
- Multiple visual guide tracks for beat subdivisions (1/1 beats, 1/2, 1/3, 1/4 notes)
- Precise marker placement aligned to musical timing

Example:
    >>> from otio_music_arrangement import build_timeline_from_audio
    >>> timeline = build_timeline_from_audio(
    ...     audio_path="song.wav",
    ...     beats=[1.0, 2.0, 3.0, 4.0],
    ...     downbeats=[1.0, 3.0],
    ...     segments=[{"start": 0.0, "end": 4.0, "label": "verse"}],
    ...     subdivision_level=2,
    ...     accumulate=True
    ... )
"""

__version__ = "0.1.0"

# Import main functions for easier access
from .builder import build_timeline_from_audio
from .timing_utils import (
    adjust_segment_times_to_downbeats,
    calculate_subdivision_markers,
)

__all__ = [
    "build_timeline_from_audio",
    "adjust_segment_times_to_downbeats",
    "calculate_subdivision_markers",
]
