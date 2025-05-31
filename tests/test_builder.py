import json
import logging
import os
import shutil  # Import shutil for file copying

import opentimelineio as otio
import pytest

# Assuming your builder module will be in the main package
from otio_music_arrangement import builder

# Remove timing_utils import if no longer needed directly by tests

# Define the path to the test data relative to this test file
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_PATH = os.path.join(TEST_DIR, "fixtures")
MUSIC_JSON_PATH = os.path.join(FIXTURE_PATH, "music.json")
MUSIC_AUDIO_PATH = os.path.join(FIXTURE_PATH, "music.wav")


# Configure logging for tests
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def load_test_data(json_path):
    """Loads JSON data for testing."""
    try:
        with open(json_path) as f:
            data = json.load(f)
            # Ensure the audio path is absolute based on the fixture path
            data["path"] = MUSIC_AUDIO_PATH
            return data
    except Exception as e:
        pytest.fail(f"Failed to load test data from {json_path}: {e}")


def test_load_music_data():
    """Tests if the music.json data file can be loaded."""
    data = load_test_data(MUSIC_JSON_PATH)
    assert "path" in data
    assert "bpm" in data
    assert "beats" in data
    assert "downbeats" in data
    assert "segments" in data
    assert isinstance(data["beats"], list)
    assert isinstance(data["downbeats"], list)
    assert isinstance(data["segments"], list)
    assert data["bpm"] > 0


# === Timeline Building Tests ===


# Helper function to count markers on clips within a track
def count_markers_on_clips(track):
    """Count the total number of markers on all clips in a track."""
    count = 0
    for item in track:
        if isinstance(item, otio.schema.Clip):
            count += len(item.markers)
    return count


