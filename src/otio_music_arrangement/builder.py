# SPDX-License-Identifier: MIT
# Copyright Contributors to the OpenTimelineIO project

"""Builder module for creating OpenTimelineIO timelines from music arrangement data."""

import logging
import os
from decimal import Decimal, getcontext
from typing import Any

import ffmpeg  # type: ignore[import-untyped]
import opentimelineio as otio  # type: ignore[import-untyped]
from opentimelineio import opentime

logger = logging.getLogger(__name__)
getcontext().prec = 15  # Set precision for Decimal calculations

# --- Constants ---
DEFAULT_RATE = 48000  # Default sample rate if not provided/determinable
PLACEHOLDER_EFFECT_UID = (
    ".../Generators.localized/Elements.localized/Placeholder.localized/Placeholder.motn"
)
PLACEHOLDER_EFFECT_NAME = "Placeholder"
# Assume a resource ID the lite adapter might assign or look for
# (this might need adjustment)
PLACEHOLDER_FCPX_REF = "r_placeholder"

# Marker Colors
SEGMENT_COLOR = otio.schema.MarkerColor.RED
DOWNBEAT_COLOR = otio.schema.MarkerColor.GREEN
BEAT_COLOR = otio.schema.MarkerColor.BLUE
SUBDIVISION_COLORS = [
    otio.schema.MarkerColor.YELLOW,
    otio.schema.MarkerColor.CYAN,
    otio.schema.MarkerColor.MAGENTA,
]

# --- Helper Functions ---


def _get_audio_duration_ffmpeg(file_path: str) -> float | None:
    """Gets the duration of an audio/video file using ffmpeg-python.

    Args:
        file_path: Path to the audio/video file.

    Returns:
        Duration in seconds if successful, None if failed.
    """
    try:
        logger.debug(f"Probing file for duration: {file_path}")
        probe = ffmpeg.probe(file_path)
        duration_str = probe.get("format", {}).get("duration")
        if duration_str is None:
            # Check streams if format duration is missing
            for stream in probe.get("streams", []):
                duration_str = stream.get("duration")
                if duration_str:
                    logger.debug("Using duration from stream.")
                    break
            if duration_str is None:
                logger.warning(
                    f"Could not find 'duration' in format or stream info for: "
                    f"{file_path}"
                )
                return None
        duration_sec = float(duration_str)
        logger.debug(
            f"Successfully probed duration: {duration_sec} seconds for: {file_path}"
        )
        return duration_sec
    except ffmpeg.Error as e:
        stderr_output = e.stderr.decode("utf8") if e.stderr else "N/A"
        logger.error(
            f"ffmpeg probe error for {file_path}: {e}. Stderr: {stderr_output}",
            exc_info=True,
        )
        return None
    except FileNotFoundError:
        logger.error(
            "FFmpeg executable not found. Please ensure ffmpeg is installed "
            "and in your PATH."
        )
        return None
    except Exception as e:
        logger.error(f"Error probing duration for {file_path}: {e}", exc_info=True)
        return None


