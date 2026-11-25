"""Fetch the published inputs, or check rebuilt COGs against the release."""

import argparse
import csv
import hashlib
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

MANIFEST = Path(__file__).with_name("release") / "files.csv"
BASE = "https://github.com/ramSeraph/india_topo_maps/releases/download"


def files():
    with MANIFEST.open(newline="") as stream:
        return {Path(r["path"]): r for r in csv.DictReader(stream)}


def url(path, row):
    return f"{BASE}/{row['release']}/{quote(path.name)}"


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ensure(path_and_row):
    path, row = path_and_row
    if path.exists():
        if sha256(path) != row["sha256"]:
            raise ValueError(
                f"{path} differs from the release. Move it aside to fetch a fresh copy."
            )
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    retry = Retry(total=4, backoff_factor=1, status_forcelist=(429, 500, 502, 503, 504))
    with requests.Session() as session:
        session.mount("https://", HTTPAdapter(max_retries=retry))
        with session.get(url(path, row), stream=True, timeout=(15, 120)) as response:
            response.raise_for_status()
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as out:
                tmp = Path(out.name)
                try:
                    for chunk in response.iter_content(1024 * 1024):
                        out.write(chunk)
                    out.flush()
                    if sha256(tmp) != row["sha256"]:
                        raise ValueError(f"Download checksum mismatch for {path}")
                    os.replace(tmp, path)
                finally:
                    tmp.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("fetch", "verify-cogs"))
    parser.add_argument("names", nargs="*", help="Optional original or COG basenames")
    parser.add_argument("-j", type=int, default=4)
    args = parser.parse_intermixed_args()
    directory = "data" if args.operation == "fetch" else "georef"
    rows = {p: r for p, r in files().items() if p.parts[0] == directory}
    names = set(args.names)
    if unknown := names.difference(p.name for p in rows):
        parser.error(f"Unknown release files: {sorted(unknown)}")
    selected = [
        (p, r)
        for p, r in rows.items()
        if not names or p.name in names or p.parent == Path("data")
    ]
    if args.operation == "fetch":
        with ThreadPoolExecutor(max_workers=args.j) as pool:
            list(pool.map(ensure, selected))
    else:
        for p, r in selected:
            if sha256(p) != r["sha256"]:
                raise ValueError(f"COG differs from the release: {p}")
    print(f"Verified {len(selected)} files.")
