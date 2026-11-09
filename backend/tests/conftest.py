from pathlib import Path

import pytest

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


@pytest.fixture
def samples_dir() -> Path:
    return SAMPLES


def read_sample(name: str) -> bytes:
    return (SAMPLES / name).read_bytes()
