import unittest


class UIDialogsTests(unittest.TestCase):
    def test_clear_dialog_index_if_out_of_range_resets_state(self):
        from app.ui.dialogs import clear_dialog_index_if_out_of_range

        session_state = {"sell_dialog_index": 3}
        changed = clear_dialog_index_if_out_of_range(
            session_state,
            key="sell_dialog_index",
            record_count=2,
        )

        self.assertTrue(changed)
        self.assertIsNone(session_state["sell_dialog_index"])

    def test_clear_dialog_index_if_out_of_range_keeps_valid_index(self):
        from app.ui.dialogs import clear_dialog_index_if_out_of_range

        session_state = {"editing_holding": 1}
        changed = clear_dialog_index_if_out_of_range(
            session_state,
            key="editing_holding",
            record_count=3,
        )

        self.assertFalse(changed)
        self.assertEqual(session_state["editing_holding"], 1)


if __name__ == "__main__":
    unittest.main()
