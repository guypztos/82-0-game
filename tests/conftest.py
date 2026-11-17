import pytest

from eighty_two_o.data.repository import Dataset, load_dataset
from eighty_two_o.sweep.repository import SweepDataset, load_sweep_dataset


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The real bundled dataset, loaded once per test run."""
    return load_dataset()


@pytest.fixture(scope="session")
def sweep_dataset() -> SweepDataset:
    """The real bundled Clean Sweep dataset, loaded once per test run."""
    return load_sweep_dataset()
