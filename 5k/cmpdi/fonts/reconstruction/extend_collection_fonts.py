# /// script
# requires-python = ">=3.12"
# dependencies = ["fonttools==4.68.0"]
# ///
"""Extend the reviewed AURANGA fonts to all 34 observed CMPDI symbol pairs."""

import argparse
from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
INPUT = Path(__file__).resolve().parent / "inputs"
sys.path.insert(0, str(ROOT))
import build_fonts  # noqa: E402 - load the sibling rebuild script for direct CLI use.


def fitted(
    family,
    scale=2.0,
    width_em=None,
    height_em=None,
    reason="Centred CEL outline at the established 2x source scale.",
):
    x0, y0, x1, y1 = family["bounds"]
    upm = 2000
    a = d = scale * upm / family["units_per_em"]
    if width_em is not None:
        a = width_em * upm / (x1 - x0)
    if height_em is not None:
        d = height_em * upm / (y1 - y0)
    return {
        "review_id": family["review_id"],
        "cel_codes": family["codes"],
        "source_outline_sha256": family["id"],
        "source_fonts": family["sources"],
        "affine_transform": [a, 0, 0, d, upm / 2 - a * (x0 + x1) / 2, upm / 2 - d * (y0 + y1) / 2],
        "fit": {
            "width_em": a * (x1 - x0) / upm,
            "height_em": d * (y1 - y0) / upm,
            "centre_em": [0.5, 0.5],
            "reason": reason,
        },
        "status": "reconstructed_shape",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = json.loads((INPUT / "auranga_manifest.json").read_text())
    manifest = deepcopy(base)
    families = {
        g["review_id"]: g for g in json.loads((INPUT / "available_symbols.json").read_text())
    }
    matches = json.loads((INPUT / "collection_matches.json").read_text())["rows"]
    usage = json.loads((INPUT / "collection_usage.json").read_text())
    metrics = json.loads((INPUT / "collection_metrics.json").read_text())
    if metrics["errors"]:
        raise ValueError(metrics["errors"])
    advances = {}
    for row in metrics["rows"]:
        if len(row["widths_pdf_units"]) != 1:
            raise ValueError(f"Inconsistent source advances: {row}")
        advances[(row["font"], row["character"])] = round(
            float(next(iter(row["widths_pdf_units"]))) * manifest["build"]["units_per_em"] / 1000
        )
    for row in matches:
        name, char = row["font"], row["character"]
        if len(row["candidates"]) != 1:
            raise ValueError(f"Unselected candidates for {name} {char}")
        f = families[row["candidates"][0]["review_id"]]
        if f["id"] != row["candidates"][0]["id"]:
            raise ValueError(f"Candidate outline fingerprint mismatch: {name} {char}")
        if (name, char) == ("DGNSymbols", "$"):
            glyph = deepcopy(base["fonts"]["DGNSymbols_new"]["glyphs"]["$"])
            glyph["fit"]["reason"] = (
                "Reuse the fitted distance-stone bar from DGNSymbols_new; retain this font resource's original PDF size and rotation."
            )
        elif (name, char) == ("DGNSymbols", "t"):
            glyph = fitted(
                f,
                scale=1,
                reason="Native CEL scale for the tall tree at the CMPDI 9.72 pt font size; height 5.35 pt. Tree identity is provisional.",
            )
        else:
            glyph = fitted(f)
        glyph["feature"] = row["feature"]
        glyph["mapping_status"] = row["status"]
        glyph["evidence"] = row
        manifest["fonts"][name]["glyphs"][char] = glyph
        manifest["fonts"][name]["advance_widths"][str(ord(char))] = advances[(name, char)]
    # The earlier '(' was hollow even though the latest choice calls it lined.
    # Preserve its accepted diameter and centre, changing only the fill convention.
    f = families["G123"]
    glyph = fitted(
        f,
        width_em=1,
        height_em=1,
        reason="Filled lined-well circle: preserve the previous ( diameter and centre while adopting the user-requested lined/unlined distinction.",
    )
    glyph.update(
        feature="Lined well: filled circle",
        mapping_status="user_requested_pairing",
        evidence={
            "user_statement": "for 'N' given we picked the previous one as lined well.. pick this as unlined",
            "previous_outline": "G056",
            "previous_rendering": "hollow circle",
            "paired_code": "DGNSymbols N",
            "paired_outline": "G056",
            "interpretation": "Use filled ( for lined well and hollow N for unlined well; this is not a recovered original DGN mapping.",
        },
    )
    manifest["fonts"]["DGNSymbols"]["glyphs"]["("] = glyph
    manifest["previous_open_well"] = manifest.pop("open_well")
    manifest["wells"] = {
        "lined": {"font": "DGNSymbols", "code": "(", "outline": "G123", "fill": "solid"},
        "unlined": {"font": "DGNSymbols", "code": "N", "outline": "G056", "fill": "hollow"},
        "status": "user_selected_convention",
        "original_glyphs_recovered": False,
    }
    manifest["coverage"] = (
        "All 34 font/character pairs observed in DGNSymbols and DGNSymbols_new across the 1,430-PDF CMPDI audit. This is observed character coverage, not recovery of the complete original fonts or validation of every visible occurrence."
    )
    manifest["initial_source_pdf"] = manifest.pop("source_pdf")
    manifest["collection_audit"] = {
        "pdf_count": usage["pdf_count"],
        "download_bytes": usage["download_bytes"],
        "metrics_consistent": True,
        "font_character_pairs": len(usage["rows"]),
        "source_occurrences": sum(r["count"] for r in usage["rows"]),
        "usage_input": "reconstruction/inputs/collection_usage.json",
        "metrics_input": "reconstruction/inputs/collection_metrics.json",
        "mapping_input": "reconstruction/inputs/collection_matches.json",
    }
    manifest["version"] = "2.000"
    manifest["base_variant"] = "AURANGA fits plus collection glyphs; lined/unlined well correction"
    manifest["validation"] = [
        "All 34 observed font/code pairs have nonempty glyphs",
        "Original source advances agree across the collection and are retained",
        "Exact original family and PostScript names",
        "Existing fits preserved except the documented lined-well correction",
        "Source PDF content streams remain unchanged in rendering checks",
        "Deterministic rebuild from the manifest and extracted outlines",
    ]
    needed = {g["review_id"] for r in manifest["fonts"].values() for g in r["glyphs"].values()}
    outlines = {
        "families": [families[fid] for fid in sorted(needed)],
        "qualification": "SOI_cel outline families used by the reconstructed fonts; identities and fit evidence are in manifest.json.",
    }
    (args.output / "outlines.json").write_text(json.dumps(outlines, indent=2) + "\n")
    for name, record in manifest["fonts"].items():
        record["auranga_source_occurrences"] = record["source_occurrences"]
        record["source_occurrences"] = {
            r["character"]: r["count"] for r in usage["rows"] if r["font"] == name
        }
        assert set(record["glyphs"]) == set(record["source_occurrences"])
        for char in record["glyphs"]:
            assert record["advance_widths"][str(ord(char))] == advances[(name, char)]
        record["name_records"].update(
            {
                "3": name + "-CEL-reconstruction-v2",
                "5": "Version 2.000; reconstructed",
                "10": "SOI_cel-derived reconstruction of all observed CMPDI symbol codes. See manifest.json for choices, provisional interpretations and fit evidence.",
            }
        )
        record["head_timestamps"]["modified"] = max(
            int(datetime(2026, 11, 3, tzinfo=timezone.utc).timestamp()) + 2082844800,
            base["fonts"][name]["head_timestamps"]["modified"] + 1,
        )
        path = build_fonts.build(record, families, args.output, manifest["build"])
        record["sha256"] = build_fonts.sha256(path)
        print(name, len(record["glyphs"]), path.stat().st_size, record["sha256"])
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
