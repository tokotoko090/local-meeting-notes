#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, tempfile
from pathlib import Path
try:
    from .release_manifest import load_manifest, sha256
except ImportError:
    from release_manifest import load_manifest, sha256

EXPECTED = {"windows-x64", "macos-arm64"}

def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], text=True).strip()

def assemble(manifests: list[Path], artifact_dir: Path, platforms: set[str] | None = None) -> dict:
    entries = [load_manifest(path, artifact_dir) for path in manifests]
    expected = EXPECTED if platforms is None else platforms
    actual = {item["platform"] for item in entries}
    if actual != expected or len(entries) != len(expected): raise ValueError(f"expected exactly {sorted(expected)}, got {sorted(actual)}")
    versions = {item["version"] for item in entries}; sources = {item["source_commit"] for item in entries}
    if len(versions) != 1 or len(sources) != 1: raise ValueError("both builds must have the same version and source commit")
    return {"schema_version": 1, "version": versions.pop(), "source_commit": sources.pop(),
            "artifacts": sorted(entries, key=lambda item: item["platform"])}

def validate_tag(bundle: dict, tag: str) -> None:
    source = bundle["source_commit"]
    if git("rev-parse", f"refs/tags/{tag}^{{commit}}") != source: raise ValueError(f"tag {tag} is not pinned to source commit {source}")

def validate_publish_source(bundle: dict, tag: str) -> None:
    subprocess.run(["git", "fetch", "origin", "master", f"refs/tags/{tag}:refs/tags/{tag}"], check=True)
    validate_tag(bundle, tag); source = bundle["source_commit"]
    master = git("rev-parse", "origin/master^{commit}")
    if master != source and git("rev-parse", "origin/master^{tree}") != git("rev-parse", f"{source}^{{tree}}"):
        raise ValueError("master is neither the source commit nor an identical source tree")

def gh(*args: str, capture: bool = False) -> str:
    result = subprocess.run(["gh", *args], check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else ""

def ensure_absent(tag: str) -> None:
    result = subprocess.run(["gh", "release", "view", tag], capture_output=True, text=True)
    if result.returncode == 0: raise ValueError(f"release {tag} already exists; refusing to overwrite it")
    if "release not found" not in result.stderr.lower() and "HTTP 404" not in result.stderr:
        raise RuntimeError(f"Cannot determine whether release exists: {result.stderr.strip()}")

def read_bundle(path: Path, manifest_dir: Path, artifact_dir: Path, platforms: set[str] | None = None) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = EXPECTED if platforms is None else platforms
    rebuilt = assemble(manifest_paths(manifest_dir, expected), artifact_dir, expected)
    if data != rebuilt: raise ValueError("combined manifest does not match its platform manifests")
    return data

def manifest_paths(directory: Path, platforms: set[str]) -> list[Path]:
    return [directory / ("windows-manifest.json" if platform == "windows-x64" else "macos-manifest.json") for platform in sorted(platforms)]

def validate_evidence(path: Path, platform: str, bundle: dict) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    expected = {"status": "passed", "platform": platform, "version": bundle["version"], "source_commit": bundle["source_commit"]}
    if data != expected: raise ValueError(f"invalid validation evidence: {path}")

def verify_draft_assets(tag: str, bundle: dict) -> None:
    with tempfile.TemporaryDirectory() as directory:
        target = Path(directory)
        gh("release", "download", tag, "--dir", str(target))
        for item in bundle["artifacts"]:
            downloaded = target / item["artifact"]
            if not downloaded.is_file() or sha256(downloaded) != item["sha256"]: raise ValueError(f"draft asset hash mismatch: {item['artifact']}")
            manifest_name = "windows-manifest.json" if item["platform"] == "windows-x64" else "macos-manifest.json"
            if load_manifest(target / manifest_name, target) != item:
                raise ValueError(f"draft platform manifest mismatch: {manifest_name}")
        if json.loads((target / "release-manifest.json").read_text(encoding="utf-8")) != bundle:
            raise ValueError("draft combined manifest mismatch")

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False); common.add_argument("--manifest-dir", type=Path, required=True); common.add_argument("--artifact-dir", type=Path, required=True)
    common.add_argument("--platforms", choices=("both", "windows"), default="both")
    cmd = sub.add_parser("assemble", parents=[common]); cmd.add_argument("--output", type=Path, required=True)
    for name in ("check", "draft", "publish"):
        cmd = sub.add_parser(name, parents=[common]); cmd.add_argument("--bundle", type=Path, required=True)
        if name == "publish":
            cmd.add_argument("--windows-validation", type=Path, required=True); cmd.add_argument("--mac-validation", type=Path)
    args = parser.parse_args()
    platforms = {"windows-x64"} if args.platforms == "windows" else EXPECTED
    paths = manifest_paths(args.manifest_dir, platforms)
    if args.command == "publish" and "macos-arm64" in platforms and args.mac_validation is None:
        parser.error("--mac-validation is required for both platforms")
    if args.command == "assemble":
        bundle = assemble(paths, args.artifact_dir, platforms); args.output.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8"); return 0
    bundle = read_bundle(args.bundle, args.manifest_dir, args.artifact_dir, platforms); tag = f"v{bundle['version']}"; validate_tag(bundle, tag)
    if args.command == "check": return 0
    if args.command == "draft":
        ensure_absent(tag); assets = [str(args.artifact_dir / item["artifact"]) for item in bundle["artifacts"]]
        assets += [str(path) for path in paths]
        gh("release", "create", tag, *assets, str(args.bundle), "--verify-tag", "--draft", "--title", tag, "--generate-notes"); return 0
    validate_publish_source(bundle, tag)
    validate_evidence(args.windows_validation, "windows-x64", bundle)
    if "macos-arm64" in platforms:
        validate_evidence(args.mac_validation, "macos-arm64", bundle)
    if gh("release", "view", tag, "--json", "isDraft", "--jq", ".isDraft", capture=True) != "true": raise ValueError(f"release {tag} is absent or already public")
    verify_draft_assets(tag, bundle)
    gh("release", "edit", tag, "--draft=false", "--latest"); return 0

if __name__ == "__main__": raise SystemExit(main())
