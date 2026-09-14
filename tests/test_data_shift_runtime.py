from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from flask import Flask

import data_shift


def write_parquet(path: Path, ticker: str = "AMT") -> None:
    frame = pd.DataFrame([
        {
            "ticker": ticker,
            "date": "2024-01-01",
            "prepared_remarks": [{"speech": ["first quarter prepared remarks"]}],
        },
        {
            "ticker": ticker,
            "date": "2024-04-01",
            "prepared_remarks": [{"speech": ["second quarter prepared remarks"]}],
        },
    ])
    frame.to_parquet(path)


class DataShiftRuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.original_env = os.environ.get("DATA_SHIFT_PARQUET")
        self._reset_cache()

    def tearDown(self) -> None:
        self._reset_cache()
        if self.original_env is None:
            os.environ.pop("DATA_SHIFT_PARQUET", None)
        else:
            os.environ["DATA_SHIFT_PARQUET"] = self.original_env
        self.tempdir.cleanup()

    @staticmethod
    def _reset_cache() -> None:
        data_shift._STRUX_DF_CACHE = None
        data_shift._STRUX_PATH_CACHE = None

    def test_env_parquet_path_loads_dataset(self) -> None:
        parquet = self.root / "fixture.parquet"
        write_parquet(parquet)
        os.environ["DATA_SHIFT_PARQUET"] = str(parquet)

        dataset, path = data_shift.load_strux_dataset()

        self.assertEqual(path, parquet)
        self.assertEqual(len(dataset), 2)
        self.assertEqual(dataset["ticker"].tolist(), ["AMT", "AMT"])
        self.assertIn("prepared_text", dataset.columns)

    def test_missing_env_parquet_path_fails_with_explainable_error(self) -> None:
        missing = self.root / "missing.parquet"
        os.environ["DATA_SHIFT_PARQUET"] = str(missing)

        with self.assertRaisesRegex(FileNotFoundError, "找不到 STRUX parquet"):
            data_shift.resolve_strux_path()

        app = Flask(__name__)
        app.register_blueprint(data_shift.data_shift_bp)
        response = app.test_client().post("/api/data-shift/auto", json={"ticker": "AMT"})

        self.assertEqual(response.status_code, 500)
        payload = response.get_json()
        self.assertFalse(payload["success"])
        self.assertIn("找不到 STRUX parquet", payload["error"])

    def test_env_path_takes_priority_over_local_fallback(self) -> None:
        env_parquet = self.root / "env.parquet"
        fallback_home = self.root / "home"
        fallback_parquet = (
            fallback_home
            / "Downloads"
            / "畢業專題"
            / "02_Data_Shift資料"
            / "train-00000-of-00001.parquet"
        )
        fallback_parquet.parent.mkdir(parents=True)
        write_parquet(env_parquet, ticker="ENV")
        write_parquet(fallback_parquet, ticker="FALLBACK")
        os.environ["DATA_SHIFT_PARQUET"] = str(env_parquet)

        with patch.object(data_shift.Path, "home", return_value=fallback_home):
            dataset, path = data_shift.load_strux_dataset()

        self.assertEqual(path, env_parquet)
        self.assertEqual(set(dataset["ticker"]), {"ENV"})


if __name__ == "__main__":
    unittest.main()