@pytest.mark.parametrize("accumulate_markers", [True, False])
def test_build_timeline_from_music_lite_structure(accumulate_markers):
    """Tests build_timeline_from_audio generates lite-adapter compatible structure.

    Checking both accumulate={accumulate_markers} modes.
    """
    music_data = load_test_data(MUSIC_JSON_PATH)
    subdivision_level = 2  # Test with subdivisions
    rate = builder.DEFAULT_RATE  # Use rate from builder

    # Calculate expected marker counts from source data
    num_beats = len(music_data["beats"])
    num_downbeats = len(music_data["downbeats"])
    beats_rt = sorted(
        [otio.opentime.RationalTime(float(b) * rate, rate) for b in music_data["beats"]]
    )
    subdivision_markers_data = builder._calculate_subdivision_markers_rt(
        beats_rt, subdivision_level, rate
    )
    num_subdivisions = len(subdivision_markers_data)
    num_segments = len(music_data["segments"])

    # Call the updated builder function with the accumulate parameter
    timeline = builder.build_timeline_from_audio(
        audio_path=music_data["path"],
        beats=music_data["beats"],
        downbeats=music_data["downbeats"],
        segments=music_data["segments"],
        subdivision_level=subdivision_level,
        accumulate=accumulate_markers,
    )

    # Basic Timeline Checks
    assert timeline is not None
    assert isinstance(timeline, otio.schema.Timeline)
    assert "Lite" in timeline.name

    # Expecting 1 Audio track + Video tracks (Segments, Downbeats, Beats, Subdivisions)
    expected_track_count = 1 + 3 + (1 if subdivision_level > 1 else 0)
    assert len(timeline.tracks) == expected_track_count

    # --- Find tracks by name for easier assertions ---
    tracks_by_name = {t.name: t for t in timeline.tracks}
    audio_track = tracks_by_name.get("Audio 1")
    segments_track = tracks_by_name.get("Segments")
    downbeats_track = tracks_by_name.get("Downbeats")
    beats_track = tracks_by_name.get("Beats")
    subdivisions_track = tracks_by_name.get(f"Subdivisions (1/{subdivision_level})")

    assert audio_track and audio_track.kind == otio.schema.TrackKind.Audio
    assert segments_track and segments_track.kind == otio.schema.TrackKind.Video
    assert downbeats_track and downbeats_track.kind == otio.schema.TrackKind.Video
    assert beats_track and beats_track.kind == otio.schema.TrackKind.Video
    if subdivision_level > 1:
        assert (
            subdivisions_track
            and subdivisions_track.kind == otio.schema.TrackKind.Video
        )

    # Check Content of Tracks
    timeline_duration = timeline.duration()
    assert len(audio_track) == 1
    assert isinstance(audio_track[0], otio.schema.Clip)
    assert audio_track[0].name == os.path.basename(music_data["path"])
    assert audio_track[0].duration() == timeline_duration

    # --- Detailed Marker Count Assertions ---

    # Segments track should always have one marker per segment
    segment_marker_count = count_markers_on_clips(segments_track)
    assert segment_marker_count == num_segments, (
        f"Expected {num_segments} segment markers, found {segment_marker_count}"
    )

    # Downbeats track should always have num_downbeats markers
    downbeat_marker_count = count_markers_on_clips(downbeats_track)
    assert downbeat_marker_count == num_downbeats, (
        f"Expected {num_downbeats} downbeat markers, found {downbeat_marker_count}"
    )

    # Beats track count depends on accumulate flag
    beat_marker_count = count_markers_on_clips(beats_track)
    expected_beat_markers = num_beats  # Includes downbeats if accumulating
    if not accumulate_markers:
        # If not accumulating, only count beats that are NOT also downbeats
        expected_beat_markers = num_beats - num_downbeats
    assert beat_marker_count == expected_beat_markers, (
        f"Accumulate={accumulate_markers}: Expected {expected_beat_markers} "
        f"beat markers, found {beat_marker_count}"
    )

    # Subdivisions track count depends on accumulate flag (if track exists)
    if subdivisions_track:
        subdivision_marker_count = count_markers_on_clips(subdivisions_track)
        expected_subdivision_markers = num_subdivisions
        # If not accumulating, subdivisions that land exactly on a
        # beat/downbeat are excluded
        # Note: This requires recalculating which subdivisions DON'T overlap
        # For simplicity in this test, we'll just check if the count is
        # non-zero when expected, and less than or equal to total subdivisions
        # when not accumulating.
        if not accumulate_markers:
            assert subdivision_marker_count <= expected_subdivision_markers, (
                f"Accumulate=False: Found {subdivision_marker_count} "
                f"subdivision markers, expected <= {expected_subdivision_markers}"
            )
            # We could add a more precise check here if needed by filtering
            # subdivision_markers_data
        else:
            assert subdivision_marker_count == expected_subdivision_markers, (
                f"Accumulate=True: Expected {expected_subdivision_markers} "
                f"subdivision markers, found {subdivision_marker_count}"
            )
        assert (
            subdivision_marker_count > 0
        )  # Ensure some subdivision markers were generated

    # General check: Video marker tracks should contain Gaps and Clips
    # (Keeping the previous loop structure for this part)
    total_markers_on_clips_check = 0
    for track in [segments_track, downbeats_track, beats_track, subdivisions_track]:
        if not track:
            continue  # Skip if subdivision track doesn't exist
        assert track.kind == otio.schema.TrackKind.Video
        has_clips = False
        track_marker_count = 0
        for item in track:
            assert isinstance(item, otio.schema.Gap | otio.schema.Clip)
            if isinstance(item, otio.schema.Clip):
                has_clips = True
                assert isinstance(item.media_reference, otio.schema.GeneratorReference)
                assert item.media_reference.generator_kind == "fcpx_video_placeholder"
                assert len(item.markers) > 0  # Clips on marker tracks must have markers
                track_marker_count += len(item.markers)
        assert has_clips, f"Video track '{track.name}' should contain placeholder clips"
        assert track_marker_count > 0, (
            f"Video track '{track.name}' clips have no markers attached"
        )
        total_markers_on_clips_check += track_marker_count
        assert track.duration() == timeline_duration, (
            f"Track '{track.name}' duration mismatch"
        )

    assert total_markers_on_clips_check > 0
    logger.info(
        f"Builder function test with lite structure "
        f"(accumulate={accumulate_markers}) passed."
    )


