# SPDX-License-Identifier: MIT
# Copyright Contributors to the OpenTimelineIO project

"""Timing utility functions for music arrangement calculations."""

import logging
import math
from typing import Any

from opentimelineio import opentime  # type: ignore[import-untyped]

# Basic logger configuration
logger = logging.getLogger(__name__)
if not logger.hasHandlers():
    logger.addHandler(logging.NullHandler())

# Type alias for numeric values
NumericType = int | float


def time_value(time_obj: opentime.RationalTime | NumericType) -> float:
    """Helper to get float time value from RationalTime or numeric.

    Args:
        time_obj: RationalTime object or numeric value.

    Returns:
        Float time value in seconds.
    """
    if isinstance(time_obj, opentime.RationalTime):
        return float(time_obj.value)
    return float(time_obj)  # Assume float/int otherwise


def adjust_segment_times_to_downbeats(
    segments: list[dict[str, Any]],
    downbeats: list[NumericType],
    global_start_time: opentime.RationalTime,
) -> list[dict[str, Any]]:
    """Adjusts segment start/end times to align with nearest downbeats.

    Args:
        segments: List of segment dictionaries, each needing 'start', 'end', 'label'.
                 Start/end times are expected as seconds (float/int).
        downbeats: List of downbeat times in seconds (float/int).
        global_start_time: The zero time for the timeline.

    Returns:
        Adjusted segments with 'adjusted_start' and 'adjusted_end' keys
        containing opentime.RationalTime objects.
    """
    if not segments:
        logger.debug("Adjusting segment times: No segments found.")
        return []

    if not downbeats:
        logger.warning(
            "Adjusting segment times: No downbeats provided. Returning original times."
        )
        return [
            {
                "label": seg.get("label", f"Segment {i + 1}"),
                "original_start_time": opentime.RationalTime(
                    time_value(seg.get("start", 0)), global_start_time.rate
                ),
                "original_end_time": opentime.RationalTime(
                    time_value(seg.get("end", 0)), global_start_time.rate
                ),
                "adjusted_start_time": opentime.RationalTime(
                    time_value(seg.get("start", 0)), global_start_time.rate
                ),
                "adjusted_end_time": opentime.RationalTime(
                    time_value(seg.get("end", 0)), global_start_time.rate
                ),
            }
            for i, seg in enumerate(segments)
        ]

    rate = global_start_time.rate
    zero_time = opentime.RationalTime(0, rate)

    try:
        # Convert downbeats to RationalTime, relative to global_start_time (assumed 0)
        sorted_downbeats_rt = sorted(
            [opentime.RationalTime(time_value(d), rate) for d in downbeats]
        )
    except Exception as e:
        logger.error("Error converting downbeats to RationalTime: %s", e, exc_info=True)
        # Return original times on error
        return [
            {
                "label": seg.get("label", f"Segment {i + 1}"),
                "original_start_time": opentime.RationalTime(
                    time_value(seg.get("start", 0)), rate
                ),
                "original_end_time": opentime.RationalTime(
                    time_value(seg.get("end", 0)), rate
                ),
                "adjusted_start_time": opentime.RationalTime(
                    time_value(seg.get("start", 0)), rate
                ),
                "adjusted_end_time": opentime.RationalTime(
                    time_value(seg.get("end", 0)), rate
                ),
            }
            for i, seg in enumerate(segments)
        ]

    adjusted_segments = []
    last_adjusted_end_time = zero_time  # Initialize to timeline start

    for i, seg in enumerate(segments):
        label = seg.get("label", f"Segment {i + 1}")
        try:
            # Convert original segment times to RationalTime
            original_start_rt = opentime.RationalTime(
                time_value(seg.get("start", 0)), rate
            )
            original_end_rt = opentime.RationalTime(time_value(seg.get("end", 0)), rate)
        except Exception as e:
            logger.error(
                "Error converting segment %d times to RationalTime: %s. Segment: %s",
                i,
                e,
                seg,
                exc_info=True,
            )
            continue  # Skip segment if conversion fails

        # --- Find Nearest Downbeats ---
        first_downbeat_rt = sorted_downbeats_rt[0] if sorted_downbeats_rt else None

        # Find nearest preceding downbeat for start
        nearest_start_db_rt = None
        possible_starts = [db for db in sorted_downbeats_rt if db <= original_start_rt]
        if possible_starts:
            nearest_start_db_rt = max(possible_starts)
        elif first_downbeat_rt is not None:
            # If start is before the first actual downbeat,
            # snap start to the first downbeat
            logger.debug(
                "Segment '%s' starts at %s, before first downbeat %s. "
                "Adjusting start to first downbeat.",
                label,
                original_start_rt,
                first_downbeat_rt,
            )
            nearest_start_db_rt = first_downbeat_rt
        else:  # No downbeats at all
            nearest_start_db_rt = (
                original_start_rt  # Should have been caught earlier, but safe fallback
            )

        # Find nearest succeeding downbeat for end
        nearest_end_db_rt = None
        possible_ends = [db for db in sorted_downbeats_rt if db >= original_end_rt]
        if possible_ends:
            nearest_end_db_rt = min(possible_ends)
        elif sorted_downbeats_rt:
            # If ends after last downbeat, snap to last downbeat
            last_db = sorted_downbeats_rt[-1]
            if original_end_rt > last_db:
                logger.debug(
                    "Segment '%s' ends at %s, after last downbeat %s. "
                    "Adjusting end to last downbeat.",
                    label,
                    original_end_rt,
                    last_db,
                )
                nearest_end_db_rt = last_db
            else:
                # Ends before or on last db, but no db >= end? Implies between dbs.
                # Snap to the nearest *preceding* downbeat in this case.
                possible_ends_preceding = [
                    db for db in sorted_downbeats_rt if db <= original_end_rt
                ]
                if possible_ends_preceding:
                    nearest_end_db_rt = max(possible_ends_preceding)
                    logger.debug(
                        "Segment '%s' ends at %s, between downbeats. "
                        "Adjusting end to preceding downbeat %s.",
                        label,
                        original_end_rt,
                        nearest_end_db_rt,
                    )
                elif (
                    first_downbeat_rt is not None
                ):  # Ends before even the first downbeat
                    nearest_end_db_rt = first_downbeat_rt
                    logger.debug(
                        "Segment '%s' ends at %s, before first downbeat. "
                        "Adjusting end to first downbeat %s.",
                        label,
                        original_end_rt,
                        nearest_end_db_rt,
                    )
                else:  # No downbeats at all
                    nearest_end_db_rt = original_end_rt  # Safe fallback
        else:  # No downbeats
            nearest_end_db_rt = original_end_rt

        # --- Handle Potential Issues & Overlap ---

        # Ensure adjusted start <= adjusted end after initial snapping
        if nearest_start_db_rt > nearest_end_db_rt:
            logger.warning(
                "Segment '%s' initial snap resulted in start %s > end %s. "
                "Snapping both to start %s.",
                label,
                nearest_start_db_rt,
                nearest_end_db_rt,
                nearest_start_db_rt,
            )
            # If initial snap makes start > end, usually means segment is tiny
            # and fits between dbs. Snapping both to the *start* db seems most logical.
            nearest_end_db_rt = nearest_start_db_rt

        adjusted_start_final = nearest_start_db_rt
        adjusted_end_final = nearest_end_db_rt

        # Prevent overlap with the *previous adjusted segment*
        # Make sure the current start is not before the end of the last segment.
        if adjusted_start_final < last_adjusted_end_time:
            logger.warning(
                "Adjusted start time %s for segment '%s' overlaps previous "
                "adjusted end %s. Adjusting start to match previous end.",
                adjusted_start_final,
                label,
                last_adjusted_end_time,
            )
            adjusted_start_final = last_adjusted_end_time

        # Ensure duration is not negative *after overlap correction*
        if adjusted_end_final < adjusted_start_final:
            logger.warning(
                "Segment '%s' adjusted end %s is before adjusted start %s "
                "after overlap correction. Setting end equal to start.",
                label,
                adjusted_end_final,
                adjusted_start_final,
            )
            adjusted_end_final = adjusted_start_final

        logger.debug(
            "Segment '%s': Original (%s - %s), Adjusted (%s - %s)",
            label,
            original_start_rt,
            original_end_rt,
            adjusted_start_final,
            adjusted_end_final,
        )

        adjusted_segments.append(
            {
                "label": label,
                "original_start_time": original_start_rt,
                "original_end_time": original_end_rt,
                "adjusted_start_time": adjusted_start_final,
                "adjusted_end_time": adjusted_end_final,
            }
        )
        last_adjusted_end_time = adjusted_end_final  # Update for next iteration

    return adjusted_segments


