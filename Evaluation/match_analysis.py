import csv
import string
from pathlib import Path
from typing import Optional

BASE     = Path(__file__).resolve().parent
DATA     = BASE.parent / "data" / "Outputs"
GOLD_CSV = BASE.parent / "data" / "GoldStandard" / "Gold Standard.csv"

SOURCES = {
    "ETSI":   DATA / "ETSI_metrics.csv",
    "Zaveri": DATA / "Zaveri_metrics.csv",
    "IEEE":   DATA / "IEEE_metrics.csv",
}

OUT_TABLE = BASE / "match_analysis.csv"

_STOP = {"a","an","the","of","in","for","to","and","or","by","with",
         "is","are","that","this","it","as","on","at","from"}

def _norm(s: str) -> str:
    s = s.lower().strip()
    s = s.translate(str.maketrans("", "", string.punctuation))
    return " ".join(s.split())

def _tokens(s: str) -> set:
    return {w for w in _norm(s).split() if w not in _STOP and len(w) > 1}

def _label_sim(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta and not tb:
        return 1.0
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)

def _def_sim(a: str, b: str) -> float:
    ta, tb = _tokens(a), _tokens(b)
    if not ta:
        return 0.0
    return len(ta & tb) / len(ta)

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))

def load_gold() -> list[dict]:
    rows = load_csv(GOLD_CSV)
    out = []
    for r in rows:
        out.append({
            "MetricLabel": r.get("MetricLabel", "").strip(),
            "Definition":  r.get("Definition", ""),
            "Formula":     r.get("Formula", ""),
            "Dimension":   r.get("Dimension", ""),
            "Source":      r.get("Source", ""),
        })
    return [r for r in out if r["MetricLabel"]]

def load_extracted() -> list[dict]:
    rows = []
    for source, path in SOURCES.items():
        if not path.exists():
            print(f"  Missing: {path.name}")
            continue
        for r in load_csv(path):
            r["Source"] = source
            rows.append(r)
    return rows

def align(gold: list[dict], extracted: list[dict]) -> list[dict]:
    used = set()
    rows = []

    for g in gold:
        g_src = _norm(g["Source"])

        pool = [
            (i, e) for i, e in enumerate(extracted)
            if _norm(e.get("Source", "")) == g_src and i not in used
        ]

        best_i, best_e = None, None
        best_ls, best_ds = 0.0, 0.0

        for i, e in pool:
            ls = _label_sim(g["MetricLabel"], e.get("MetricLabel", ""))
            ds = _def_sim(g["Definition"],    e.get("Definition", ""))
            score = 0.7 * ls + 0.3 * ds
            if score > 0.7 * best_ls + 0.3 * best_ds:
                best_i, best_e, best_ls, best_ds = i, e, ls, ds

        if best_e is not None and best_ls >= 0.40:
            used.add(best_i)
        else:
            best_e = None

        rows.append(build_row(g, best_e, best_ls, best_ds))

    return rows

def _dim_check(g_dim: str, e_dim: str, source: str = "") -> str:
    # IEEE uses economic value categories rather than DQV dimensions
    if _norm(source) == "ieee":
        return "N/A"
    if not g_dim.strip():
        return "N/A"
    if _norm(g_dim) == _norm(e_dim):
        return "Yes"
    if _norm(g_dim)[:6] == _norm(e_dim)[:6]:
        return "Yes"
    return "No"

def _formula_check(g_f: str, e_f: str) -> str:
    gn = _norm(g_f)
    en = _norm(e_f)
    if gn in ("", "null"):
        return "N/A"
    if gn == en:
        return "Yes"
    gt, et = _tokens(g_f), _tokens(e_f)
    if gt and len(gt & et) / len(gt) >= 0.5:
        return "Close"
    return "No"

def build_row(g: dict, e: Optional[dict], ls: float, ds: float) -> dict:
    if e is None:
        return {
            "Source":                g["Source"],
            "Gold_MetricLabel":      g["MetricLabel"],
            "Extracted_MetricLabel": "",
            "Dim_Match":             "N/A",
            "Formula_Match":         "N/A",
            "LabelSim":              0.0,
            "DefSim":                0.0,
        }

    dim_m     = _dim_check(g["Dimension"], e.get("Dimension", ""), g["Source"])
    formula_m = _formula_check(g["Formula"], e.get("Formula", ""))

    return {
        "Source":                g["Source"],
        "Gold_MetricLabel":      g["MetricLabel"],
        "Extracted_MetricLabel": e.get("MetricLabel", ""),
        "Dim_Match":             dim_m,
        "Formula_Match":         formula_m,
        "LabelSim":              round(ls, 3),
        "DefSim":                round(ds, 3),
    }

FIELDS = [
    "Source", "Gold_MetricLabel", "Extracted_MetricLabel",
    "Dim_Match", "Formula_Match", "LabelSim", "DefSim",
]

def main():
    gold      = load_gold()
    extracted = load_extracted()
    print(f"Gold standard : {len(gold)} records")
    print(f"Extracted     : {len(extracted)} records")

    rows = align(gold, extracted)
    print(f"Aligned       : {len(rows)} rows")

    with OUT_TABLE.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)
    print(f"Wrote -> {OUT_TABLE.name}")


if __name__ == "__main__":
    main()
