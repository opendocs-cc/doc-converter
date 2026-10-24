"""
LaTeX math → Office Math (OMML).

``$...$`` and ``$$...$$`` in Markdown are converted to MathML with
latex2mathml, then mapped element by element onto OMML, the math format
Word uses natively. Word and LibreOffice both typeset OMML (fractions,
radicals, scripts, n-ary operators, matrices), and the equations stay
editable in Word.

Anything latex2mathml can't parse comes back as ``None`` and the caller
shows the TeX source instead.
"""

from __future__ import annotations

from typing import Optional

from lxml import etree

M_NS = "http://schemas.openxmlformats.org/officeDocument/2006/math"
W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MML_NS = "http://www.w3.org/1998/Math/MathML"

# Operators drawn as n-ary (big) operators with limits.
_NARY = set("∑∏∐∫∬∭∮∯∰⋀⋁⋂⋃⨀⨁⨂⨄⨆")
# Operators whose limits sit under/over the base (\lim, \max ...).
_LIMIT_WORDS = {"lim", "max", "min", "sup", "inf", "limsup", "liminf", "det", "gcd", "Pr", "arg max", "arg min"}


def _m(tag: str) -> str:
    return f"{{{M_NS}}}{tag}"


def _w(tag: str) -> str:
    return f"{{{W_NS}}}{tag}"


def _local(el) -> str:
    return etree.QName(el).localname


def _text(el) -> str:
    return "".join(el.itertext()).strip()