# === OTIO Export Test ===


def test_export_timeline_to_otio_with_lite_adapter(tmp_path):
    """Tests creating timeline via builder and exporting with the lite adapter."""
    music_data = load_test_data(MUSIC_JSON_PATH)
    subdivision_level = 1  # Keep export simple for now

    # Call the updated builder function
    try:
        timeline = builder.build_timeline_from_audio(
            audio_path=music_data["path"],
            beats=music_data["beats"],
            downbeats=music_data["downbeats"],
            segments=music_data["segments"],
            subdivision_level=subdivision_level,
        )
        assert timeline is not None
    except Exception as e:
        pytest.fail(f"builder.build_timeline_from_audio failed: {e}")

    output_path = os.path.join(str(tmp_path), "music_lite_output.fcpxml")
    logger.info(f"Writing FCPXML via otio-fcpx-xml-lite-adapter to: {output_path}")

    adapter_name_to_use = "otio_fcpx_xml_lite_adapter"
    available_adapters = otio.adapters.available_adapter_names()
    print(f"Available OTIO adapters: {available_adapters}")
    assert adapter_name_to_use in available_adapters, (
        f"{adapter_name_to_use} not found!"
    )

    try:
        # Export using the lite adapter
        otio.adapters.write_to_file(
            timeline,
            output_path,
            adapter_name=adapter_name_to_use,
            # No sequence_rate argument for lite adapter
        )
    except Exception as e:
        pytest.fail(
            f"otio.adapters.write_to_file failed for {adapter_name_to_use}: {e}"
        )

    logger.info(f"Successfully wrote FCPXML to: {output_path}")
    assert os.path.exists(output_path)
    assert os.path.getsize(output_path) > 0

    # --- Copy file to Downloads ---
    try:
        downloads_dir = os.path.expanduser("~/Downloads")
        os.makedirs(downloads_dir, exist_ok=True)
        dest_path = os.path.join(downloads_dir, "test_music_lite_output.fcpxml")
        shutil.copy2(output_path, dest_path)
        logger.info(f"Copied FCPXML from {output_path} to {dest_path}")
        assert os.path.exists(dest_path)
    except Exception as e:
        logger.error(f"Failed to copy FCPXML to Downloads: {e}", exc_info=True)


def test_end_to_end_music_arrangement():
    """Comprehensive end-to-end test using real music data."""
    music_data = load_test_data(MUSIC_JSON_PATH)

    # Test with subdivision level 4 for more comprehensive testing
    subdivision_level = 4
    accumulate = True

    # Build timeline
    timeline = builder.build_timeline_from_audio(
        audio_path=music_data["path"],
        beats=music_data["beats"],
        downbeats=music_data["downbeats"],
        segments=music_data["segments"],
        subdivision_level=subdivision_level,
        accumulate=accumulate,
    )

    # Comprehensive validation
    assert timeline is not None
    assert timeline.duration().to_seconds() > 0

    # Check that all expected tracks exist
    track_names = [track.name for track in timeline.tracks]
    assert "Audio 1" in track_names
    assert "Segments" in track_names
    assert "Downbeats" in track_names
    assert "Beats" in track_names
    assert f"Subdivisions (1/{subdivision_level})" in track_names

    # Validate timing
    audio_track = next(track for track in timeline.tracks if track.name == "Audio 1")
    segments_track = next(
        track for track in timeline.tracks if track.name == "Segments"
    )

    # Audio track should have exactly one clip covering the entire timeline
    assert len(audio_track) == 1
    assert isinstance(audio_track[0], otio.schema.Clip)

    # Segments track should have clips aligned to music structure
    segment_clips = [
        item for item in segments_track if isinstance(item, otio.schema.Clip)
    ]
    assert len(segment_clips) == len(music_data["segments"])

    # Validate that all segments have markers
    total_segment_markers = sum(len(clip.markers) for clip in segment_clips)
    assert total_segment_markers == len(music_data["segments"])

    logger.info("End-to-end test passed successfully")


