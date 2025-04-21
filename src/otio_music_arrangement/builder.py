# SPDX-License-Identifier: MIT
# Copyright Contributors to the OpenTimelineIO project

import logging
import opentimelineio as otio
import os
import ffmpeg # Added import
from . import timing_utils # Use relative import within the package

logger = logging.getLogger(__name__)

DEFAULT_RATE = 48000 # Revert back to single default rate for core logic
# DEFAULT_AUDIO_RATE = 48000 # Common audio sample rate
DEFAULT_VIDEO_RATE = 29.97 # Common NTSC video rate (frames per second) - Keep for rounding
PLACEHOLDER_COLOR = otio.schema.MarkerColor.RED # Color for segment markers
DOWNBEAT_COLOR = otio.schema.MarkerColor.GREEN
BEAT_COLOR = otio.schema.MarkerColor.BLUE
# Add more colors if adding more subdivision levels later
# SUBDIVISION_COLORS = [otio.schema.MarkerColor.YELLOW, otio.schema.MarkerColor.CYAN, otio.schema.MarkerColor.MAGENTA]

def _get_audio_duration_ffmpeg(file_path):
    """Gets the duration of an audio/video file using ffmpeg-python."""
    try:
        logger.debug(f"Probing file for duration: {file_path}")
        probe = ffmpeg.probe(file_path)
        duration_str = probe.get('format', {}).get('duration')
        if duration_str is None:
            logger.warning(f"Could not find 'duration' in format info for: {file_path}")
            return None
        duration_sec = float(duration_str)
        logger.debug(f"Successfully probed duration: {duration_sec} seconds for: {file_path}")
        return duration_sec
    except ffmpeg.Error as e:
        # stderr might contain useful info from ffmpeg
        stderr_output = e.stderr.decode('utf8') if e.stderr else 'N/A'
        logger.error(f"ffmpeg probe error for {file_path}: {e}. Stderr: {stderr_output}", exc_info=True)
        return None
    except FileNotFoundError:
        logger.error(f"FFmpeg executable not found. Please ensure ffmpeg is installed and in your PATH.")
        return None
    except Exception as e:
        logger.error(f"Error probing duration for {file_path}: {e}", exc_info=True)
        return None

