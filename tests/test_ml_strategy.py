import unittest

import pandas as pd

from tests.support import clear_modules, install_fake_yfinance, reload_module


class CreateTargetTests(unittest.TestCase):
    def setUp(self):
        install_fake_yfinance()
        clear_modules("strategies.ml_utils")
        self.ml_strategy = reload_module("strategies.ml_utils")

    def test_create_target_marks_tail_rows_as_unknown(self):
        dataframe = pd.DataFrame({"Close": [10, 11, 12, 13, 14]})

        target = self.ml_strategy.create_target(dataframe, horizon=2)

        self.assertEqual(target.iloc[:3].tolist(), [1.0, 1.0, 1.0])
        self.assertTrue(target.iloc[-2:].isna().all())


if __name__ == "__main__":
    unittest.main()
