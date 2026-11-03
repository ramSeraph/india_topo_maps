# /// script
# requires-python = ">=3.12"
# dependencies = ["pymupdf==2.1", "fonttools==4.68.0"]
# ///
"""Validate font coverage/metrics and render unchanged-source PDF contexts."""

import argparse
import hashlib
import json
from pathlib import Path

import pymupdf
from fontTools.ttLib import TTFont

DEFAULT_FONTS = Path(__file__).resolve().parents[1]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def repaired_copy(path, fonts_root):
    original = path.read_bytes()
    doc = pymupdf.open(stream=original, filetype="pdf")
    page_streams = {xref: doc.xref_stream(xref) for page in doc for xref in page.get_contents()}
    seen = set()
    changed = []
    for page in doc:
        for xref, _, _, name, *_ in page.get_fonts(full=True):
            if name not in ("DGNSymbols", "DGNSymbols_new") or xref in seen:
                continue
            seen.add(xref)
            data = (fonts_root / f"{name}.ttf").read_bytes()
            stream = doc.get_new_xref()
            doc.update_object(stream, "<<>>")
            doc.update_stream(stream, data)
            doc.xref_set_key(stream, "Length1", str(len(data)))
            kind, value = doc.xref_get_key(xref, "FontDescriptor")
            descriptor = doc.get_new_xref()
            doc.update_object(
                descriptor,
                doc.xref_object(int(value.split()[0]))
                if kind == "xref"
                else "<< /Type /FontDescriptor >>",
            )
            with TTFont(fonts_root / f"{name}.ttf") as font:
                head = font["head"]
                bounds = [
                    getattr(head, k) * 1000 / head.unitsPerEm
                    for k in ["xMin", "yMin", "xMax", "yMax"]
                ]
            for key, value in {
                "FontFile2": f"{stream} 0 R",
                "FontName": "/" + name,
                "FontBBox": "[" + " ".join(map(str, bounds)) + "]",
                "Ascent": "1200",
                "Descent": "-300",
                "Flags": "32",
            }.items():
                doc.xref_set_key(descriptor, key, value)
            doc.xref_set_key(xref, "FontDescriptor", f"{descriptor} 0 R")
            changed.append({"font": name, "xref": xref})
    assert changed
    assert all(doc.xref_stream(x) == v for x, v in page_streams.items())
    data = doc.tobytes()
    doc.close()
    doc = pymupdf.open(stream=data, filetype="pdf")
    assert all(doc.xref_stream(x) == v for x, v in page_streams.items())
    assert sha(path.read_bytes()) == sha(original)
    return doc, {
        "file": path.name,
        "source_sha256": sha(original),
        "font_resources": changed,
        "page_content_streams_unchanged": True,
        "source_file_unchanged": True,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fonts", type=Path, default=DEFAULT_FONTS)
    parser.add_argument(
        "--sources",
        type=Path,
        required=True,
        help="Directory of original CMPDI PDFs named in inputs/render_examples.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    fonts_root = args.fonts
    output = args.output
    output.mkdir(parents=True, exist_ok=True)
    (output / "images").mkdir(exist_ok=True)
    manifest = json.loads((fonts_root / "manifest.json").read_text())
    base = json.loads((fonts_root / "reconstruction/inputs/auranga_manifest.json").read_text())
    checks = []
    for name, record in manifest["fonts"].items():
        with TTFont(fonts_root / record["file"]) as font:
            cmap = font.getBestCmap()
            assert set(cmap) == {32} | {ord(c) for c in record["glyphs"]}
            assert font["name"].getDebugName(1) == font["name"].getDebugName(6) == name
            for char in record["glyphs"]:
                g = font["glyf"][cmap[ord(char)]]
                assert g.numberOfContours > 0, (name, char)
                assert font["hmtx"][cmap[ord(char)]][0] == record["advance_widths"][str(ord(char))]
            for char, old in base["fonts"][name]["glyphs"].items():
                if (name, char) == ("DGNSymbols", "("):
                    continue
                assert record["glyphs"][char] == old, (name, char, "unintended old-fit change")
            if name == "DGNSymbols":
                assert font["glyf"][cmap[ord("(")]].numberOfContours == 1
                assert font["glyf"][cmap[ord("N")]].numberOfContours == 2
            else:
                assert font["glyf"][cmap[ord("&")]].numberOfContours == 2
                assert font["glyf"][cmap[ord("T")]].numberOfContours == 1
        checks.append(
            {
                "font": name,
                "symbols": len(record["glyphs"]),
                "bytes": (fonts_root / record["file"]).stat().st_size,
                "sha256": sha((fonts_root / record["file"]).read_bytes()),
                "coverage_and_metrics": "pass",
                "existing_fits": "pass",
            }
        )
    rows = json.loads((fonts_root / "reconstruction/inputs/render_examples.json").read_text())
    sources = {}
    evidence = []
    report = pymupdf.open()
    for i, row in enumerate(rows, 1):
        name, char = row["font"], row["character"]
        example = row["cmpdi_example"]
        file = example["file"]
        path = args.sources / file
        if file not in sources:
            before = pymupdf.open(path)
            after, rec = repaired_copy(path, fonts_root)
            sources[file] = (before, after)
            evidence.append(rec)
        before, after = sources[file]
        page_index = example["page"] - 1
        if "clip_pt" in row:
            clip = pymupdf.Rect(row["clip_pt"])
        else:
            box = pymupdf.Rect(example["bbox_pt"])
            centre = (box.tl + box.br) / 2
            clip = (
                pymupdf.Rect(centre.x - 38, centre.y - 29, centre.x + 38, centre.y + 29)
                & before[page_index].rect
            )
        page = report.new_page(width=960, height=680)
        page.insert_text((25, 30), f'{i:02d}. {name} {char!r}: {row["feature"]}', fontsize=19)
        page.insert_text(
            (25, 55), f"{file} | Original font size/position/rotation retained", fontsize=11
        )
        for j, (label, doc) in enumerate(
            [("Original missing-font rendering", before), ("Updated standalone font", after)]
        ):
            x = 25 + j * 475
            page.insert_text((x, 90), label, fontsize=12)
            pix = doc[page_index].get_pixmap(matrix=pymupdf.Matrix(6, 6), clip=clip, alpha=False)
            dest = output / "images" / f"{i:02d}_{j}.png"
            pix.save(dest)
            page.insert_image(pymupdf.Rect(x, 110, x + 435, 585), filename=str(dest))
        glyph = manifest["fonts"][name]["glyphs"][char]
        page.insert_text(
            (25, 620),
            f'CEL {glyph["review_id"]} | ' + glyph.get("mapping_status", "reconstructed"),
            fontsize=12,
        )
        page.insert_textbox(
            pymupdf.Rect(25, 638, 935, 677),
            "Rendering check attaches fonts to an in-memory copy only. Source PDF page streams and files are unchanged. "
            "No missing-glyph fallback was used for this character.",
            fontsize=10,
        )
    for before, after in sources.values():
        before.close()
        after.close()
    report.save(output / "updated_fonts_review.pdf", deflate=True)
    report.close()
    result = {
        "fonts": checks,
        "rendered_examples": len(rows),
        "source_pdfs": evidence,
        "source_pdf_edits": 0,
        "note": "Character coverage and source advances are verified across the audit; visual fitting is sampled, and t remains provisional.",
    }
    (output / "validation.json").write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {"fonts": checks, "rendered_examples": len(rows), "source_pdfs": len(evidence)},
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
