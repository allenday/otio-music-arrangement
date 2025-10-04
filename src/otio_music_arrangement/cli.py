# SPDX-License-Identifier: MIT
# Copyright Contributors to the OpenTimelineIO project

"""Command-line interface for otio-music-arrangement."""

import argparse
import json
import logging
import sys
from pathlib import Path
from typing import Any, Dict, List

import opentimelineio as otio  # type: ignore[import-untyped]

from . import build_timeline_from_audio
from .timing_utils import adjust_segment_times_to_downbeats


def setup_logging(verbose: bool = False) -> None:
    """Setup logging configuration."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def load_json_file(file_path: str) -> Dict[str, Any]:
    """Load and parse a JSON file."""
    try:
        with open(file_path, "r") as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"Error: File not found: {file_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON in {file_path}: {e}")
        sys.exit(1)


def parse_timing_data(timing_data: Dict[str, Any]) -> tuple[List[float], List[float], List[Dict[str, Any]]]:
    """Parse timing data from JSON format."""
    beats = timing_data.get("beats", [])
    downbeats = timing_data.get("downbeats", [])
    segments = timing_data.get("segments", [])

    # Validate segments format
    for i, segment in enumerate(segments):
        if not all(key in segment for key in ["start", "end", "label"]):
            print(f"Error: Segment {i} missing required keys (start, end, label)")
            sys.exit(1)

    return beats, downbeats, segments


def main() -> None:
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Generate OpenTimelineIO timelines for music video editing workflows",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate timeline from audio and timing data
  otio-music-arrange -a song.wav -t timing.json -o output.fcpxml

  # Use subdivision markers and accumulate mode
  otio-music-arrange -a song.wav -t timing.json -o output.fcpxml --subdivision-level 4 --accumulate

  # Adjust segments to align with downbeats
  otio-music-arrange -a song.wav -t timing.json -o output.fcpxml --adjust-segments

Timing JSON format:
{
  "beats": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
  "downbeats": [1.0, 3.0, 5.0, 7.0],
  "segments": [
    {"start": 1.0, "end": 5.0, "label": "verse"},
    {"start": 5.0, "end": 9.0, "label": "chorus"}
  ]
}
        """,
    )

    # Required arguments
    parser.add_argument(
        "-a", "--audio",
        required=True,
        help="Path to the primary audio file"
    )

    parser.add_argument(
        "-t", "--timing",
        required=True,
        help="Path to JSON file containing timing data (beats, downbeats, segments)"
    )

    parser.add_argument(
        "-o", "--output",
        required=True,
        help="Output file path (e.g., timeline.fcpxml, timeline.otio)"
    )

    # Optional arguments
    parser.add_argument(
        "--subdivision-level",
        type=int,
        default=1,
        help="Beat subdivision level (1=none, 2=half-notes, 4=quarter-notes, default: 1)"
    )

    parser.add_argument(
        "--accumulate",
        action="store_true",
        help="Markers appear on multiple tracks (e.g., downbeats also appear on beats track)"
    )

    parser.add_argument(
        "--adjust-segments",
        action="store_true",
        help="Adjust segment boundaries to align with nearest downbeats"
    )

    parser.add_argument(
        "--frame-rate",
        type=float,
        default=30.0,
        help="Frame rate for the timeline (default: 30.0 fps)"
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging(args.verbose)
    logger = logging.getLogger(__name__)

    # Validate input files
    if not Path(args.audio).exists():
        print(f"Error: Audio file not found: {args.audio}")
        sys.exit(1)

    if not Path(args.timing).exists():
        print(f"Error: Timing file not found: {args.timing}")
        sys.exit(1)

    # Load timing data
    logger.info(f"Loading timing data from: {args.timing}")
    timing_data = load_json_file(args.timing)
    beats, downbeats, segments = parse_timing_data(timing_data)

    logger.info(f"Loaded {len(beats)} beats, {len(downbeats)} downbeats, {len(segments)} segments")

    # Adjust segments to downbeats if requested
    if args.adjust_segments and downbeats:
        logger.info("Adjusting segment boundaries to align with downbeats")
        # Use same video rate as the builder will use
        video_rate = int(args.frame_rate)
        global_start_time = otio.opentime.RationalTime(0, video_rate)
        adjusted_segments = adjust_segment_times_to_downbeats(segments, downbeats, global_start_time)

        # Convert adjusted segments back to expected format
        segments = []
        for seg in adjusted_segments:
            # Convert RationalTime back to seconds
            start_seconds = seg["adjusted_start_time"].to_seconds()
            end_seconds = seg["adjusted_end_time"].to_seconds()
            original_start = seg["original_start_time"].to_seconds()
            original_end = seg["original_end_time"].to_seconds()

            duration = end_seconds - start_seconds
            original_duration = original_end - original_start

            logger.debug(
                f"Segment '{seg['label']}': "
                f"Original ({original_start:.3f}-{original_end:.3f}, dur={original_duration:.3f}s) -> "
                f"Adjusted ({start_seconds:.3f}-{end_seconds:.3f}, dur={duration:.3f}s)"
            )

            # Validate segment has positive duration
            if duration > 0.01:  # At least 10ms duration
                segments.append({
                    "start": start_seconds,
                    "end": end_seconds,
                    "label": seg["label"],
                })
            else:
                logger.warning(f"Skipping invalid adjusted segment: {seg['label']} (duration = {duration:.6f}s <= 0.01s)")

        logger.info(f"Adjusted {len(segments)} segments to align with downbeats (from {len(adjusted_segments)} total)")

    # Build timeline
    logger.info(f"Building timeline from audio: {args.audio}")
    timeline = build_timeline_from_audio(
        audio_path=args.audio,
        beats=beats,
        downbeats=downbeats,
        segments=segments,
        subdivision_level=args.subdivision_level,
        accumulate=args.accumulate,
        frame_rate=args.frame_rate,
    )

    if timeline is None:
        print("Error: Failed to build timeline")
        sys.exit(1)

    # Write output
    logger.info(f"Writing timeline to: {args.output}")
    try:
        otio.adapters.write_to_file(timeline, args.output)
        logger.info("Timeline successfully generated!")
        print(f"Timeline written to: {args.output}")
    except Exception as e:
        print(f"Error writing timeline: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()