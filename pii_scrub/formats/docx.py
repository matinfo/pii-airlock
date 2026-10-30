"""Word .docx — scrub every text-bearing part, keep document structure.

Optional dependency: python-docx  (pip install 'pii-airlock[docx]')

Covered: body, tables, text boxes, headers and footers, footnotes, endnotes,
comments, tracked deletions, hyperlink text, and document properties. The
author / last-modified-by properties are cleared outright (they identify a
person but are too short for reliable detection).

Text is scrubbed at paragraph granularity so that entities spanning multiple
runs are still caught; when a paragraph changes, its text is collapsed into the
first text node (formatting within a scrubbed paragraph is not preserved).
"""

from __future__ import annotations

import io

from .base import Handler, MissingExtra, Scrubber, Tokenizer

# Core properties that are free text (scrubbed) / identify a person (cleared).
_SCRUB_PROPS = ("title", "subject", "keywords", "comments", "category", "content_status")
_CLEAR_PROPS = ("author", "last_modified_by")


class DocxHandler(Handler):
    reads_binary = True
    binary_output = True
    out_suffix = ".docx"

    def scrub(self, scrub: Scrubber, tokenize: Tokenizer | None = None) -> bytes:
        try:
            import docx  # type: ignore
            from docx.opc.part import XmlPart  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on install
            raise MissingExtra("docx", "python-docx") from exc

        assert isinstance(self.raw, (bytes, bytearray))
        doc = docx.Document(io.BytesIO(self.raw))

        # Every XML part: document, headers, footers, footnotes, comments, ...
        for part in doc.part.package.iter_parts():
            if isinstance(part, XmlPart):
                _scrub_element(part.element, scrub)

        props = doc.core_properties
        for name in _SCRUB_PROPS:
            value = getattr(props, name, None)
            if isinstance(value, str) and value.strip():
                setattr(props, name, scrub(value))
        for name in _CLEAR_PROPS:
            if getattr(props, name, None):
                setattr(props, name, "")

        out = io.BytesIO()
        doc.save(out)
        return out.getvalue()


def _scrub_element(root, scrub: Scrubber) -> None:
    from docx.oxml.ns import qn  # type: ignore

    w_p, w_t, w_del = qn("w:p"), qn("w:t"), qn("w:delText")
    for p in root.iter(w_p):
        # Only this paragraph's own text nodes; nested paragraphs (text boxes)
        # are visited on their own.
        nodes = [t for t in p.iter(w_t) if _owner(t, w_p) is p]
        _scrub_nodes(nodes, scrub)
    for t in root.iter(w_del):  # tracked deletions still carry the old text
        if t.text and t.text.strip():
            t.text = scrub(t.text)


def _owner(node, w_p):
    return next(node.iterancestors(w_p), None)


def _scrub_nodes(nodes, scrub: Scrubber) -> None:
    original = "".join(t.text or "" for t in nodes)
    if not original.strip():
        return
    cleaned = scrub(original)
    if cleaned == original:
        return
    nodes[0].text = cleaned
    nodes[0].set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
    for t in nodes[1:]:
        t.text = ""
