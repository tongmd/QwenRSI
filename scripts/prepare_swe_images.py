"""Materialize the official SWE-bench images for the DGM initial subset using crane."""

import argparse
import fcntl
import hashlib
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from qwenrsi.swebench import INITIAL


def fetch_layer(crane, cache, image, layer):
    digest = layer["digest"]
    cached = cache / digest
    with cached.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if cached.is_file() and cached.stat().st_size == layer["size"]:
            return
        pending = cached.with_suffix(".partial")
        print("Downloading", image, digest, flush=True)
        try:
            with pending.open("wb") as stream:
                subprocess.run([crane, "blob", f"{image}@{digest}"], stdout=stream, timeout=1200, check=True)
            checksum = hashlib.sha256()
            with pending.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    checksum.update(chunk)
            if pending.stat().st_size != layer["size"] or f"sha256:{checksum.hexdigest()}" != digest:
                raise RuntimeError(f"Downloaded layer does not match the manifest: {digest}")
            pending.replace(cached)
        finally:
            pending.unlink(missing_ok=True)


def prepare(crane, output, instance):
    folder = output / instance
    if (folder / "image.json").is_file():
        return
    folder.mkdir(exist_ok=True)
    root = folder / "rootfs"
    root.mkdir(exist_ok=True)
    image = f"swebench/sweb.eval.x86_64.{instance.replace('__', '_1776_')}"
    digest = subprocess.check_output(
        [crane, "digest", "--platform", "linux/amd64", f"{image}:latest"], text=True, timeout=90
    ).strip()
    reference = f"{image}@{digest}"
    print(instance, reference, flush=True)
    archive = folder / "image.tar"
    manifest = json.loads(subprocess.check_output([crane, "manifest", reference], text=True, timeout=90))
    if "manifests" in manifest:
        digest = next(
            entry["digest"]
            for entry in manifest["manifests"]
            if entry.get("platform", {}).get("architecture") == "amd64"
            and entry["platform"].get("os") == "linux"
        )
        reference = f"{image}@{digest}"
        manifest = json.loads(subprocess.check_output([crane, "manifest", reference], text=True, timeout=90))
    cache = output / "layers"
    # Start the instance-specific layers first so workers share downloads without
    # blocking one another on the common layers.
    for layer in reversed(manifest["layers"]):
        fetch_layer(crane, cache, image, layer)
    subprocess.run([crane, "pull", "-c", str(cache), reference, str(archive)], timeout=240, check=True)
    with archive.open("rb") as image_input:
        exporter = subprocess.Popen([crane, "export", "-", "-"], stdin=image_input, stdout=subprocess.PIPE)
        try:
            with exporter.stdout as stream:
                subprocess.run(
                    ["tar", "--no-same-owner", "--no-same-permissions", "-xf", "-", "-C", str(root)],
                    stdin=stream,
                    timeout=180,
                    check=True,
                )
            if exporter.wait(timeout=10):
                raise RuntimeError(f"Image export failed for {instance}")
        finally:
            if exporter.poll() is None:
                exporter.kill()
                exporter.wait()
    if not (root / "testbed/.git").is_dir():
        raise RuntimeError(f"Invalid SWE-bench root filesystem for {instance}")
    receipt = folder / "image.json.tmp"
    receipt.write_text(
        json.dumps({"instance_id": instance, "image": reference}, indent=2) + "\n"
    )
    receipt.replace(folder / "image.json")
    archive.unlink()
    print(instance, "ready", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--crane", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "layers").mkdir(exist_ok=True)
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        list(
            pool.map(
                lambda instance: prepare(str(args.crane.resolve()), args.out.resolve(), instance), INITIAL
            )
        )
