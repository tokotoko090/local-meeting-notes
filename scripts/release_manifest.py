#!/usr/bin/env python3
from __future__ import annotations
import argparse, hashlib, json, re, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLATFORMS = {"windows-x64", "macos-arm64"}
SHA_RE = re.compile(r"^[0-9a-f]{40}$")

def package_version(root: Path = ROOT) -> str:
    return json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]

def git_head(root: Path = ROOT) -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip().lower()

def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()

def create_manifest(artifact: Path, platform: str, source_commit: str, version: str) -> dict:
    if not artifact.is_file(): raise ValueError(f"artifact does not exist: {artifact}")
    source_commit = source_commit.lower()
    if platform not in PLATFORMS: raise ValueError(f"unsupported platform: {platform}")
    if not SHA_RE.fullmatch(source_commit): raise ValueError("source commit must be a full 40-character SHA")
    return {"schema_version": 1, "version": version, "source_commit": source_commit,
            "platform": platform, "artifact": artifact.name, "sha256": sha256(artifact),
            "size": artifact.stat().st_size}

def load_manifest(path: Path, artifact_dir: Path | None = None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    required = {"schema_version", "version", "source_commit", "platform", "artifact", "sha256", "size"}
    if set(data) != required or data["schema_version"] != 1: raise ValueError(f"invalid manifest schema: {path}")
    if data["platform"] not in PLATFORMS or not SHA_RE.fullmatch(data["source_commit"]): raise ValueError(f"invalid manifest values: {path}")
    expected_name = (f"LocalMeetingNotesSetup-{data['version']}.exe" if data["platform"] == "windows-x64"
                     else f"LocalMeetingNotes-{data['version']}-macOS-arm64.zip")
    if data["artifact"] != expected_name or Path(data["artifact"]).name != data["artifact"]:
        raise ValueError(f"unexpected artifact name: {data['artifact']}")
    if artifact_dir is not None:
        artifact = artifact_dir / data["artifact"]
        if not artifact.is_file() or sha256(artifact) != data["sha256"]: raise ValueError(f"artifact hash mismatch: {artifact}")
        if artifact.stat().st_size != data["size"]: raise ValueError(f"artifact size mismatch: {artifact}")
    return data

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create"); create.add_argument("--artifact", type=Path, required=True)
    create.add_argument("--platform", choices=sorted(PLATFORMS), required=True); create.add_argument("--source-commit")
    create.add_argument("--version"); create.add_argument("--output", type=Path, required=True)
    verify = sub.add_parser("verify"); verify.add_argument("manifest", type=Path); verify.add_argument("--artifact-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "create":
        manifest = create_manifest(args.artifact, args.platform, args.source_commit or git_head(), args.version or package_version())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    else: load_manifest(args.manifest, args.artifact_dir)
    return 0

if __name__ == "__main__": raise SystemExit(main())
