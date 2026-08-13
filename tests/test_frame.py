import unittest

from asterisk_webhook_relay.frame import FrameError, StrictAmiFrameNormalizer


class FrameNormalizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.normalizer = StrictAmiFrameNormalizer(1024, 32)

    def test_normalizes_lf_to_one_ami_terminator(self) -> None:
        frame = self.normalizer.normalize(b"Action: Originate\nActionID: id-1\n\n")
        self.assertEqual(frame.action_id.value, "id-1")
        self.assertEqual(frame.payload, b"Action: Originate\r\nActionID: id-1\r\n\r\n")

    def test_preserves_duplicate_variable_headers(self) -> None:
        frame = self.normalizer.normalize(
            b"Action: Originate\r\nActionID: id-1\r\nVariable: one\r\nVariable: two\r\n"
        )
        self.assertIn(b"Variable: one\r\nVariable: two", frame.payload)

    def test_rejects_bare_cr_and_missing_action_id(self) -> None:
        with self.assertRaises(FrameError):
            self.normalizer.normalize(b"Action: Originate\rActionID: id-1\n")
        with self.assertRaises(FrameError):
            self.normalizer.normalize(b"Action: Originate\n")