def create_music_video_timeline(music_data):
    """Builds an OTIO timeline for music video editing from timing data.

    Args:
        music_data (dict): Dictionary containing music timing information:
            'path' (str): Path to the primary audio file.
            'bpm' (float/int): Beats per minute (currently unused, but good context).
            'beats' (list): List of beat times in seconds.
            'downbeats' (list): List of downbeat times in seconds.
            'segments' (list): List of segment dicts {'start', 'end', 'label'}.
            Optionally can include audio metadata like sample rate if known.

    Returns:
        otio.schema.Timeline: The generated OpenTimelineIO timeline object.
                               Returns None if essential data is missing or invalid.
    """
    # --- Validation and Setup --- 
    required_keys = ['path', 'beats', 'downbeats', 'segments']
    if not all(key in music_data for key in required_keys):
        logger.error("Missing required keys in music_data: %s", required_keys)
        return None

    audio_path = music_data.get('path')
    beats = music_data.get('beats', [])
    downbeats = music_data.get('downbeats', [])
    segments = music_data.get('segments', [])

    if not audio_path or not beats or not segments:
        logger.error("Essential data missing (audio_path, beats, or segments). Cannot create timeline.")
        return None

    # Determine time rate (use audio sample rate if available, else default)
    rate = music_data.get('sample_rate', DEFAULT_RATE)
    global_start_time = otio.opentime.RationalTime(0, rate)

    # Convert beats and downbeats to RationalTime early
    try:
        beats_rt = sorted([otio.opentime.RationalTime(timing_utils.time_value(b), rate) for b in beats])
        downbeats_rt = sorted([otio.opentime.RationalTime(timing_utils.time_value(d), rate) for d in downbeats])
    except Exception as e:
        logger.error("Error converting beat/downbeat times to RationalTime: %s", e, exc_info=True)
        return None

    # --- Adjust Segment Times --- 
    adjusted_segments = timing_utils.adjust_segment_times_to_downbeats(
        segments, [db.to_seconds() for db in downbeats_rt], global_start_time
    ) # Pass original global start time

    # --- Calculate Marker-Based Duration --- 
    last_beat_rt = beats_rt[-1] if beats_rt else global_start_time
    last_adjusted_segment_end_rt = adjusted_segments[-1]['adjusted_end_time'] if adjusted_segments else global_start_time
    marker_based_duration_rt = max(last_beat_rt, last_adjusted_segment_end_rt) 
    logger.info("Calculated marker-based timeline duration: %s (%.3f sec) at rate %s", 
                marker_based_duration_rt, marker_based_duration_rt.to_seconds(), rate)

    # --- Enforce Minimum Video Frame Duration for Timeline Items ---
    # Calculate one frame duration based on the sequence rate we expect (30fps)
    # Use precise fraction 1001/30000 for 29.97
    # one_frame_video_rt = otio.opentime.RationalTime(1001, 30000) 
    one_frame_video_rt = otio.opentime.RationalTime(1, 30) # Use 1 frame at 30fps
    timeline_marker_duration_rt = marker_based_duration_rt # Start with calculated duration
    
    # If the marker duration is very short (less than one video frame), 
    # set the duration used for timeline items to exactly one video frame.
    if marker_based_duration_rt.value > 0 and marker_based_duration_rt < one_frame_video_rt:
        logger.warning("Marker-based duration (%s) is less than one video frame (%s). "
                       "Adjusting timeline item duration to one video frame to avoid FCPXML boundary errors.",
                       marker_based_duration_rt, one_frame_video_rt)
        timeline_marker_duration_rt = one_frame_video_rt
    # --- End Minimum Duration Enforcement ---

    # --- Get Actual Audio File Duration --- 
    actual_audio_duration_rt = None
    actual_duration_seconds = _get_audio_duration_ffmpeg(audio_path)
    if actual_duration_seconds is not None:
        actual_audio_duration_rt = otio.opentime.RationalTime(actual_duration_seconds * rate, rate)
        logger.info("Actual audio file duration: %s (%.3f sec) at rate %s", 
                    actual_audio_duration_rt, actual_duration_seconds, rate)
    else:
        logger.warning("Could not determine actual audio duration. Falling back to marker-based duration for available_range.")
        # Fallback to marker duration if probe fails
        actual_audio_duration_rt = marker_based_duration_rt 
        
    # Ensure we have a valid RationalTime, even if it's the fallback
    if not isinstance(actual_audio_duration_rt, otio.opentime.RationalTime):
         logger.error("Failed to obtain a valid RationalTime for audio duration. Using zero.")
         actual_audio_duration_rt = global_start_time # Zero duration

    # --- Create Timeline and Tracks --- 
    timeline_name = f"Music Arrangement - {os.path.basename(audio_path)}" 
    timeline = otio.schema.Timeline(name=timeline_name)
    timeline.global_start_time = global_start_time

    # --- Add Downbeat Markers Track --- 
    downbeat_track = otio.schema.Track(name="Downbeats", kind=otio.schema.TrackKind.Video)
    for i, db_rt in enumerate(downbeats_rt):
        if db_rt > timeline_marker_duration_rt: 
            logger.warning("Downbeat %d at %s is beyond adjusted timeline marker duration %s. Skipping marker.", i+1, db_rt, timeline_marker_duration_rt)
            continue
        downbeat_track.markers.append(otio.schema.Marker(
            name=f"Downbeat {i+1}",
            color=DOWNBEAT_COLOR,
            marked_range=otio.opentime.TimeRange(
                start_time=db_rt,
                duration=otio.opentime.RationalTime(0, rate) # Use DEFAULT_RATE
            )
        ))
    # Add a single gap to the track based on adjusted marker duration
    if timeline_marker_duration_rt.value > 0:
        downbeat_track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(
            start_time=otio.opentime.RationalTime(0, DEFAULT_VIDEO_RATE), 
            duration=timeline_marker_duration_rt # Use adjusted duration
        )))
    timeline.tracks.append(downbeat_track)

    # --- Audio Track --- 
    audio_reference = otio.schema.ExternalReference(
        target_url=audio_path,
        available_range=otio.opentime.TimeRange(global_start_time, actual_audio_duration_rt) # Use ACTUAL duration
    )
    audio_clip = otio.schema.Clip(
        name=os.path.basename(audio_path),
        media_reference=audio_reference,
        # Use ADJUSTED MARKER-BASED duration for the clip's source_range on the timeline
        source_range=otio.opentime.TimeRange(global_start_time, timeline_marker_duration_rt) 
    )
    audio_track = otio.schema.Track(name="Audio", kind=otio.schema.TrackKind.Audio)
    audio_track.append(audio_clip)
    timeline.tracks.append(audio_track)

    # --- Main Video Track (Segments) --- 
    segment_track = otio.schema.Track(name="Segments", kind=otio.schema.TrackKind.Video)
    last_clip_end_time = global_start_time # Use original rate
    for i, seg_info in enumerate(adjusted_segments):
        start_time_rt = seg_info['adjusted_start_time']
        end_time_rt = seg_info['adjusted_end_time']
        label = seg_info['label']
        original_start_rt = seg_info['original_start_time']
        original_end_rt = seg_info['original_end_time']

        # Prevent negative durations after adjustment/overlap correction
        if end_time_rt < start_time_rt:
            logger.warning("Segment '%s' has negative duration (%s -> %s) after adjustment. Skipping.", label, start_time_rt, end_time_rt)
            continue 
        duration_rt = end_time_rt - start_time_rt

        # Handle gaps before this item
        gap_duration = start_time_rt - last_clip_end_time
        if gap_duration > otio.opentime.RationalTime(0, rate):
            logger.debug("Adding gap of %s before segment '%s'", gap_duration, label)
            segment_track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=gap_duration)))
        elif gap_duration < otio.opentime.RationalTime(0, rate):
             logger.warning("Overlap detected for segment '%s'. Start time %s is before previous end %s. Segment may be truncated or misplaced.", 
                            label, start_time_rt, last_clip_end_time)
             # For now, just log. A better strategy might be needed.

        # Create Gap instead
        segment_gap = otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=duration_rt))
        segment_track.append(segment_gap)
        # Add marker TO THE TRACK
        print(f"[DEBUG] Creating segment marker '{label}' with start_time={start_time_rt} ({start_time_rt.value}) duration={duration_rt} ({duration_rt.value})") # DEBUG
        segment_track.markers.append(otio.schema.Marker(
            name=label,
            color=PLACEHOLDER_COLOR,
            marked_range=otio.opentime.TimeRange(
                start_time=start_time_rt, # Original rate
                duration=duration_rt      # Original rate (before rounding for gap)
            ),
            metadata={'original_start': str(original_start_rt), 'original_end': str(original_end_rt)} # Original rate
        ))
        last_clip_end_time = end_time_rt # Use adjusted end time

    # Final gap for segment track using ADJUSTED marker duration
    final_gap_duration = timeline_marker_duration_rt - last_clip_end_time
    if final_gap_duration > otio.opentime.RationalTime(0, rate):
        segment_track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=final_gap_duration)))
    timeline.tracks.append(segment_track)

    # --- Beat Marker Track (1/1) --- 
    beat_track = otio.schema.Track(name="Beats (1/1)", kind=otio.schema.TrackKind.Video)
    last_beat_marker_time = global_start_time # Use original rate

    # Add a gap before the first beat if it doesn't start at 0
    if beats_rt and beats_rt[0] > global_start_time:
        duration_to_first_beat = beats_rt[0] - global_start_time
        beat_track.append(otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=duration_to_first_beat)))
        last_beat_marker_time = beats_rt[0]

    # Create gaps for intervals between beats and add markers to the track
    for i in range(len(beats_rt)):
        start_beat_rt = beats_rt[i]
        
        # Calculate end time for this interval gap
        if i + 1 < len(beats_rt):
            end_beat_rt = beats_rt[i+1]
        else:
            # Last beat interval extends to the ADJUSTED end of the timeline
            end_beat_rt = timeline_marker_duration_rt
        
        # Ensure valid interval
        interval_duration_rt = end_beat_rt - start_beat_rt
        if interval_duration_rt.value < -1e-10: # Skip only if detectably negative
            logger.warning("Skipping negative duration beat interval starting at %s (duration %s)", start_beat_rt, interval_duration_rt)
            continue
        if interval_duration_rt < otio.opentime.RationalTime(0, rate):
             interval_duration_rt = otio.opentime.RationalTime(0, rate)
            
        # Create Gap instead
        beat_interval_gap = otio.schema.Gap(source_range=otio.opentime.TimeRange(duration=interval_duration_rt))
        beat_track.append(beat_interval_gap)
        # Add marker TO THE TRACK
        beat_track.markers.append(otio.schema.Marker(
            name=f"Beat {i+1}",
            color=BEAT_COLOR,
            marked_range=otio.opentime.TimeRange( # Point marker at the beat time
                start_time=start_beat_rt, # Original rate
                duration=otio.opentime.RationalTime(0, rate) # Original rate
            )
        ))
        last_beat_marker_time = end_beat_rt # Update for potential final gap
        
    # No need for a final gap check here, as the loop goes up to timeline_marker_duration_rt

    timeline.tracks.append(beat_track)

    # --- Other Subdivision Marker Tracks (Optional / Future) ---
    # Example: Adding 1/4 note markers
    # subdivision_level = 4
    # quarter_note_markers = timing_utils.calculate_subdivision_markers(beats, subdivision_level, global_start_time)
    # if quarter_note_markers:
    #     subdiv_track = otio.schema.Track(name=f"Notes (1/{subdivision_level})", kind=otio.schema.TrackKind.Video)
    #     # Create one long clip for markers for simplicity on subdivision tracks
    #     subdiv_clip_ref = otio.schema.GeneratorReference(name="Black", generator_kind="ColorBar", parameters={'color': 'black'})
    #     subdiv_clip = otio.schema.Clip(name=f"1/{subdivision_level} Markers", media_reference=subdiv_clip_ref, source_range=otio.opentime.TimeRange(duration=calculated_duration_rt))
    #     
    #     for time_tuple, label in quarter_note_markers.items():
    #         marker_time_rt = otio.opentime.RationalTime(time_tuple[0], time_tuple[1])
    #         if marker_time_rt > calculated_duration_rt: continue # Skip markers beyond duration
    #         # Add marker relative to the clip's start time (which is 0)
    #         marker_start_in_clip = marker_time_rt - global_start_time 
    #         subdiv_clip.markers.append(otio.schema.Marker(
    #             name=label,
    #             color=SUBDIVISION_COLORS[subdivision_level % len(SUBDIVISION_COLORS) -1], # Cycle through colors
    #             marked_range=otio.opentime.TimeRange(
    #                 start_time=marker_start_in_clip, 
    #                 duration=otio.opentime.RationalTime(0, rate))
    #         ))
    #     subdiv_track.append(subdiv_clip)
    #     timeline.tracks.append(subdiv_track)

    logger.info("Timeline creation complete with %d tracks.", len(timeline.tracks))
    return timeline

# Example internal helper (consider moving if it grows)
import os 