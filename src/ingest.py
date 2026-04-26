"""
Document ingestion — converts DOCX and PDF files to plain text.
OMML equations in DOCX are emitted as [[FORMULA: …]] placeholders.
"""

import re
from pathlib import Path


# OMML XML namespaces
_NS_M = "http://schemas.openxmlformats.org/officeDocument/2006/math"
_NS_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


# Property/formatting tags whose content we skip entirely
_SKIP_TAGS = frozenset(
    "rPr ctrlPr sSubPr sSupPr sPr fPr naryPr dPr radPr limLowPr "
    "limUppPr boxPr barPr eqArrPr mPr oMathParaPr sSubSupPr funcPr "
    "groupChrPr accPr".split()
)


def _ltag(elem):
    """Return the local tag name of an lxml element (or '')."""
    from lxml import etree
    return etree.QName(elem.tag).localname if isinstance(elem.tag, str) else ""


def _omml_to_text(elem) -> str:
    """Convert an <m:oMath> element tree into a readable formula string."""
    tag = _ltag(elem)

    if tag == "t":
        return (elem.text or "").strip()
    if tag in _SKIP_TAGS:
        return ""

    # Ordered list of all child texts (preserves duplicates like r, r, sSub, r)
    child_texts = [(_ltag(c), _omml_to_text(c)) for c in elem]
    children = [t for _, t in child_texts if t]
    # Tag-text lookup (last wins) for structural elements with unique children
    parts = {tag: t for tag, t in child_texts if t}

    if tag == "f": # fraction
        n, d = parts.get("num", ""), parts.get("den", "")
        if n and d:
            return f"{'(%s)' % n if ' ' in n else n}/{'(%s)' % d if ' ' in d else d}"
        return "/".join(children) if children else ""

    if tag in ("sSub", "sSup", "sSubSup"): # sub/superscript
        r = parts.get("e", "")
        if parts.get("sub"):
            r += f"_{parts['sub']}"
        if parts.get("sup"):
            r += f"^{parts['sup']}"
        return r

    if tag == "nary":  # summation / product
        op = "∑"
        for child in elem:
            if _ltag(child) == "naryPr":
                for prop in child:
                    if _ltag(prop) == "chr":
                        op = prop.get(f"{{{_NS_M}}}val", op)
                        break
        sub, sup, body = parts.get("sub", ""), parts.get("sup", ""), parts.get("e", "")
        out = [op]
        if sub:
            out.append(f"({sub}")
        if sup:
            out.append(f"to {sup})")
        elif sub:
            out.append(")")
        if body:
            out.append(f" {body}")
        return "".join(out)

    if tag == "d":# delimiter (parens)
        return f"({' '.join(children)})"

    if tag in ("rad", "bar"): # radical / overline
        body = parts.get("e", "")
        return f"{'sqrt' if tag == 'rad' else 'bar'}({body})" if body else ""

    if tag == "func": # named function
        return f"{parts.get('fName', '')}({parts.get('e', '')})"

    return " ".join(children) # default: join


# DOCX ingestion 

def ingest_docx(path: str) -> str:
    """Extract text from a DOCX, with OMML equations as [[FORMULA: …]]."""
    from docx import Document
    from docx.table import Table as DocxTable

    doc = Document(path)
    out: list[str] = []

    def para_text(p_elem) -> str:
        frags: list[str] = []
        for child in p_elem:
            t = _ltag(child)
            if t == "r":
                te = child.find(f"{{{_NS_W}}}t")
                if te is not None and te.text:
                    if frags and frags[-1][-1:].isalnum() and te.text[0].isalnum():
                        frags.append(" ")
                    frags.append(te.text)
            elif t == "oMath":
                f = _omml_to_text(child).strip()
                if f:
                    frags.append(f" [[FORMULA: {f}]] ")
            elif t == "oMathPara":
                for om in child.findall(f"{{{_NS_M}}}oMath"):
                    f = _omml_to_text(om).strip()
                    if f:
                        frags.append(f" [[FORMULA: {f}]] ")
        return "".join(frags).strip()

    for child in doc.element.body:
        t = _ltag(child)
        if t == "p":
            text = para_text(child)
            if text:
                out.append(text)
        elif t == "tbl":
            for row in DocxTable(child, doc).rows:
                cells = " | ".join(c.text.strip() for c in row.cells if c.text.strip())
                if cells:
                    out.append(cells)

    return clean_text("\n".join(out))


# PDF ingestion 

def ingest_pdf(path: str) -> str:
    """Extract text from a text-layer PDF via PyMuPDF."""
    import fitz
    doc = fitz.open(path)
    pages = [p.get_text("text") for p in doc if p.get_text("text").strip()]
    doc.close()
    return clean_text("\n".join(pages))


# Text cleaning

def clean_text(raw: str) -> str:
    """Light, non-semantic cleaning of ingested text."""
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", raw) # fix hyphenated breaks
    text = re.sub(r"(?<![.\:\;\!\?])\n(?!\s*[\-\•\d\(A-Z])", # join mid-sentence breaks
                  " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text) # max two newlines
    text = re.sub(r"[^\S\n]+", " ", text) # collapse horiz. space
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


# Dispatcher

def ingest(path: str) -> str:
    """Auto-detect file type and delegate to the appropriate reader."""
    ext = Path(path).suffix.lower()
    if ext == ".docx":
        return ingest_docx(path)
    if ext == ".pdf":
        return ingest_pdf(path)
    if ext == ".txt":
        return Path(path).read_text(encoding="utf-8")
    raise ValueError(f"Unsupported file type '{ext}'. Supported: .docx, .pdf, .txt")