import json, tempfile, unittest
from pathlib import Path
from scripts.release_manifest import create_manifest, load_manifest

SHA = "a" * 40

class ManifestTests(unittest.TestCase):
    def test_create_and_verify(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); artifact = root / "LocalMeetingNotesSetup-1.2.3.exe"; artifact.write_bytes(b"release")
            data = create_manifest(artifact, "windows-x64", SHA, "1.2.3")
            manifest = root / "manifest.json"; manifest.write_text(json.dumps(data), encoding="utf-8")
            self.assertEqual(load_manifest(manifest, root), data)
            self.assertEqual(data["artifact"], "LocalMeetingNotesSetup-1.2.3.exe")

    def test_changed_artifact_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); artifact = root / "LocalMeetingNotesSetup-1.0.0.exe"; artifact.write_bytes(b"one")
            manifest = root / "manifest.json"; manifest.write_text(json.dumps(create_manifest(artifact, "windows-x64", SHA, "1.0.0")), encoding="utf-8")
            artifact.write_bytes(b"two")
            with self.assertRaisesRegex(ValueError, "hash mismatch"): load_manifest(manifest, root)

if __name__ == "__main__": unittest.main()
