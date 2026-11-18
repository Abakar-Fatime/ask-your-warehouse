import pytest

from ayw import demo_data
from ayw.catalog import Catalog
from ayw.engine import Engine

CATALOG = "catalog/warehouse.yaml"


@pytest.fixture(scope="session")
def warehouse_dir(tmp_path_factory):
    return demo_data.build(tmp_path_factory.mktemp("wh") / "warehouse")


@pytest.fixture(scope="session")
def engine(warehouse_dir):
    e = Engine.from_warehouse(warehouse_dir)
    yield e
    e.close()


@pytest.fixture(scope="session")
def catalog():
    return Catalog.load(CATALOG)