def _calculate_subdivision_markers_rt(
    beats_rt: list[opentime.RationalTime], subdivision_level: int, rate: int
) -> list[tuple[opentime.RationalTime, str]]:
    """Calculates subdivision markers between beats, returning RationalTime values.

    Args:
        beats_rt: List of beat times as RationalTime objects.
        subdivision_level: Number of subdivisions per beat interval.
        rate: Sample rate for calculations.

    Returns:
        List of (RationalTime, label) tuples for subdivision markers.
    """
    subdivision_markers: list[tuple[opentime.RationalTime, str]] = []
    if not beats_rt or subdivision_level < 1:
        return subdivision_markers

    for i in range(len(beats_rt) - 1):
        start_beat_rt = beats_rt[i]
        end_beat_rt = beats_rt[i + 1]
        interval_rt = end_beat_rt - start_beat_rt

        if interval_rt <= otio.opentime.RationalTime(0, rate):
            continue

        # Use Decimal for precision during subdivision calculation
        try:
            interval_decimal = Decimal(interval_rt.value) / Decimal(interval_rt.rate)
            level_decimal = Decimal(subdivision_level)
            step_decimal = interval_decimal / level_decimal
            start_beat_decimal = Decimal(start_beat_rt.value) / Decimal(
                start_beat_rt.rate
            )

            for k in range(1, subdivision_level):
                k_decimal = Decimal(k)
                # Calculate subdivision time in seconds first
                intermediate_time_decimal = start_beat_decimal + (
                    k_decimal * step_decimal
                )
                # Convert back to RationalTime
                intermediate_value_float = float(
                    intermediate_time_decimal * Decimal(rate)
                )
                # Round to nearest frame value before creating RationalTime
                intermediate_frame = round(intermediate_value_float)
                intermediate_beat_rt = otio.opentime.RationalTime(
                    intermediate_frame, rate
                )

                # Ensure the calculated time is within the interval
                if (
                    intermediate_beat_rt > start_beat_rt
                    and intermediate_beat_rt < end_beat_rt
                ):
                    label = f"Beat {i + 1}.{k}"  # Simpler label
                    subdivision_markers.append((intermediate_beat_rt, label))

        except Exception as e:
            logger.error(
                "Error calculating subdivisions between %s and %s: %s",
                start_beat_rt,
                end_beat_rt,
                e,
                exc_info=True,
            )

    subdivision_markers.sort(key=lambda x: x[0])
    logger.debug(
        "Calculated %d subdivision markers for Level %d",
        len(subdivision_markers),
        subdivision_level,
    )
    return subdivision_markers


# --- Main Builder Function ---


