from benchmarks.adapters.longmemeval_vector_cache import PersistentVectorCache


def test_vector_cache_round_trip_and_namespace_isolation(tmp_path):
    path = tmp_path / "vectors.sqlite3"
    first = PersistentVectorCache(path, "first")
    second = PersistentVectorCache(path, "second")

    first.put_many({"a": [0.25, 0.5, 0.75]})

    assert first.get_many(["a", "missing"])["a"] == [0.25, 0.5, 0.75]
    assert second.get_many(["a"]) == {}
