import pytest

from eighty_two_o.data.repository import Dataset, load_dataset


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    """The real bundled dataset, loaded once per test run."""
    return load_dataset()
