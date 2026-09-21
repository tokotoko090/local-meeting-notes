import json, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from scripts.release import assemble, validate_evidence, validate_publish_source, validate_tag, verify_draft_assets
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

    def test_assemble_rejects_missing_platform(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = self.make(root, "windows-x64", "LocalMeetingNotesSetup-0.3.0.exe")
            with self.assertRaisesRegex(ValueError, "expected exactly"): assemble([manifest], root)

    def test_valid_evidence_is_accepted(self):
        bundle = {"version": "0.3.0", "source_commit": SHA}
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "windows.json"
            evidence.write_text(json.dumps({"status": "passed", "platform": "windows-x64", "version": "0.3.0", "source_commit": SHA}), encoding="utf-8")
            validate_evidence(evidence, "windows-x64", bundle)

    def test_invalid_evidence_fields_are_rejected(self):
        bundle = {"version": "0.3.0", "source_commit": SHA}
        valid = {"status": "passed", "platform": "windows-x64", "version": "0.3.0", "source_commit": SHA}
        cases = {
            "pending": {**valid, "status": "pending"},
            "version": {**valid, "version": "0.2.9"},
            "source": {**valid, "source_commit": "c" * 40},
            "platform": {**valid, "platform": "macos-arm64"},
        }
        with tempfile.TemporaryDirectory() as directory:
            evidence = Path(directory) / "evidence.json"
            for name, data in cases.items():
                with self.subTest(name=name):
                    evidence.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "invalid validation evidence"):
                        validate_evidence(evidence, "windows-x64", bundle)

    @patch("scripts.release.git")
    def test_mismatched_tag_is_rejected(self, git_mock):
        git_mock.return_value = "c" * 40
        with self.assertRaisesRegex(ValueError, "not pinned"):
            validate_tag({"source_commit": SHA}, "v0.3.0")

    @patch("scripts.release.subprocess.run")
    @patch("scripts.release.git")
    def test_mismatched_master_tree_is_rejected(self, git_mock, run_mock):
        # tag commit, origin/master commit, master tree, source tree
        git_mock.side_effect = [SHA, "c" * 40, "tree-master", "tree-source"]
        with self.assertRaisesRegex(ValueError, "master is neither"):
            validate_publish_source({"source_commit": SHA}, "v0.3.0")
        run_mock.assert_called_once()

    @patch("scripts.release.gh")
    def test_changed_downloaded_asset_is_rejected(self, gh_mock):
        bundle = {"artifacts": [{"artifact": "LocalMeetingNotesSetup-0.3.0.exe", "sha256": "0" * 64}]}
        def fake_download(*args, **kwargs):
            target = Path(args[args.index("--dir") + 1])
            (target / "LocalMeetingNotesSetup-0.3.0.exe").write_bytes(b"changed")
            return ""
        gh_mock.side_effect = fake_download
        with self.assertRaisesRegex(ValueError, "draft asset hash mismatch"):
            verify_draft_assets("v0.3.0", bundle)

if __name__ == "__main__": unittest.main()
