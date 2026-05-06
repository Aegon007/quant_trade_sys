import unittest


class ShareUtilsTests(unittest.TestCase):
    def test_normalize_share_quantity_rounds_to_three_decimals(self):
        from share_utils import normalize_share_quantity

        self.assertEqual(normalize_share_quantity(0.1236), 0.124)
        self.assertEqual(normalize_share_quantity(1), 1.0)

    def test_validate_share_quantity_rejects_values_below_minimum(self):
        from share_utils import validate_share_quantity

        with self.assertRaises(ValueError):
            validate_share_quantity(0.0009)

    def test_format_share_quantity_uses_three_decimals(self):
        from share_utils import format_share_quantity

        self.assertEqual(format_share_quantity(1), "1.000")
        self.assertEqual(format_share_quantity(0.125), "0.125")


if __name__ == "__main__":
    unittest.main()

