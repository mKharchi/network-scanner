#!/usr/bin/env python3
"""
Build test update packages for Milestone F testing.

This script automates the creation of two test packages:
1. Success case: v2.0.0 with all valid files
2. Failure case: v2.0.1 with intentionally broken requirements.txt

Usage:
    python build_test_update_package.py --version 2.0.0 [--broken]
    python build_test_update_package.py --version 2.0.1 --broken
"""

import argparse
import hashlib
import json
import os
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path


def calculate_sha256(file_path: Path) -> str:
    """Calculate SHA256 hash of a file."""
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()


def build_test_package(
    version: str,
    output_dir: Path,
    broken: bool = False,
    base_app_dir: Path = None,
) -> Path:
    """
    Build a test update package.
    
    Args:
        version: Version string (e.g., "2.0.0")
        output_dir: Directory to save the .zip package
        broken: If True, create intentionally broken requirements.txt for rollback testing
        base_app_dir: Source app directory to copy from (defaults to client/app)
    
    Returns:
        Path to the created .zip package
    """
    if base_app_dir is None:
        base_app_dir = Path(__file__).parent.parent / "client" / "app"
    
    if not base_app_dir.exists():
        raise FileNotFoundError(f"Base app directory not found: {base_app_dir}")
    
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Create temporary directory for package contents
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        app_dir = tmpdir_path / "app"
        
        # Copy app directory
        print(f"  Copying app from {base_app_dir}...")
        shutil.copytree(base_app_dir, app_dir)
        
        # Update version.json
        version_json_path = app_dir / "version.json"
        version_data = {
            "version": version,
            "release_date": datetime.now().isoformat(),
            "updater_version": "1.0.0"
        }
        print(f"  Creating version.json: {version}")
        with open(version_json_path, "w") as f:
            json.dump(version_data, f, indent=2)
        
        # If broken, corrupt requirements.txt with invalid syntax
        if broken:
            req_path = app_dir / "requirements.txt"
            if req_path.exists():
                print(f"  Creating broken requirements.txt for rollback test")
                with open(req_path, "w") as f:
                    f.write("# INTENTIONALLY BROKEN FOR TESTING\n")
                    f.write("valid-package-name===INVALID_VERSION_SYNTAX_THAT_FAILS_PIP\n")
                    f.write("another-broken-package@#@#@\n")
        
        # Create marker file to verify deployment
        marker_path = app_dir / f"DEPLOYED_{version.replace('.', '_')}"
        with open(marker_path, "w") as f:
            f.write(f"This file confirms successful deployment of v{version}\n")
            f.write(f"Timestamp: {datetime.now().isoformat()}\n")
        print(f"  Created marker file: {marker_path.name}")
        
        # Calculate file hashes for manifest
        print("  Calculating file hashes...")
        file_hashes = {}
        for file_path in app_dir.rglob("*"):
            if file_path.is_file():
                rel_path = file_path.relative_to(tmpdir_path / "app")
                file_hash = calculate_sha256(file_path)
                file_hashes[str(rel_path).replace("\\", "/")] = file_hash
        
        # Create manifest.json
        manifest = {
            "version": version,
            "package_type": "client-update",
            "minimum_updater_version": "1.0.0",
            "file_hashes": file_hashes,
            "release_notes": f"Test update package v{version}" + (" (BROKEN FOR TESTING)" if broken else ""),
            "build_timestamp": datetime.now().isoformat(),
        }
        manifest_path = tmpdir_path / "manifest.json"
        with open(manifest_path, "w") as f:
            json.dump(manifest, f, indent=2)
        print(f"  Created manifest.json")
        
        # Create zip package
        zip_filename = f"client-update-{version}.zip"
        zip_path = output_dir / zip_filename
        
        print(f"  Creating zip archive: {zip_path.name}")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for root, dirs, files in os.walk(tmpdir_path):
                for file in files:
                    file_path = Path(root) / file
                    arcname = file_path.relative_to(tmpdir_path)
                    zf.write(file_path, arcname)
        
        zip_size_mb = zip_path.stat().st_size / (1024 * 1024)
        print(f"  ✓ Package created: {zip_path} ({zip_size_mb:.2f} MB)")
        
        return zip_path


def main():
    parser = argparse.ArgumentParser(
        description="Build test update packages for Milestone F testing"
    )
    parser.add_argument(
        "--version",
        required=True,
        help="Version string (e.g., 2.0.0, 2.0.1)"
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).parent.parent / "test_packages",
        help="Output directory for packages (default: ./test_packages/)"
    )
    parser.add_argument(
        "--base-app-dir",
        type=Path,
        help="Source app directory to copy from (default: ./client/app/)"
    )
    parser.add_argument(
        "--broken",
        action="store_true",
        help="Create intentionally broken package for rollback testing"
    )
    
    args = parser.parse_args()
    
    print(f"\n{'='*60}")
    print(f"Building test update package v{args.version}")
    print(f"Broken: {args.broken}")
    print(f"Output dir: {args.output_dir}")
    print(f"{'='*60}\n")
    
    try:
        zip_path = build_test_package(
            version=args.version,
            output_dir=args.output_dir,
            broken=args.broken,
            base_app_dir=args.base_app_dir,
        )
        
        print(f"\n✓ SUCCESS: Package ready at:")
        print(f"  {zip_path}")
        print(f"\nNext steps:")
        print(f"  1. Upload package to server:")
        print(f"     curl -X POST http://SERVER_IP:8080/api/v1/packages/upload \\")
        print(f"          -H 'X-Package-Filename: client-update-{args.version}.zip' \\")
        print(f"          --data-binary @{zip_path}")
        print(f"\n  2. Create UPDATE_CLIENT action on server with returned package_id")
        print(f"  3. Monitor update on test client\n")
        
    except Exception as e:
        print(f"\n✗ ERROR: {e}", file=__import__("sys").stderr)
        return 1
    
    return 0


if __name__ == "__main__":
    exit(main())
