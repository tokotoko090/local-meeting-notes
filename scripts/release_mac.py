#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, plistlib
from pathlib import Path
from release_manifest import create_manifest, git_head, package_version

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "release/Local Meeting Notes-darwin-arm64/Local Meeting Notes.app"

def main() -> int:
    parser = argparse.ArgumentParser(); parser.add_argument("--source-commit"); args = parser.parse_args()
    version = package_version(); source = args.source_commit or git_head()
    if source.lower() != git_head(): raise SystemExit("source commit must equal the checked-out HEAD")
    if subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip():
        raise SystemExit("commit tracked changes before building a release")
    subprocess.run(["npm", "run", "build:mac"], cwd=ROOT, check=True)
    if git_head() != source.lower() or subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=no"], cwd=ROOT, text=True).strip():
        raise SystemExit("source changed during the build")
    with (APP / "Contents/Info.plist").open("rb") as stream:
        if plistlib.load(stream)["CFBundleShortVersionString"] != version:
            raise SystemExit("packaged app version does not match source")
    output = ROOT / "release" / f"LocalMeetingNotes-{version}-macOS-arm64.zip"
    if not APP.is_dir(): raise SystemExit(f"Mac app was not found: {APP}")
    if output.exists(): output.unlink()
    subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", APP, output], check=True)
    manifest = create_manifest(output, "macos-arm64", source, version)
    (ROOT / "release/macos-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(output); return 0

if __name__ == "__main__": raise SystemExit(main())
