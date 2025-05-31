# OpenTimelineIO Music Arrangement

[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Tests](https://img.shields.io/badge/tests-39%20passing-green.svg)](./tests)
[![Coverage](https://img.shields.io/badge/coverage-85%25-brightgreen.svg)](./htmlcov)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Typed: mypy](https://img.shields.io/badge/typed-mypy-blue.svg)](http://mypy-lang.org/)

A production-ready Python library for building OpenTimelineIO timelines specifically tailored for music video editing workflows. Generate professional video editing timelines with precise musical timing alignment.

## Features

- 🎵 **Musical Timeline Generation**: Convert musical timing data into OTIO timelines
- 🎬 **FCPXML Export**: Direct export to Final Cut Pro via OTIO adapters
- 🎯 **Precise Alignment**: Align video segments to musical downbeats and subdivisions
- 📍 **Visual Markers**: Generate beat subdivision guides (1/1, 1/2, 1/3, 1/4 notes)
- 🔧 **Type Safe**: Full type annotations with mypy compatibility
- ✅ **Well Tested**: 85% test coverage with comprehensive edge case handling
- 📦 **Production Ready**: Professional code quality with linting and formatting

## Installation

```bash
pip install otio-music-arrangement
```

### Development Installation

```bash
git clone https://github.com/allenday/otio-music-arrangement.git
cd otio-music-arrangement
pip install -e ".[dev,test]"
```

## Quick Start

```python
from otio_music_arrangement import build_timeline_from_audio

# Create a timeline from musical timing data
timeline = build_timeline_from_audio(
    audio_path="song.wav",
    beats=[1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0],
    downbeats=[1.0, 3.0, 5.0, 7.0],
    segments=[
        {"start": 1.0, "end": 5.0, "label": "verse"},
        {"start": 5.0, "end": 9.0, "label": "chorus"}
    ],
    subdivision_level=4,  # Quarter-note subdivisions
    accumulate=True       # Show markers on all relevant tracks
)

# Export to FCPXML
import opentimelineio as otio
otio.adapters.write_to_file(timeline, "music_timeline.fcpxml")
```

## Generated Timeline Structure

The library creates a structured timeline with multiple tracks:

1. **Audio Track**: Primary music file
2. **Segments Track**: Video clips for song sections (verse, chorus, bridge, etc.)
3. **Downbeats Track**: Markers at major musical boundaries
4. **Beats Track**: Markers at each beat
5. **Subdivisions Track**: Fine-grained timing markers (optional)

Each track contains placeholder clips with precise markers aligned to musical timing.

## API Reference

### Core Functions

#### `build_timeline_from_audio()`

```python
def build_timeline_from_audio(
    audio_path: str,
    beats: list[float | int],
    downbeats: list[float | int],
    segments: list[dict[str, Any]],
    subdivision_level: int = 1,
    accumulate: bool = False,
) -> otio.schema.Timeline | None
```

**Parameters:**
- `audio_path`: Path to the primary audio file
- `beats`: List of beat times in seconds
- `downbeats`: List of downbeat times in seconds  
- `segments`: List of segment dictionaries with 'start', 'end', 'label' keys
- `subdivision_level`: Beat subdivision level (1=none, 2=half-notes, 4=quarter-notes)
- `accumulate`: Whether markers appear on multiple tracks or just the most specific

**Returns:** OpenTimelineIO Timeline object ready for export

### Utility Functions

#### `adjust_segment_times_to_downbeats()`

Aligns segment boundaries to the nearest downbeats for musical accuracy.

#### `calculate_subdivision_markers()`

Generates precise subdivision timing markers between beats.

## Development

### Requirements

- Python 3.10+
- OpenTimelineIO >= 0.15
- FFmpeg (for audio probing)

### Setup Development Environment

```bash
# Clone repository
git clone https://github.com/allenday/otio-music-arrangement.git
cd otio-music-arrangement

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install with development dependencies
pip install -e ".[dev,test]"

# Install pre-commit hooks
pre-commit install
```

### Running Tests

```bash
# Run all tests with coverage
pytest tests/ --cov=src/otio_music_arrangement --cov-report=html

# Run specific test file
pytest tests/test_builder.py -v

# Run with real music data
pytest tests/test_builder.py::test_end_to_end_with_real_music_data -v
```

### Code Quality

```bash
# Run linting
ruff check src/ tests/

# Format code
ruff format src/ tests/

# Type checking
mypy src/

# Run all quality checks
ruff check src/ tests/ && mypy src/ && pytest tests/ --cov=src/otio_music_arrangement
```

### Building Package

```bash
python -m build
```

## Project Structure

```
otio-music-arrangement/
├── src/otio_music_arrangement/    # Source code
│   ├── __init__.py               # Package interface
│   ├── builder.py                # Timeline building logic
│   └── timing_utils.py           # Musical timing utilities
├── tests/                        # Test suite (85% coverage)
│   ├── fixtures/                 # Test data (music files)
│   ├── test_builder.py           # Timeline builder tests
│   └── test_timing_utils.py      # Timing utilities tests
├── htmlcov/                      # Coverage reports
├── pyproject.toml                # Project configuration
└── README.md                     # This file
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Make your changes with tests
4. Ensure all tests pass and coverage remains high
5. Run code quality checks (`ruff check`, `mypy src/`)
6. Commit your changes (`git commit -m 'Add amazing feature'`)
7. Push to the branch (`git push origin feature/amazing-feature`)
8. Open a Pull Request

## Testing

The project includes comprehensive tests with real music data:

- **Unit Tests**: Individual function testing
- **Integration Tests**: Full workflow validation  
- **Error Handling**: Edge cases and invalid input testing
- **Real Data Tests**: Using actual music files (`tests/fixtures/`)

Test coverage is maintained at 85%+ with detailed HTML reports.

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built on [OpenTimelineIO](https://github.com/PixarAnimationStudios/OpenTimelineIO)
- Uses [otio-fcpx-xml-lite-adapter](https://github.com/markreidvfx/otio-fcpx-xml-lite) for FCPXML export
- Music timing analysis powered by [librosa](https://librosa.org/)

## Technical Approach

**Core Technology:** Uses the `opentimelineio` library for timeline structure and time conversions with RationalTime precision.

**Music Timing Logic:** Dedicated utility functions handle musical calculations like aligning segments to downbeats and calculating subdivision timings.

**Timeline Building:** Creates OTIO `Timeline`, `Track`, `Clip`, and `Marker` objects based on musical timing data.

**Export Ready:** Direct export to FCPXML and other NLE formats via OTIO adapters.