def calculate_subdivision_markers(
    beats: list[NumericType],
    subdivision_level: int,
    global_start_time: opentime.RationalTime,
) -> dict[tuple[int, int], str]:
    """Calculates marker times and labels for beat subdivisions.

    Generates subdivision markers between beats for the specified subdivision level.
    For example, level 4 creates quarter-note subdivisions between each beat.

    Args:
        beats: List of beat times in seconds.
        subdivision_level: Number of subdivisions per beat interval
            (1 = no subdivisions, 2 = half-note subdivisions,
            4 = quarter-note subdivisions).
        global_start_time: The zero time for the timeline (determines rate).

    Returns:
        Dictionary mapping (value, rate) tuples to marker labels.
        Keys are RationalTime components for hashable lookup.
    """
    markers: dict[tuple[int, int], str] = {}
    if subdivision_level < 1:
        logger.error(
            "Subdivision level must be 1 or greater, got: %d", subdivision_level
        )
        return markers

    if not beats:
        logger.warning("No beats provided for subdivision calculation.")
        return markers

    rate = global_start_time.rate

    try:
        # Convert beat times to RationalTime
        beats_rt = [opentime.RationalTime(time_value(b), rate) for b in beats]
    except Exception as e:
        logger.error("Error converting beats to RationalTime: %s", e, exc_info=True)
        return markers

    # Add main beat markers first
    for i, beat_time_rt in enumerate(beats_rt):
        # Use math.ceil to ensure beat numbers are 1-based and handle potential
        # floating point issues near integers
        beat_num = math.ceil(i + 1)
        label = f"Beat {beat_num}"
        # Use a hashable key (tuple) instead of RationalTime directly
        markers[(beat_time_rt.value, beat_time_rt.rate)] = label

    # Calculate and add subdivision markers if level > 1
    if subdivision_level > 1:
        for i in range(len(beats_rt) - 1):  # Iterate through intervals between beats
            start_beat_rt = beats_rt[i]
            end_beat_rt = beats_rt[i + 1]
            interval_rt = end_beat_rt - start_beat_rt

            # Skip if interval is zero or negative duration
            if interval_rt <= opentime.RationalTime(0, rate):
                logger.warning(
                    "Skipping zero or negative duration interval between "
                    "beat %d (%s) and beat %d (%s)",
                    i + 1,
                    start_beat_rt,
                    i + 2,
                    end_beat_rt,
                )
                continue

            # Calculate time step for subdivisions within this interval
            # Need to multiply first then divide to avoid potential precision
            # loss with RationalTime division
            # step_rt = interval_rt / subdivision_level # Less precise for RationalTime
            # Perform calculation using floating point for intermediate step,
            # then convert back
            interval_val = time_value(interval_rt)
            step_val = interval_val / subdivision_level

            beat_num = math.ceil(i + 1)  # Base beat number for label

            for k in range(1, subdivision_level):  # k from 1 to subdivision_level-1
                # Calculate intermediate time using floating point then convert
                intermediate_time_val = time_value(start_beat_rt) + k * step_val
                intermediate_time_rt = opentime.RationalTime(
                    intermediate_time_val, rate
                )

                # Ensure the intermediate time doesn't overshoot the next beat
                # (can happen due to float precision)
                if intermediate_time_rt >= end_beat_rt:
                    # logger.debug('Skipping subdivision %d/%d for beat %d,
                    # calculated time %s >= next beat %s',
                    # k, subdivision_level, beat_num, intermediate_time_rt, end_beat_rt)
                    continue

                # Label like Beat 5.1/4, Beat 5.2/4 etc.
                label = f"Beat {beat_num}.{k}/{subdivision_level}"
                # Use a hashable key (tuple) instead of RationalTime directly
                markers[(intermediate_time_rt.value, intermediate_time_rt.rate)] = label

    logger.debug(
        "Calculated %d markers for subdivision level %d",
        len(markers),
        subdivision_level,
    )
    # Sort markers by time before returning for predictable order (optional but helpful)
    # sorted_markers = dict(sorted(markers.items()))
    # return sorted_markers
    # Return a dict mapping hashable tuple (value, rate) to label
    return markers
