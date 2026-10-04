"""
test_memory_efficiency.py — memory-saving changes must not alter results or share mutable state.
"""

import io
import os
import tempfile

import numpy as np
import pandas as pd
import pytest

from core.parsing import normalise_for_parquet, parse_file, parse_to_parquet, read_parquet, write_parquet
from core.transform_engine import execute_transform


def _frame() -> pd.DataFrame:
    return pd.DataFrame({
        "region": ["N", "S", None, "E", "N"],
        "name": ["  ann ", "Bob", "cy", None, "dee"],
        "amount": [1.5, np.nan, 3.0, 4.25, 5.0],
        "qty": [1, 2, 3, 4, 5],
        "mixed": [1, "a", None, 2.5, "b"],  # object column normalise_for_parquet rewrites
        "when": pd.to_datetime(["2024-01-01", "2024-02-01", None, "2024-03-01", "2024-04-01"]),
    })


def _fingerprint(df: pd.DataFrame):
    return (list(df.columns), [str(t) for t in df.dtypes], df.astype(str).values.tolist())


ACTIONS = [
    {"action": "remove_duplicates"},
    {"action": "drop_nulls", "columns": ["region"]},
    {"action": "drop_nulls"},
    {"action": "fill_nulls", "column": "amount", "strategy": "mean"},
    {"action": "fill_nulls", "column": "region", "strategy": "constant", "fill_value": "?"},
    {"action": "normalize_text", "column": "name", "strategy": "strip"},
    {"action": "convert_type", "column": "amount", "target_type": "int"},
    {"action": "convert_type", "column": "qty", "target_type": "str"},
    {"action": "filter_rows", "column": "qty", "operator": ">", "value": 2},
    {"action": "group_aggregate", "group_by": ["region"], "aggregations": [{"column": "amount", "func": "sum"}]},
    {"action": "merge_columns", "columns": ["region", "name"], "target_column": "rn", "separator": "-"},
    {"action": "split_column", "column": "name", "target_columns": ["n1", "n2"], "delimiter": "o"},
    {"action": "rename_column", "column": "qty", "new_name": "units"},
    {"action": "drop_column", "column": "mixed"},
]


@pytest.mark.parametrize("action", ACTIONS, ids=lambda a: a["action"])
def test_transforms_never_modify_the_source_frame(action):
    df = _frame()
    before = _fingerprint(df)
    out = execute_transform(df, action)
    assert _fingerprint(df) == before  # the cached version must stay intact
    assert out is not df


def test_normalise_for_parquet_does_not_mutate_and_round_trips():
    df = _frame()
    before = _fingerprint(df)
    out = normalise_for_parquet(df)
    assert _fingerprint(df) == before
    assert out["mixed"].tolist() == ["1", "a", None, "2.5", "b"]
    buf = io.BytesIO()
    write_parquet(df, buf)
    back = read_parquet(io.BytesIO(buf.getvalue()))
    expected = pd.read_parquet(io.BytesIO(buf.getvalue()))
    pd.testing.assert_frame_equal(back, expected)  # same result as pandas' reader, lower peak memory


def test_parse_to_parquet_matches_in_memory_parse(monkeypatch, tmp_path):
    src = tmp_path / "s.csv"
    src.write_text("zip,revenue,flag\n02134,10.5,true\n10001,20,false\n")
    for subprocess_mode in ("false", "true"):
        monkeypatch.setenv("PARSE_IN_SUBPROCESS", subprocess_mode)
        out = tmp_path / f"out-{subprocess_mode}.parquet"
        meta = parse_to_parquet(src, ".csv", None, 30, out)
        df = read_parquet(out)
        assert df["zip"].tolist() == ["02134", "10001"]  # identifiers keep leading zeros
        assert df["revenue"].tolist() == [10.5, 20.0]
        assert df["flag"].tolist() == [True, False]
        assert meta["delimiter"] == ","
    direct, _ = parse_file(src, ".csv")
    pd.testing.assert_frame_equal(read_parquet(out), normalise_for_parquet(direct).reset_index(drop=True),
                                  check_dtype=False)


def test_chunked_csv_export_equals_single_pass_export(monkeypatch):
    import core.job_handlers as jh

    rng = np.random.default_rng(1)
    df = pd.DataFrame({"a": rng.random(1234).round(3), "b": rng.integers(0, 9, 1234), "c": ["x,y"] * 1234})
    df.loc[5, "a"] = np.nan
    monkeypatch.setattr(jh, "CSV_CHUNK_ROWS", 100)
    chunked = jh._df_to_bytes(df, "csv")
    monkeypatch.setattr(jh, "CSV_CHUNK_ROWS", 10_000)
    single = jh._df_to_bytes(df, "csv")
    assert chunked == single
    assert chunked.decode().count("\n") == len(df) + 1  # one header, no repeated headers
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "x.csv")
        jh.write_df_file(df, "csv", path)
        assert open(path, "rb").read() == single


def test_cell_limit_is_enforced_from_parquet_metadata_before_loading(monkeypatch, tmp_path):
    import core.file_manager as fm

    path = tmp_path / "v.parquet"
    write_parquet(pd.DataFrame({f"c{i}": range(100) for i in range(10)}), path)  # 1,000 cells
    monkeypatch.setenv("MAX_DATASET_CELLS", "999")
    loaded = []
    monkeypatch.setattr(fm, "read_parquet", lambda *a, **k: loaded.append(1))
    with pytest.raises(ValueError, match="Maximum supported cells"):
        fm.FileManager._validate_parquet_bounds(path)
    assert loaded == []
    monkeypatch.setenv("MAX_DATASET_CELLS", "1000")
    fm.FileManager._validate_parquet_bounds(path)  # exactly at the limit is fine


