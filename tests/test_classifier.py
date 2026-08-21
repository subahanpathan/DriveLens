import unittest

from drivelens.classifier import classify
from drivelens.models import Category, ItemKind


class ClassifierTests(unittest.TestCase):
    def test_windows_system_is_blocked(self):
        result = classify(r"C:\Windows\System32\kernel32.dll", ItemKind.FILE, 100)
        self.assertEqual(result.category, Category.WINDOWS_SYSTEM)
        self.assertEqual(result.can_delete, "NO")
        self.assertTrue(result.is_protected)

    def test_downloaded_document_is_reviewable(self):
        result = classify(r"C:\Users\Alex\Downloads\invoice.pdf", ItemKind.FILE, 1000)
        self.assertEqual(result.category, Category.DOWNLOADED)
        self.assertEqual(result.can_delete, "YES")

    def test_double_extension_is_suspicious(self):
        result = classify(r"C:\Users\Alex\Downloads\invoice.pdf.exe", ItemKind.FILE, 1000)
        self.assertEqual(result.category, Category.SUSPICIOUS)
        self.assertEqual(result.can_delete, "REVIEW")

    def test_unknown_explains_lack_of_evidence(self):
        result = classify(r"C:\misc\thing.bin", ItemKind.FILE, 1000)
        self.assertEqual(result.category, Category.UNKNOWN)
        self.assertIn("Unknown", result.reason)


if __name__ == "__main__":
    unittest.main()