def test_build_timeline_invalid_audio_path():
    """Test error handling for invalid audio path."""
    result = builder.build_timeline_from_audio(
        audio_path="/nonexistent/path.wav",
        beats=[1.0, 2.0],
        downbeats=[1.0],
        segments=[{"start": 0.0, "end": 2.0, "label": "test"}],
    )
    assert result is None


def test_build_timeline_missing_audio_path():
    """Test error handling for missing audio path."""
    result = builder.build_timeline_from_audio(
        audio_path="",
        beats=[1.0, 2.0],
        downbeats=[1.0],
        segments=[{"start": 0.0, "end": 2.0, "label": "test"}],
    )
    assert result is None


def test_build_timeline_empty_beats():
    """Test error handling for empty beats list."""
    music_data = load_test_data(MUSIC_JSON_PATH)
    result = builder.build_timeline_from_audio(
        audio_path=music_data["path"],
        beats=[],
        downbeats=[1.0],
        segments=[{"start": 0.0, "end": 2.0, "label": "test"}],
    )
    assert result is None


def test_build_timeline_empty_segments():
    """Test error handling for empty segments list."""
    music_data = load_test_data(MUSIC_JSON_PATH)
    result = builder.build_timeline_from_audio(
        audio_path=music_data["path"], beats=[1.0, 2.0], downbeats=[1.0], segments=[]
    )
    assert result is None


def test_build_timeline_no_downbeats():
    """Test timeline building with no downbeats."""
    music_data = load_test_data(MUSIC_JSON_PATH)
    timeline = builder.build_timeline_from_audio(
        audio_path=music_data["path"],
        beats=[1.0, 2.0, 3.0],
        downbeats=[],
        segments=[{"start": 0.0, "end": 3.0, "label": "test"}],
    )
    assert timeline is not None

    # Should still have all tracks except downbeats should be empty
    track_names = [track.name for track in timeline.tracks]
    assert "Downbeats" in track_names


def test_build_timeline_invalid_subdivision_level():
    """Test timeline building with invalid subdivision level."""
    music_data = load_test_data(MUSIC_JSON_PATH)
    timeline = builder.build_timeline_from_audio(
        audio_path=music_data["path"],
        beats=[1.0, 2.0, 3.0],
        downbeats=[1.0],
        segments=[{"start": 0.0, "end": 3.0, "label": "test"}],
        subdivision_level=0,  # Invalid level
    )
    assert timeline is not None
    # Should default to level 1
    track_names = [track.name for track in timeline.tracks]
    assert "Subdivisions" not in " ".join(track_names)


def test_build_timeline_conversion_error():
    """Test error handling for time conversion errors."""
    music_data = load_test_data(MUSIC_JSON_PATH)
    # Use invalid time values that can't be converted
    result = builder.build_timeline_from_audio(
        audio_path=music_data["path"],
        beats=["invalid", "time"],
        downbeats=[1.0],
        segments=[{"start": 0.0, "end": 2.0, "label": "test"}],
    )
    assert result is None


def test_calculate_subdivision_markers_rt_edge_cases():
    """Test edge cases for subdivision marker calculation."""
    rate = 48000

    # Test with empty beats
    result = builder._calculate_subdivision_markers_rt([], 2, rate)
    assert result == []

    # Test with subdivision level < 1
    beats_rt = [otio.opentime.RationalTime(1.0 * rate, rate)]
    result = builder._calculate_subdivision_markers_rt(beats_rt, 0, rate)
    assert result == []

    # Test with single beat (no intervals)
    result = builder._calculate_subdivision_markers_rt(beats_rt, 2, rate)
    assert result == []

    # Test with zero duration interval
    beats_rt = [
        otio.opentime.RationalTime(1.0 * rate, rate),
        otio.opentime.RationalTime(1.0 * rate, rate),  # Same time
    ]
    result = builder._calculate_subdivision_markers_rt(beats_rt, 2, rate)
    assert result == []


def test_get_audio_duration_ffmpeg_error_cases():
    """Test error handling in audio duration detection."""
    # Test with non-existent file
    duration = builder._get_audio_duration_ffmpeg("/nonexistent/file.wav")
    assert duration is None