def build_timeline_from_audio(
    audio_path: str,
    beats: list[float | int],
    downbeats: list[float | int],
    segments: list[dict[str, Any]],
    subdivision_level: int = 1,
    accumulate: bool = False,
) -> otio.schema.Timeline | None:
    """Builds an OTIO timeline compatible with otio-fcpx-xml-lite-adapter.

    Creates one audio track and multiple video tracks (Segments, Downbeats,
    Beats, Subdivisions) containing placeholder clips with attached markers.

    Args:
        audio_path: Path to the primary audio file.
        beats: List of beat times in seconds.
        downbeats: List of downbeat times in seconds.
        segments: List of segment dicts with 'start', 'end', 'label' keys.
        subdivision_level: Level of beat subdivision markers to create.
            Defaults to 1 (no subdivisions).
        accumulate: If True, markers accumulate down tracks (e.g., a downbeat
            also appears on the Beat track). If False (default), markers appear
            only on the most specific track.

    Returns:
        The generated OpenTimelineIO timeline object, or None if essential
        data is missing or invalid.
    """
    # --- Validation and Setup ---
    if not audio_path or not os.path.exists(audio_path):
        logger.error(f"Audio path invalid or file not found: {audio_path}")
        return None
    if not beats or not segments:
        logger.error(
            "Essential data missing (beats or segments). Cannot create timeline."
        )
        return None
    if downbeats is None:
        downbeats = []  # Allow empty downbeats
    if subdivision_level < 1:
        subdivision_level = 1

    rate = DEFAULT_RATE  # Use a consistent rate
    global_start_time = otio.opentime.RationalTime(0, rate)

    # --- Convert Times to RationalTime ---
    try:
        # Ensure times are floats/Decimals before conversion
        beats_rt = sorted(
            [otio.opentime.RationalTime(float(b) * rate, rate) for b in beats]
        )
        downbeats_rt = sorted(
            [otio.opentime.RationalTime(float(d) * rate, rate) for d in downbeats]
        )
        segments_rt = [
            {
                "start": otio.opentime.RationalTime(float(s["start"]) * rate, rate),
                "end": otio.opentime.RationalTime(float(s["end"]) * rate, rate),
                "label": s["label"],
            }
            for s in segments
        ]
        segments_rt.sort(key=lambda x: x["start"])
    except Exception as e:
        logger.error(
            "Error converting input times to RationalTime: %s", e, exc_info=True
        )
        return None

    # --- Calculate Overall Timeline Duration ---
    max_segment_end = max((s["end"] for s in segments_rt), default=global_start_time)
    all_beat_times = beats_rt + downbeats_rt
    max_beat_time = max(all_beat_times) if all_beat_times else global_start_time
    max_time_rt = max(max_segment_end, max_beat_time)

    # Get actual audio duration
    actual_audio_duration_rt = global_start_time
    actual_duration_seconds = _get_audio_duration_ffmpeg(audio_path)
    if actual_duration_seconds is not None:
        actual_audio_duration_rt = otio.opentime.RationalTime(
            actual_duration_seconds * rate, rate
        )
        logger.info(
            "Actual audio file duration: %s (%.3f sec)",
            actual_audio_duration_rt,
            actual_duration_seconds,
        )
    else:
        logger.warning(
            "Could not determine actual audio duration. Using marker-based duration."
        )

    # Final timeline duration is the max of marker extent or actual audio length
    timeline_duration_rt = max(max_time_rt, actual_audio_duration_rt)

    # Quantize duration to nearest frame - essential for FCPXML
    timeline_duration_frames = int(round(timeline_duration_rt.to_frames()))
    timeline_duration_rt = otio.opentime.RationalTime(timeline_duration_frames, rate)
    if timeline_duration_rt <= global_start_time:
        logger.warning(
            "Calculated timeline duration is zero or negative. Setting to 1 frame."
        )
        timeline_duration_rt = otio.opentime.RationalTime(1, rate)
    logger.info(
        "Final quantized timeline duration: %s (%.3f sec)",
        timeline_duration_rt,
        timeline_duration_rt.to_seconds(),
    )

    # --- Create Timeline and Tracks ---
    timeline_name = f"Music Arrangement Lite - {os.path.basename(audio_path)}"
    timeline = otio.schema.Timeline(
        name=timeline_name, global_start_time=global_start_time
    )

    # --- Create Shared Placeholder Generator Reference ---
    placeholder_generator_ref = otio.schema.GeneratorReference(
        name="Placeholder GenRef",  # Internal OTIO name
        generator_kind="fcpx_video_placeholder",
        # available_range=opentime.TimeRange(duration=timeline_duration_rt),
        # Does GenRef need this? Maybe not.
        parameters={
            "fcpx_ref": PLACEHOLDER_FCPX_REF,
            "fcpx_effect_name": PLACEHOLDER_EFFECT_NAME,
            "fcpx_effect_uid": PLACEHOLDER_EFFECT_UID,
        },
    )

    # --- Create Audio Track (Lane -1) ---
    logger.debug("Creating Audio Track...")
    audio_track = otio.schema.Track(name="Audio 1", kind=otio.schema.TrackKind.Audio)
    audio_ref = otio.schema.ExternalReference(
        target_url=otio.url_utils.url_from_filepath(audio_path),
        # Available range should reflect the *actual* file duration
        available_range=otio.opentime.TimeRange(
            start_time=global_start_time,
            duration=actual_audio_duration_rt
            if actual_duration_seconds
            else timeline_duration_rt,
        ),
    )
    audio_clip = otio.schema.Clip(
        name=os.path.basename(audio_path),
        media_reference=audio_ref,
        # Source range uses the calculated timeline duration
        source_range=otio.opentime.TimeRange(
            start_time=global_start_time, duration=timeline_duration_rt
        ),
    )
    audio_track.append(audio_clip)
    timeline.tracks.append(audio_track)
    logger.debug("Audio Track created.")

    # --- Create Video Tracks for Markers ---
    logger.debug("Creating Video Marker Tracks...")
    video_tracks = {}
    video_tracks["Segments"] = otio.schema.Track(
        name="Segments", kind=otio.schema.TrackKind.Video
    )
    video_tracks["Downbeats"] = otio.schema.Track(
        name="Downbeats", kind=otio.schema.TrackKind.Video
    )
    video_tracks["Beats"] = otio.schema.Track(
        name="Beats", kind=otio.schema.TrackKind.Video
    )
    if subdivision_level > 1:
        video_tracks["Subdivisions"] = otio.schema.Track(
            name=f"Subdivisions (1/{subdivision_level})",
            kind=otio.schema.TrackKind.Video,
        )

    # Add tracks to timeline in a specific order
    # (e.g., Segments, Downbeats, Beats, Subs)
    track_order = ["Segments", "Downbeats", "Beats", "Subdivisions"]
    for track_name in track_order:
        if track_name in video_tracks:
            timeline.tracks.append(video_tracks[track_name])

    # Keep track of current time for each video track to add gaps correctly
    current_track_times = dict.fromkeys(video_tracks, global_start_time)

    # --- Populate Video Tracks with Placeholder Clips and Markers ---
    logger.debug("Populating Video Tracks...")
    subdivision_markers_rt = []
    if subdivision_level > 1:
        subdivision_markers_rt = _calculate_subdivision_markers_rt(
            beats_rt, subdivision_level, rate
        )

    # Create sets of FRAME NUMBERS for faster lookup
    downbeat_frames_set = {rt.to_frames() for rt in downbeats_rt}
    beat_frames_set = {rt.to_frames() for rt in beats_rt}
    subdivision_frames_set = {rt.to_frames() for rt, _ in subdivision_markers_rt}

    # Create a combined set of all unique marker frames
    all_marker_frames = downbeat_frames_set.union(beat_frames_set).union(
        subdivision_frames_set
    )

    # Create a lookup from frame number back to the original RationalTime
    # and label (for subs). Prioritize downbeats/beats if frames collide
    # (though unlikely with rounding)
    frames_to_rt = {rt.to_frames(): rt for rt, _ in subdivision_markers_rt}
    frames_to_rt.update({rt.to_frames(): rt for rt in beats_rt})
    frames_to_rt.update({rt.to_frames(): rt for rt in downbeats_rt})

    # Lookup for subdivision labels by frame
    subdivision_labels_by_frame = {
        rt.to_frames(): lbl for rt, lbl in subdivision_markers_rt
    }

    for _i, segment in enumerate(segments_rt):
        seg_start_rt = segment["start"]
        seg_end_rt = segment["end"]
        seg_label = segment["label"]

        # Quantize segment times to frames
        start_frame = int(round(seg_start_rt.to_frames()))
        end_frame = int(round(seg_end_rt.to_frames()))
        quantized_seg_start_rt = otio.opentime.RationalTime(start_frame, rate)
        quantized_seg_end_rt = otio.opentime.RationalTime(end_frame, rate)
        quantized_seg_duration_rt = quantized_seg_end_rt - quantized_seg_start_rt

        if quantized_seg_duration_rt <= global_start_time:
            logger.debug(
                f"Skipping zero/negative duration quantized segment: {seg_label}"
            )
            continue

        # Define the source range for the placeholder clip for this segment duration
        placeholder_source_range = otio.opentime.TimeRange(
            duration=quantized_seg_duration_rt
        )

        # --- Collect markers within this segment ---
        segment_markers = {}
        segment_markers["Segments"] = [
            otio.schema.Marker(
                name=seg_label,
                color=SEGMENT_COLOR,
                # Place segment label marker at the start of the clip
                marked_range=otio.opentime.TimeRange(
                    start_time=global_start_time, duration=global_start_time
                ),
            )
        ]  # Always add segment label marker
        segment_markers["Downbeats"] = []
        segment_markers["Beats"] = []
        if subdivision_level > 1:
            segment_markers["Subdivisions"] = []

        # Iterate through UNIQUE marker frame numbers
        for marker_frames in all_marker_frames:
            # Get the corresponding RationalTime
            marker_time_rt = frames_to_rt.get(marker_frames)
            if not marker_time_rt:
                continue  # Should not happen if dictionary is built correctly

            # Check if this unique marker time falls within the segment
            if seg_start_rt <= marker_time_rt < seg_end_rt:
                # Calculate time relative to the *quantized* segment start
                marker_time_relative = marker_time_rt - quantized_seg_start_rt
                if marker_time_relative < global_start_time:
                    marker_time_relative = global_start_time  # Clamp to start
                # Ensure marker doesn't fall outside the *quantized* clip duration
                if marker_time_relative >= quantized_seg_duration_rt:
                    continue  # Skip marker if quantization pushed it outside

                marked_range = otio.opentime.TimeRange(
                    start_time=marker_time_relative, duration=global_start_time
                )

                # --- Determine which level(s) this marker belongs to ---
                is_downbeat = marker_frames in downbeat_frames_set
                is_beat = marker_frames in beat_frames_set
                is_subdivision = marker_frames in subdivision_frames_set

                # --- Add Markers based on flags and accumulate setting ---

                # Always add downbeat if it matches
                if is_downbeat:
                    segment_markers["Downbeats"].append(
                        otio.schema.Marker(
                            name="Downbeat",
                            color=DOWNBEAT_COLOR,
                            marked_range=marked_range,
                        )
                    )

                # Add beat if it matches AND (accumulating OR it wasn't a downbeat)
                if is_beat and (accumulate or not is_downbeat):
                    segment_markers["Beats"].append(
                        otio.schema.Marker(
                            name="Beat", color=BEAT_COLOR, marked_range=marked_range
                        )
                    )

                # Add subdivision if it matches AND (accumulating OR it wasn't
                # a downbeat OR a beat). Also check if the subdivision track exists
                if (
                    "Subdivisions" in segment_markers
                    and is_subdivision
                    and (accumulate or not (is_downbeat or is_beat))
                ):
                    subdivision_label = subdivision_labels_by_frame.get(
                        marker_frames, "Sub"
                    )  # Use lookup
                    segment_markers["Subdivisions"].append(
                        otio.schema.Marker(
                            name=subdivision_label,
                            color=SUBDIVISION_COLORS[0],
                            marked_range=marked_range,
                        )
                    )

        # --- Add placeholder clip to tracks if they have markers for this segment ---
        for track_name, track in video_tracks.items():
            if segment_markers.get(
                track_name
            ):  # Check if this track type has markers in this segment
                # Create the placeholder clip instance WITHOUT markers arg
                placeholder_clip = otio.schema.Clip(
                    name=f"{track_name} Clip: {seg_label}",
                    media_reference=placeholder_generator_ref,
                    source_range=placeholder_source_range,
                    # markers=segment_markers[track_name]
                    # Markers are added after creation
                )
                # Add markers to the created clip
                placeholder_clip.markers.extend(segment_markers[track_name])

                # Add Gap before the clip if needed
                gap_duration = quantized_seg_start_rt - current_track_times[track_name]
                if gap_duration > global_start_time:
                    track.append(
                        otio.schema.Gap(
                            source_range=otio.opentime.TimeRange(duration=gap_duration)
                        )
                    )

                # Append the placeholder clip
                track.append(placeholder_clip)

                # Update the current time for this track
                current_track_times[track_name] = (
                    quantized_seg_end_rt  # End of the appended clip
                )

    # --- Add Final Gaps to Video Tracks ---
    logger.debug("Adding final gaps to video tracks...")
    for track_name, track in video_tracks.items():
        final_gap_duration = timeline_duration_rt - current_track_times[track_name]
        if final_gap_duration > global_start_time:
            track.append(
                otio.schema.Gap(
                    source_range=otio.opentime.TimeRange(duration=final_gap_duration)
                )
            )

    logger.info("Successfully built OTIO timeline for lite adapter.")
    return timeline