class _Builder:
    def __init__(self, font: str):
        self.font = font

    # ── primitives ──────────────────────────────────────────────────────

    def run(self, text: str, *, plain: bool = False, bold: bool = False):
        r = etree.Element(_m("r"))
        if plain or bold:
            # p = upright, b = upright bold, bi = bold italic
            rpr = etree.SubElement(r, _m("rPr"))
            sty = etree.SubElement(rpr, _m("sty"))
            sty.set(_m("val"), ("b" if plain else "bi") if bold else "p")
        wrpr = etree.SubElement(r, _w("rPr"))
        fonts = etree.SubElement(wrpr, _w("rFonts"))
        fonts.set(_w("ascii"), self.font)
        fonts.set(_w("hAnsi"), self.font)
        t = etree.SubElement(r, _m("t"))
        t.text = text
        if text != text.strip():
            t.set("{http://www.w3.org/XML/1998/namespace}space", "preserve")
        return r

    def wrap(self, tag: str, children) -> etree._Element:
        el = etree.Element(_m(tag))
        for child in children:
            el.append(child)
        return el

    def arg(self, tag: str, node) -> etree._Element:
        """An argument slot (``m:e``, ``m:num``...) holding ``node``."""
        return self.wrap(tag, self.convert(node) if node is not None else [])

    # ── conversion ──────────────────────────────────────────────────────

    def convert(self, el) -> list:
        """OMML elements for a MathML element."""
        name = _local(el)
        handler = getattr(self, f"_{name}", None)
        if handler is not None:
            return handler(el)
        return self.children(el)

    def children(self, el) -> list:
        out: list = []
        kids = [k for k in el if isinstance(k.tag, str)]
        i = 0
        while i < len(kids):
            kid = kids[i]
            # A big operator with limits takes the next sibling as its body.
            if self._is_nary(kid):
                body = kids[i + 1] if i + 1 < len(kids) else None
                out.append(self._nary(kid, body))
                i += 2 if body is not None else 1
                continue
            out.extend(self.convert(kid))
            i += 1
        return out

    def _is_nary(self, el) -> bool:
        name = _local(el)
        if name == "mo":
            return _text(el) in _NARY
        if name in ("msub", "msup", "msubsup", "munder", "mover", "munderover"):
            base = next((k for k in el if isinstance(k.tag, str)), None)
            return base is not None and _local(base) == "mo" and _text(base) in _NARY
        return False

    def _nary(self, el, body):
        name = _local(el)
        kids = [k for k in el if isinstance(k.tag, str)]
        op = _text(kids[0]) if name != "mo" else _text(el)
        sub = sup = None
        if name in ("msub", "munder"):
            sub = kids[1]
        elif name in ("msup", "mover"):
            sup = kids[1]
        elif name in ("msubsup", "munderover"):
            sub, sup = kids[1], kids[2]
        nary = etree.Element(_m("nary"))
        pr = etree.SubElement(nary, _m("naryPr"))
        chr_ = etree.SubElement(pr, _m("chr"))
        chr_.set(_m("val"), op)
        if op in "∫∬∭∮∯∰":
            loc = etree.SubElement(pr, _m("limLoc"))
            loc.set(_m("val"), "subSup")
        if sub is None:
            hide = etree.SubElement(pr, _m("subHide"))
            hide.set(_m("val"), "1")
        if sup is None:
            hide = etree.SubElement(pr, _m("supHide"))
            hide.set(_m("val"), "1")
        nary.append(self.arg("sub", sub))
        nary.append(self.arg("sup", sup))
        nary.append(self.arg("e", body))
        return nary

    # Leaves

    def _mi(self, el):
        text = _text(el)
        variant = el.get("mathvariant", "")
        plain = len(text) > 1 or variant == "normal"
        return [self.run(text, plain=plain, bold="bold" in variant)]

    def _mn(self, el):
        return [self.run(_text(el))]

    def _mo(self, el):
        text = _text(el)
        return [self.run(text, plain=text in _LIMIT_WORDS or text.isalpha())]

    def _mtext(self, el):
        return [self.run(_text(el).replace(" ", " ") or " ", plain=True)]

    def _ms(self, el):
        return [self.run(f'"{_text(el)}"', plain=True)]

    def _mspace(self, el):
        return [self.run(" ")]

    def _none(self, el):
        return []

    def _mphantom(self, el):
        return []

    # Rows and fences

    def _mrow(self, el):
        kids = [k for k in el if isinstance(k.tag, str)]
        if (
            len(kids) >= 2
            and _local(kids[0]) == "mo" and _local(kids[-1]) == "mo"
            and kids[0].get("fence") == "true" and kids[-1].get("fence") == "true"
        ):
            return [self._delimited(_text(kids[0]), _text(kids[-1]), kids[1:-1])]
        return self.children(el)

    def _mfenced(self, el):
        kids = [k for k in el if isinstance(k.tag, str)]
        return [self._delimited(el.get("open", "("), el.get("close", ")"), kids)]

    def _delimited(self, open_chr: str, close_chr: str, inner):
        d = etree.Element(_m("d"))
        pr = etree.SubElement(d, _m("dPr"))
        beg = etree.SubElement(pr, _m("begChr"))
        beg.set(_m("val"), open_chr)
        end = etree.SubElement(pr, _m("endChr"))
        end.set(_m("val"), close_chr)
        e = etree.SubElement(d, _m("e"))
        holder = etree.Element(_m("tmp"))
        for kid in inner:
            holder.append(kid)
        for child in self.children(holder):
            e.append(child)
        return d

    # Scripts

    def _msup(self, el):
        base, sup = [k for k in el if isinstance(k.tag, str)][:2]
        return [self.wrap("sSup", [self.arg("e", base), self.arg("sup", sup)])]

    def _msub(self, el):
        base, sub = [k for k in el if isinstance(k.tag, str)][:2]
        if _local(base) == "mo" and _text(base) in _LIMIT_WORDS:
            return [self.wrap("limLow", [self.arg("e", base), self.arg("lim", sub)])]
        return [self.wrap("sSub", [self.arg("e", base), self.arg("sub", sub)])]

    def _msubsup(self, el):
        base, sub, sup = [k for k in el if isinstance(k.tag, str)][:3]
        return [self.wrap("sSubSup", [self.arg("e", base), self.arg("sub", sub), self.arg("sup", sup)])]

    def _munder(self, el):
        base, under = [k for k in el if isinstance(k.tag, str)][:2]
        return [self.wrap("limLow", [self.arg("e", base), self.arg("lim", under)])]

    def _mover(self, el):
        base, over = [k for k in el if isinstance(k.tag, str)][:2]
        mark = _text(over)
        if _local(over) == "mo" and mark in ("¯", "‾", "_", "―"):
            bar = etree.Element(_m("bar"))
            pr = etree.SubElement(bar, _m("barPr"))
            pos = etree.SubElement(pr, _m("pos"))
            pos.set(_m("val"), "top")
            bar.append(self.arg("e", base))
            return [bar]
        if _local(over) == "mo" and len(mark) == 1:
            acc = etree.Element(_m("acc"))
            pr = etree.SubElement(acc, _m("accPr"))
            chr_ = etree.SubElement(pr, _m("chr"))
            chr_.set(_m("val"), {"^": "̂", "~": "̃", "˙": "̇", "¨": "̈",
                                  "→": "⃗", "ˇ": "̌", "˘": "̆", "´": "́",
                                  "`": "̀"}.get(mark, mark))
            acc.append(self.arg("e", base))
            return [acc]
        return [self.wrap("limUpp", [self.arg("e", base), self.arg("lim", over)])]

    def _munderover(self, el):
        base, under, over = [k for k in el if isinstance(k.tag, str)][:3]
        low = self.wrap("limLow", [self.arg("e", base), self.arg("lim", under)])
        e = self.wrap("e", [low])
        return [self.wrap("limUpp", [e, self.arg("lim", over)])]

    # Fractions and radicals

    def _mfrac(self, el):
        num, den = [k for k in el if isinstance(k.tag, str)][:2]
        f = etree.Element(_m("f"))
        if el.get("linethickness") in ("0", "0px", "0em"):
            pr = etree.SubElement(f, _m("fPr"))
            typ = etree.SubElement(pr, _m("type"))
            typ.set(_m("val"), "noBar")
        f.append(self.arg("num", num))
        f.append(self.arg("den", den))
        return [f]

    def _msqrt(self, el):
        rad = etree.Element(_m("rad"))
        pr = etree.SubElement(rad, _m("radPr"))
        hide = etree.SubElement(pr, _m("degHide"))
        hide.set(_m("val"), "1")
        etree.SubElement(rad, _m("deg"))
        rad.append(self.wrap("e", self.children(el)))
        return [rad]

    def _mroot(self, el):
        base, degree = [k for k in el if isinstance(k.tag, str)][:2]
        rad = etree.Element(_m("rad"))
        rad.append(self.arg("deg", degree))
        rad.append(self.arg("e", base))
        return [rad]

    # Tables and boxes

    def _mtable(self, el):
        matrix = etree.Element(_m("m"))
        for row in el:
            if not isinstance(row.tag, str) or _local(row) not in ("mtr", "mlabeledtr"):
                continue
            mr = etree.SubElement(matrix, _m("mr"))
            for cell in row:
                if isinstance(cell.tag, str) and _local(cell) == "mtd":
                    mr.append(self.wrap("e", self.children(cell)))
        return [matrix]

    def _menclose(self, el):
        return [self.wrap("borderBox", [self.wrap("e", self.children(el))])]


def latex_to_omml(tex: str, *, display: bool, font: str = "Cambria Math") -> Optional[etree._Element]:
    """An ``m:oMath`` (inline) or ``m:oMathPara`` (display) element for
    ``tex``, or ``None`` if it can't be parsed."""
    tex = (tex or "").strip()
    if not tex:
        return None
    try:
        from latex2mathml.converter import convert

        mathml = convert(tex)
        root = etree.fromstring(mathml.encode("utf-8"))
        builder = _Builder(font)
        math = etree.Element(_m("oMath"), nsmap={"m": M_NS, "w": W_NS})
        for child in builder.children(root):
            math.append(child)
    except Exception:
        return None
    if not display:
        return math
    para = etree.Element(_m("oMathPara"), nsmap={"m": M_NS, "w": W_NS})
    para.append(math)
    return para
