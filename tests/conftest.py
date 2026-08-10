"""Shared fixtures for the ClipClipper test suite (pure units, no network/API)."""
import pytest


@pytest.fixture
def heatmap():
    return [
        {"start": 0, "end": 10, "value": 0.2},
        {"start": 10, "end": 20, "value": 0.5},
        {"start": 20, "end": 30, "value": 1.0},
        {"start": 30, "end": 40, "value": 0.6},
        {"start": 40, "end": 50, "value": 0.1},
    ]


@pytest.fixture
def chapters():
    return [
        {"start": 0, "end": 15, "title": "intro"},
        {"start": 15, "end": 35, "title": "the big mistake"},
        {"start": 35, "end": 50, "title": "outro"},
    ]


@pytest.fixture
def segments():
    return [
        {"start": 0.0, "end": 2.0, "text": "hello world"},
        {"start": 2.5, "end": 5.0, "text": "the big mistake cost me fifty"},
        {"start": 5.0, "end": 8.0, "text": "nobody talks about this secret"},
        {"start": 8.0, "end": 12.0, "text": "and then everything changed"},
    ]


@pytest.fixture
def energy():
    return {
        "values": [0.1, 0.1, 0.1, 0.9, 0.1, 0.1, 0.8, 0.1, 0.1, 0.1],
        "mean": 0.2,
        "std": 0.1,
        "spikes": [3, 6],
        "pauses": [0, 1],
    }