def test_upload_over_cell_limit_fails_with_clear_message(monkeypatch):
    from fastapi.testclient import TestClient

    import main
    from test_production_hardening import _make_user

    monkeypatch.setenv("MAX_DATASET_CELLS", "10")
    owner = _make_user()
    body = "a,b,c\n" + "".join(f"{i},{i},{i}\n" for i in range(5))  # 15 cells
    resp = TestClient(main.app).post("/upload", headers=owner["headers"],
                                     files={"file": ("big.csv", io.BytesIO(body.encode()), "text/csv")})
    assert resp.status_code == 422
    assert "cells" in resp.json()["error"] and "50 MB" not in resp.json()["error"]


PARSER_CASES = {
    "basic": "region,zip,revenue,date,flag\nN,02134,10.5,2024-01-01,true\nS,10001,20,2024-02-01,false\n,00501,,2024-03-01,\n",
    "semicolon": "name;amount;pct\nA;1.234,50 €;12%\nB;2.000,00 €;7,5%\nC;;\n",
    "quoted": 'id|note|v\n1|"hello, ""world""\nline2"|5\n2|plain|6\n3|x|7\n',
    "dup_headers": "a,a,b,,c\n1,2,3,4,5\n6,7,8,9,10\n",
    "header_only": "x,y,z\n",
    "empty_col": "a,b\n1,\n2,\n3,\n",
    "ids": "acct,amt\n0001,5\n0002,6\n0100,7\n",
    "bools": "f,g\nTRUE,yes\nfalse,no\nTrue,\n",
    "unicode": "city,v\nZürich,1\nSão Paulo,2\n東京,3\n",
}


@pytest.mark.parametrize("name", sorted(PARSER_CASES))
def test_chunked_arrow_csv_parse_matches_classic_object_parse(name, monkeypatch, tmp_path):
    """The memory-lean parser must give exactly what read_csv(dtype=str) + inference gave."""
    import core.parsing as P

    src = tmp_path / f"{name}.csv"
    src.write_bytes(PARSER_CASES[name].encode("utf-8"))
    monkeypatch.setattr(P, "CSV_READ_CHUNK_ROWS", 2)  # force several chunks

    sample = src.read_bytes()
    encoding, _ = P.detect_encoding(sample)
    delimiter = P.detect_delimiter(sample.decode(encoding))
    reference = pd.read_csv(src, sep=delimiter, encoding=encoding, dtype=str, on_bad_lines="error")
    P.infer_text_column_types(reference)
    reference = P._normalise_columns(reference)
    ref_changes = P.coerce_numeric_text(reference)

    df, meta = P.parse_file(src, ".csv")
    pd.testing.assert_frame_equal(df, reference, check_exact=True)
    assert meta["numeric_conversions"] == ref_changes

    # Parquet path keeps Arrow text in memory but must read back identically.
    out = tmp_path / "out.parquet"
    monkeypatch.setenv("PARSE_IN_SUBPROCESS", "false")
    P.parse_to_parquet(src, ".csv", None, 30, out)
    buf = io.BytesIO()
    P.write_parquet(reference, buf)
    pd.testing.assert_frame_equal(P.read_parquet(out), P.read_parquet(io.BytesIO(buf.getvalue())), check_exact=True)
    assert all(not isinstance(t, pd.StringDtype) for t in P.read_parquet(out).dtypes)


def test_committing_a_version_drops_superseded_versions_from_the_cache():
    from core.file_manager import DatasetCache

    cache = DatasetCache(max_bytes=10**9)
    df = pd.DataFrame({"a": range(10)})
    cache.put(("ds", 1), df)
    cache.put(("other", 1), df)
    cache.invalidate("ds")
    cache.put(("ds", 2), df)
    assert cache.get(("ds", 1)) is None and cache.get(("ds", 2)) is not None
    assert cache.get(("other", 1)) is not None


def test_arrow_backed_csv_read_matches_classic_read(tmp_path, monkeypatch):
    """The chunked Arrow-string reader must give exactly what read_csv(dtype=str) + inference gave."""
    import core.parsing as parsing

    text = ("region,zip,revenue,date,flag,amt\n"
            + "".join(f"R{i % 3},{i:05d},{i * 1.5},2024-01-{(i % 28) + 1:02d},{'true' if i % 2 else 'false'},\"${i},0{i % 10}\"\n"
                      for i in range(2500))
            + ",,,,,\n")
    src = tmp_path / "t.csv"
    src.write_text(text)
    monkeypatch.setattr(parsing, "CSV_READ_CHUNK_ROWS", 700)  # force several chunks

    classic = pd.read_csv(src, dtype=str)
    parsing.infer_text_column_types(classic)
    classic = parsing._normalise_columns(classic)
    conversions = parsing.coerce_numeric_text(classic)

    new, meta = parsing.parse_file(src, ".csv")
    pd.testing.assert_frame_equal(new, classic, check_exact=True)
    assert meta["numeric_conversions"] == conversions

    buf = io.BytesIO()
    parsing.write_parquet(classic, buf)
    out = tmp_path / "o.parquet"
    parsing.parse_to_parquet(src, ".csv", None, 30, out)  # keeps Arrow text internally
    pd.testing.assert_frame_equal(read_parquet(out), read_parquet(io.BytesIO(buf.getvalue())), check_exact=True)
    assert read_parquet(out)["region"].dtype == object  # readers still get classic object text
