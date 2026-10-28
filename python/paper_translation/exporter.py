"""Conservative, vector-preserving PDF reflow. No translation service is called."""
from __future__ import annotations
import hashlib
import math
import os
from pathlib import Path
import re
import tempfile
import unicodedata

import fitz

# Basic CJK kinsoku constraints. These apply at automatic wraps, not explicit newlines.
NO_LINE_START = frozenset("，。、；：！？）》】〕〉」』”’％‰…,.!?;:)]}")
NO_LINE_END = frozenset("（《【〔〈「『“‘([{")

TOKEN = re.compile(r"\{\{[A-Z]+_[A-Za-z0-9]+\}\}")
LANGUAGES = {
    "en", "english", "英语", "zh", "zh-cn", "zh-hans", "zh-tw", "zh-hant",
    "chinese", "中文", "简体中文", "繁体中文", "ja", "japanese", "日语",
    "ko", "korean", "韩语", "de", "german", "德语", "fr", "french", "法语",
    "es", "spanish", "西班牙语", "it", "italian", "pt", "portuguese",
}


def fail(code, message):
    raise ValueError(f"{code}: {message}")


def validate_language(language):
    if not isinstance(language, str) or language.strip().lower() not in LANGUAGES:
        fail("TARGET_LANGUAGE_UNSUPPORTED", "Supported targets: English, Chinese, Japanese, Korean, German, French, Spanish, Italian, Portuguese.")


def _digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _clean_region(source, item):
    """Remove off-region text, image pixels and wholly outside vectors before reuse."""
    index = int(item["page"]) - 1
    page = source[index]
    if page.rotation:
        fail("LAYOUT_UNSUPPORTED", "Rotated asset pages require a normalized parser coordinate system.")
    rect = fitz.Rect(item["bbox"])
    if rect.is_empty or rect.is_infinite or not page.rect.contains(rect):
        fail("LAYOUT_UNSUPPORTED", "Invalid asset boundary.")
    # Removing a partial glyph changes appearance; treat it as a boundary error.
    for block in page.get_text("rawdict")["blocks"]:
        for line in block.get("lines", []):
            for span in line["spans"]:
                for char in span["chars"]:
                    cr = fitz.Rect(char["bbox"])
                    intersection = cr & rect
                    if not intersection.is_empty and not rect.contains(cr):
                        fail("OUTPUT_VALIDATION_FAILED", f"Asset boundary cuts a character on page {index + 1}.")
    clean = fitz.open()
    clean.insert_pdf(source, from_page=index, to_page=index, links=False, annots=False)
    cp = clean[0]
    bounds = cp.rect
    outside = [fitz.Rect(bounds.x0, bounds.y0, bounds.x1, rect.y0),
               fitz.Rect(bounds.x0, rect.y1, bounds.x1, bounds.y1),
               fitz.Rect(bounds.x0, rect.y0, rect.x0, rect.y1),
               fitz.Rect(rect.x1, rect.y0, bounds.x1, rect.y1)]
    for r in outside:
        if not r.is_empty:
            cp.add_redact_annot(r, fill=False, cross_out=False)
    cp.apply_redactions(images=2, graphics=1, text=0)
    # Round-trip drops unreachable original streams and resources.
    sanitized = fitz.open(stream=clean.tobytes(garbage=4, deflate=True), filetype="pdf")
    clean.close()
    a = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
    b = sanitized[0].get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
    if a.width != b.width or a.height != b.height or a.samples != b.samples:
        sanitized.close()
        fail("OUTPUT_VALIDATION_FAILED", f"Sanitization changed the asset appearance on page {index + 1}.")
    for block in sanitized[0].get_text("dict")["blocks"]:
        if block.get("type") == 0 and not (fitz.Rect(block["bbox"]) & rect):
            sanitized.close()
            fail("OUTPUT_VALIDATION_FAILED", "Off-region searchable source text survived sanitization.")
    return sanitized, rect


