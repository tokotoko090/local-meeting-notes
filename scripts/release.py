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

def assemble(manifests: list[Path], artifact_dir: Path) -> dict:
    entries = [load_manifest(path, artifact_dir) for path in manifests]
    platforms = {item["platform"] for item in entries}
    if platforms != EXPECTED or len(entries) != 2: raise ValueError(f"expected exactly {sorted(EXPECTED)}, got {sorted(platforms)}")
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
    result = subprocess.run(["gh", "release", "view", tag], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0: raise ValueError(f"release {tag} already exists; refusing to overwrite it")

def read_bundle(path: Path, manifest_dir: Path, artifact_dir: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    rebuilt = assemble([manifest_dir / "windows-manifest.json", manifest_dir / "macos-manifest.json"], artifact_dir)
    if data != rebuilt: raise ValueError("combined manifest does not match its platform manifests")
    return data

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

def main() -> int:
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    common = argparse.ArgumentParser(add_help=False); common.add_argument("--manifest-dir", type=Path, required=True); common.add_argument("--artifact-dir", type=Path, required=True)
    cmd = sub.add_parser("assemble", parents=[common]); cmd.add_argument("--output", type=Path, required=True)
    for name in ("check", "draft", "publish"):
        cmd = sub.add_parser(name, parents=[common]); cmd.add_argument("--bundle", type=Path, required=True)
        if name == "publish":
            cmd.add_argument("--windows-validation", type=Path, required=True); cmd.add_argument("--mac-validation", type=Path, required=True)
    args = parser.parse_args(); paths = [args.manifest_dir / "windows-manifest.json", args.manifest_dir / "macos-manifest.json"]
    if args.command == "assemble":
        bundle = assemble(paths, args.artifact_dir); args.output.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8"); return 0
    bundle = read_bundle(args.bundle, args.manifest_dir, args.artifact_dir); tag = f"v{bundle['version']}"; validate_tag(bundle, tag)
    if args.command == "check": return 0
    if args.command == "draft":
        ensure_absent(tag); assets = [str(args.artifact_dir / item["artifact"]) for item in bundle["artifacts"]]
        gh("release", "create", tag, *assets, str(args.bundle), "--verify-tag", "--draft", "--title", tag, "--generate-notes"); return 0
    validate_publish_source(bundle, tag)
    validate_evidence(args.windows_validation, "windows-x64", bundle); validate_evidence(args.mac_validation, "macos-arm64", bundle)
    if gh("release", "view", tag, "--json", "isDraft", "--jq", ".isDraft", capture=True) != "true": raise ValueError(f"release {tag} is absent or already public")
    verify_draft_assets(tag, bundle)
    gh("release", "edit", tag, "--draft=false", "--latest"); return 0

if __name__ == "__main__": raise SystemExit(main())
