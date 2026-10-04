"""Small deterministic checks for the local privacy layer."""
import unittest

from backend.pipeline import detect_and_tokenize, restore_tokens, verify_privacy


class PrivacyPipelineTests(unittest.TestCase):
    def test_sensitive_values_are_tokenized_and_restored_locally(self):
        source = "Name: Alice Example Email: alice@example.com Phone: +1 212 555 0123"
        safe, mapping, findings = detect_and_tokenize(source)
        self.assertEqual(len(findings), 3)
        self.assertTrue(verify_privacy(safe, mapping))
        self.assertNotIn("alice@example.com", safe)
        self.assertEqual(restore_tokens(safe, mapping), source)

    def test_verification_fails_if_value_remains(self):
        safe, mapping, _ = detect_and_tokenize("Email: alice@example.com")
        self.assertFalse(verify_privacy(safe + " alice@example.com", mapping))


if __name__ == "__main__":
    unittest.main()