def export_pdf(source_path, blocks, translations, target_language, destination, config):
    """Export atomically; failure leaves no final PDF. All page numbers are 1-based."""
    validate_language(target_language)
    source_path, destination = Path(source_path).resolve(), Path(destination).resolve()
    if source_path == destination or destination.exists():
        fail("OUTPUT_PATH_CONFLICT", "Destination must be a new file distinct from the source.")
    digest_before = _digest(source_path)
    size = float(config.get("fontSize", 11))
    margin = float(config.get("pageMargin", 48))
    if not math.isfinite(size) or not 8 <= size <= 24 or not math.isfinite(margin) or not 20 <= margin <= 100:
        fail("LAYOUT_UNSUPPORTED", "fontSize must be 8–24 and pageMargin 20–100 points.")
    font_path = config.get("fontPath")
    font = fitz.Font(fontfile=font_path) if font_path else fitz.Font("cjk")
    output = fitz.open()
    source = fitz.open(source_path)
    assets = []
    placed = []
    warnings = []
    current = None
    y = margin
    temp = None
    text_count = 0
    expected_asset_count = sum(len(b.get("sources", [])) for b in blocks if b.get("type") in ("asset", "figure", "table", "equation"))

    def new_page(width=595.276, height=841.89):
        nonlocal current, y
        if width > 14400 or height > 14400:
            fail("LAYOUT_UNSUPPORTED", "Asset exceeds the supported PDF page size.")
        current = output.new_page(width=width, height=height)
        current.insert_font(fontname="PaperFont", fontbuffer=font.buffer)
        y = margin

    def enough(height):
        if current is None or y + height > current.rect.height - margin:
            new_page()

    def add_asset(item, block_id):
        nonlocal y
        sanitized, rect = _clean_region(source, item)
        assets.append(sanitized)
        enough(rect.height + 12)
        if rect.width > current.rect.width - 2 * margin or rect.height > current.rect.height - 2 * margin:
            if not config.get("allowOversizeAssetPages", True):
                fail("LAYOUT_UNSUPPORTED", "An asset needs a dedicated oversized page.")
            new_page(max(595.276, rect.width + 2 * margin), max(841.89, rect.height + 2 * margin))
        x = (current.rect.width - rect.width) / 2
        target = fitz.Rect(x, y, x + rect.width, y + rect.height)
        current.show_pdf_page(target, sanitized, 0, clip=rect, keep_proportion=True)
        placed.append({"blockId": block_id, "sourcePage": item["page"], "sourceBbox": list(rect),
                       "outputPage": current.number + 1, "outputBbox": list(target), "kind": "asset"})
        y += rect.height + 12

    def add_text(text, block):
        nonlocal y, text_count
        protected = block.get("protected", {})
        local_size = size * (1.5 if block.get("type") == "title" else 1.18 if block.get("type") in ("heading", "section") else .88 if block.get("type") == "footnote" else 1)
        atoms = []
        def add_plain(value):
            for ch in value:
                if ch in "\r\t":
                    ch = " "
                if ch == "\n":
                    atoms.append({"newline": True}); continue
                if unicodedata.bidirectional(ch) in ("R", "AL", "AN"):
                    fail("TARGET_LANGUAGE_UNSUPPORTED", "Right-to-left text is not supported by this compositor.")
                if not font.has_glyph(ord(ch)):
                    fail("TARGET_LANGUAGE_UNSUPPORTED", f"Selected font lacks U+{ord(ch):04X}.")
                atoms.append({"text": ch, "width": font.text_length(ch, fontsize=local_size), "height": local_size * 1.5})
        pos = 0
        for match in TOKEN.finditer(text):
            add_plain(text[pos:match.start()])
            p = protected.get(match.group())
            if not p:
                fail("PLACEHOLDER_MISMATCH", f"Unmapped token {match.group()}.")
            if p["kind"] == "literal":
                add_plain(p["text"])
            elif p["kind"] == "math":
                sanitized, rect = _clean_region(source, p)
                assets.append(sanitized)
                atoms.append({"math": sanitized, "rect": rect, "width": rect.width, "height": rect.height,
                              "baseline": float(p.get("baseline", rect.y1)) - rect.y0, "source": p})
            else:
                fail("PLACEHOLDER_MISMATCH", "Unknown protected resource kind.")
            pos = match.end()
        add_plain(text[pos:])
        enough(local_size * 1.5)
        line = []
        width = 0
        def flush():
            nonlocal line, width, y
            if not line:
                y += local_size * 1.5
                return
            ascent = max([local_size * max(1, font.ascender)] + [max(0, a.get("baseline", 0)) for a in line])
            descent = max([local_size * max(.25, -font.descender)] + [max(0, a["height"] - a.get("baseline", a["height"])) for a in line if "math" in a])
            height = max(local_size * 1.5, ascent + descent + 2)
            enough(height)
            x = margin
            run, run_x = "", x
            def write_run():
                if run:
                    current.insert_text((run_x, y + ascent), run, fontname="PaperFont", fontsize=local_size)
            for atom in line:
                if "math" in atom:
                    write_run(); run = ""
                    top = y + ascent - atom["baseline"]
                    target = fitz.Rect(x, top, x + atom["width"], top + atom["height"])
                    current.show_pdf_page(target, atom["math"], 0, clip=atom["rect"], keep_proportion=True)
                    placed.append({"blockId": block["blockId"], "kind": "inlineMath", "sourcePage": atom["source"]["page"],
                                   "sourceBbox": list(atom["rect"]), "outputPage": current.number + 1, "outputBbox": list(target)})
                    x += atom["width"]; run_x = x
                else:
                    if not run: run_x = x
                    run += atom["text"]; x += atom["width"]
            write_run()
            y += height
            line, width = [], 0
        for atom in atoms:
            if atom.get("newline"):
                flush(); continue
            available = current.rect.width - 2 * margin
            if atom["width"] > available:
                fail("LAYOUT_UNSUPPORTED", "An inline formula is wider than the text column.")
            if line and width + atom["width"] > available:
                # Move the preceding character with closing punctuation instead of
                # allowing punctuation to start a line or exceeding the column width.
                combined = line + [atom]
                legal = [i for i in range(1, len(combined))
                         if combined[i - 1].get("text") not in NO_LINE_END
                         and combined[i].get("text") not in NO_LINE_START]
                word_boundaries = [i for i in legal
                                   if combined[i - 1].get("text") == " "
                                   and i > len(line) // 2]
                if not legal:
                    fail("LAYOUT_UNSUPPORTED", "No legal punctuation-safe line break fits the column.")
                split = max(word_boundaries or legal)
                tail = line[split:]
                line = line[:split]
                while line and line[-1].get("text") == " ":
                    line.pop()
                flush()
                line = tail
                width = sum(a["width"] for a in line)
                if width + atom["width"] > available:
                    fail("LAYOUT_UNSUPPORTED", "An unbreakable punctuation group is wider than the column.")
            if not line and atom.get("text") == " ":
                continue
            line.append(atom); width += atom["width"]
        flush()
        y += local_size * .65
        text_count += 1

    try:
        if source.needs_pass:
            fail("PDF_ENCRYPTED", "Source is encrypted.")
        for block in blocks:
            kind = block.get("type", "body")
            if kind in ("header", "footer", "page_number"):
                continue
            if kind in ("asset", "figure", "table", "equation"):
                for item in block.get("sources", []):
                    add_asset(item, block["blockId"])
                continue
            text = translations.get(block["blockId"]) if block.get("translate") else block.get("text", "")
            if isinstance(text, dict): text = text.get("text", text.get("translation"))
            if not isinstance(text, str) or not text.strip():
                fail("TRANSLATION_INCOMPLETE", f"Missing text for {block['blockId']}.")
            if re.search(r"(?:page|页)\s*\d+|第\s*\d+\s*页", block.get("text", ""), re.I):
                warnings.append({"code": "PAGE_REFERENCE_REVIEW", "blockId": block["blockId"], "message": "Source page reference may change after reflow; not rewritten."})
            add_text(text, block)
        if not len(output):
            fail("OUTPUT_VALIDATION_FAILED", "No content to export.")
        for page in output:
            page.insert_text((margin, page.rect.height - 22), str(page.number + 1), fontsize=9, fontname="helv")
        output.set_metadata({"title": source.metadata.get("title", "") or "Translated paper", "producer": "dsh-pdf-paper-translation-tools"})
        destination.parent.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix=".paper-export-", suffix=".pdf", dir=destination.parent)
        os.close(fd)
        output.save(temp, garbage=4, deflate=True)
        with fitz.open(temp) as check:
            if len(check) != len(output): fail("OUTPUT_VALIDATION_FAILED", "Page count mismatch.")
            for page in check:
                text = page.get_text()
                if TOKEN.search(text) or "\ufffd" in text:
                    fail("OUTPUT_VALIDATION_FAILED", "Unresolved token or replacement character in PDF.")
                # Force every page through the renderer, catching malformed streams.
                scale = min(1.0, 2048 / max(page.rect.width, page.rect.height))
                page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
            for placement in placed:
                source_rect = fitz.Rect(placement["sourceBbox"])
                target_rect = fitz.Rect(placement["outputBbox"])
                pixel_scale = min(2.0, 2048 / max(source_rect.width, source_rect.height))
                before = source[placement["sourcePage"] - 1].get_pixmap(
                    matrix=fitz.Matrix(pixel_scale, pixel_scale).pretranslate(-source_rect.x0, -source_rect.y0),
                    clip=source_rect, alpha=False)
                after = check[placement["outputPage"] - 1].get_pixmap(
                    matrix=fitz.Matrix(pixel_scale, pixel_scale).pretranslate(-target_rect.x0, -target_rect.y0),
                    clip=target_rect, alpha=False)
                if (before.width, before.height) != (after.width, after.height):
                    fail("OUTPUT_VALIDATION_FAILED", "Asset render dimensions differ after placement.")
                mean_difference = sum(abs(a - b) for a, b in zip(before.samples, after.samples)) / max(1, len(before.samples) * 255)
                placement["renderMeanAbsoluteDifference"] = mean_difference
                if mean_difference > .005:
                    fail("OUTPUT_VALIDATION_FAILED", "Asset changed visually after placement.")
        if sum(p["kind"] == "asset" for p in placed) != expected_asset_count:
            fail("OUTPUT_VALIDATION_FAILED", "Asset coverage mismatch.")
        for p in placed:
            a, b = fitz.Rect(p["sourceBbox"]), fitz.Rect(p["outputBbox"])
            if abs(a.width - b.width) > .001 or abs(a.height - b.height) > .001:
                fail("OUTPUT_VALIDATION_FAILED", "Asset physical dimensions changed.")
        if _digest(source_path) != digest_before:
            fail("STALE_VERSION", "Source PDF changed during export.")
        # Atomic create without ever overwriting an existing file.
        os.link(temp, destination)
        os.unlink(temp); temp = None
        return {"outputPath": str(destination), "pages": len(output), "textBlocks": text_count,
                "assets": placed, "sourceSha256": digest_before, "warnings": warnings,
                "validation": {"reopened": True, "allPagesRendered": True, "assetAppearanceBeforePlacement": "exact", "physicalSizePreserved": True, "assetAppearanceAfterPlacement": "mean absolute channel difference <= 0.005"}}
    finally:
        for asset in assets: asset.close()
        output.close(); source.close()
        if temp and os.path.exists(temp): os.unlink(temp)
