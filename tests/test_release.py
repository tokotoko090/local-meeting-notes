import json, tempfile, unittest
from pathlib import Path
from scripts.release import assemble
from scripts.release_manifest import create_manifest

SHA = "b" * 40

class ReleaseTests(unittest.TestCase):
    def make(self, root, platform, name, version="0.3.0", source=SHA):
        artifact = root / name; artifact.write_bytes(platform.encode())
        path = root / f"{platform}.json"; path.write_text(json.dumps(create_manifest(artifact, platform, source, version)), encoding="utf-8")
        return path

    def test_assemble_requires_two_matching_platforms(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bundle = assemble([self.make(root, "windows-x64", "LocalMeetingNotesSetup-0.3.0.exe"), self.make(root, "macos-arm64", "LocalMeetingNotes-0.3.0-macOS-arm64.zip")], root)
            self.assertEqual(bundle["version"], "0.3.0"); self.assertEqual(len(bundle["artifacts"]), 2)

    def test_assemble_rejects_different_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifests = [self.make(root, "windows-x64", "LocalMeetingNotesSetup-0.3.0.exe"), self.make(root, "macos-arm64", "LocalMeetingNotes-0.3.0-macOS-arm64.zip", source="c" * 40)]
            with self.assertRaisesRegex(ValueError, "same version and source"): assemble(manifests, root)

if __name__ == "__main__": unittest.main()
