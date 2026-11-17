import threading

from pydantic import BaseModel, ConfigDict

from eighty_two_o.store import InMemoryStore, Store


class Thing(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    value: int = 0


def test_get_and_save() -> None:
    store: Store[Thing] = InMemoryStore[Thing]()

    assert store.get("a") is None
    store.save(Thing(id="a", value=1))
    store.save(Thing(id="a", value=2))

    assert store.get("a") == Thing(id="a", value=2)


def test_oldest_saved_is_dropped() -> None:
    store = InMemoryStore[Thing](max_games=2)
    for name in ("a", "b", "c"):
        store.save(Thing(id=name))
    store.save(Thing(id="b", value=1))  # saving again makes it the newest
    store.save(Thing(id="d"))

    assert len(store) == 2
    assert store.get("a") is None
    assert store.get("c") is None
    assert store.get("b") == Thing(id="b", value=1)


def test_concurrent_saves() -> None:
    store = InMemoryStore[Thing](max_games=50)

    def save_many(prefix: str) -> None:
        for i in range(200):
            store.save(Thing(id=f"{prefix}{i}"))

    threads = [threading.Thread(target=save_many, args=(p,)) for p in "abcd"]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(store) == 50
