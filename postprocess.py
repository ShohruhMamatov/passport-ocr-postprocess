import csv
import json
import os
import re
import sys
from datetime import date

FIELDS = ["Last_name_ru", "First_name_ru", "Middle_name_ru", "Sex_ru", "Birth_date",
          "Birth_place_ru", "Issue_date", "Issue_organisation_code", "Licence_number",
          "Issue_organization_ru"]
CHECK_DATE = date(2026, 10, 1)
HERE = os.path.dirname(os.path.abspath(__file__))

TH = {
    "web":       {"mrz": 0.50, "nomrz": 0.99, "free": 0.97},
    "mobile":    {"mrz": 0.50, "nomrz": 0.95, "free": 0.97},
    "mobile_v2": {"mrz": 0.999, "nomrz": 0.999, "free": 0.999},
}

CYR2MRZ = dict(zip("АБВГДЕЁЖЗИЙКЛМНОПРСТУФХЦЧШЩЪЫЬЭЮЯ",
                   "ABVGDE2JZIQKLMNOPRSTUFHC34WXY9678"))
MRZ2CYR = {v: k for k, v in CYR2MRZ.items() if k != "Ё"}
MRZ2CYR["2"] = "Ё"


def check_digit(s):
    w, total = (7, 3, 1), 0
    for i, ch in enumerate(s):
        if ch.isdigit():
            v = int(ch)
        elif ch.isalpha():
            v = ord(ch) - 55
        else:
            v = 0
        total += v * w[i % 3]
    return str(total % 10)


def to_mrz(s):
    return "".join(CYR2MRZ.get(c, "<") for c in s.upper())


def parse_mrz(mrz):
    if not mrz or len(mrz.get("lines") or []) != 2:
        return None
    l1, l2 = mrz["lines"][0]["text"], mrz["lines"][1]["text"]
    out = {"l1": l1, "l2": l2,
           "conf1": min(mrz["lines"][0]["char_conf"] or [0]),
           "conf2": min(mrz["lines"][1]["char_conf"] or [0])}
    if len(l1) == 44 and l1.startswith("PNRUS"):
        out["names_raw"] = l1[5:]
        parts = l1[5:].split("<<", 1)
        out["last"] = parts[0]
        rest = parts[1].strip("<").split("<") if len(parts) > 1 else []
        out["first"] = rest[0] if rest else ""
        out["middle"] = "<".join(rest[1:]) if len(rest) > 1 else ""
        out["truncated"] = not l1.endswith("<")
    if len(l2) == 44:
        num, c_num = l2[0:9], l2[9]
        bd, c_bd = l2[13:19], l2[19]
        opt, c_opt = l2[28:42], l2[42]
        out["ok_num"] = check_digit(num) == c_num
        out["ok_bd"] = check_digit(bd) == c_bd
        out["ok_opt"] = check_digit(opt) == c_opt
        out["ok_all"] = check_digit(num + c_num + bd + c_bd + l2[21:28] + opt + c_opt) == l2[43]
        out["sex"] = {"M": "МУЖ.", "F": "ЖЕН."}.get(l2[20])
        out["bd_yymmdd"] = bd
        out["number"] = f"{num[0:2]} {num[2]}{l2[28]} {num[3:9]}"
        out["issue_yymmdd"] = l2[29:35]
        out["code"] = f"{l2[35:38]}-{l2[38:41]}"
    return out


def yymmdd(d):
    m = re.fullmatch(r"(\d\d)\.(\d\d)\.\d\d(\d\d)", d or "")
    return m.group(3) + m.group(2) + m.group(1) if m else None


def viz_text(f):
    return " ".join(l["text"] for l in f["lines"]) if f else None


def viz_min_conf(f):
    cs = [c for l in f["lines"] for c in l["char_conf"]] if f else []
    return min(cs) if cs else 0.0


def missing_lines(f):
    if not f or not f["lines"]:
        return True
    line_h = sorted(l["box"][3] for l in f["lines"])[len(f["lines"]) // 2]
    expected = round(f["box"][3] / (line_h * 1.0))
    return len(f["lines"]) < expected


def parse_date(s):
    m = re.fullmatch(r"(\d\d)\.(\d\d)\.(\d{4})", s or "")
    if not m:
        return None
    try:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    except ValueError:
        return None


def add_years(d, n):
    try:
        return d.replace(year=d.year + n)
    except ValueError:
        return d.replace(year=d.year + n, day=28)


def passport_valid(birth, issue, on=CHECK_DATE):
    if not birth or not issue or issue > on or issue < add_years(birth, 14):
        return False
    for age in (20, 45):
        bday = add_years(birth, age)
        if issue < bday:
            return (on - bday).days <= 90
    return True


def load_vocab():
    words = set()
    path = os.path.join(HERE, "reference", "subdivisions.csv")
    with open(path, encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            words.update(re.findall(r"[А-ЯЁ]+", r["name"].upper()))
    return words


def process(doc, vocab):
    viz = doc["viz"]
    if any(viz.get(f) is None for f in FIELDS if f != "Middle_name_ru"):
        return None, "missing_field"
    vals = {f: viz_text(viz.get(f)) or "" for f in FIELDS}
    conf = {f: viz_min_conf(viz.get(f)) for f in FIELDS}
    th = TH[doc["source"]]
    m = parse_mrz(doc.get("mrz"))
    mrz_ok = bool(m and "ok_all" in m and m["ok_num"] and m["ok_bd"] and m["ok_opt"]
                  and m["ok_all"] and "last" in m)

    if mrz_ok:
        checks = {
            "Licence_number": vals["Licence_number"] == m["number"],
            "Birth_date": yymmdd(vals["Birth_date"]) == m["bd_yymmdd"],
            "Issue_date": yymmdd(vals["Issue_date"]) == m["issue_yymmdd"],
            "Issue_organisation_code": vals["Issue_organisation_code"] == m["code"],
            "Sex_ru": vals["Sex_ru"] == m["sex"],
        }
        full = to_mrz(vals["Last_name_ru"]) + "<<" + to_mrz(vals["First_name_ru"])
        if vals["Middle_name_ru"]:
            full += "<" + to_mrz(vals["Middle_name_ru"])
        full = (full + "<" * 39)[:39]
        checks["names"] = full == m["names_raw"]
        if not all(checks.values()):
            return None, "mrz_mismatch:" + ",".join(k for k, v in checks.items() if not v)
        if min(conf[f] for f in FIELDS[:5] + FIELDS[6:9]) < th["mrz"]:
            return None, "low_conf_mrz_fields"
    else:
        if min(conf[f] for f in FIELDS[:5] + FIELDS[6:9]) < th["nomrz"]:
            return None, "no_mrz_low_conf"

    for f in FIELDS:
        if viz.get(f) is not None and missing_lines(viz[f]):
            return None, "missing_line:" + f

    for f in ("Birth_place_ru", "Issue_organization_ru"):
        if conf[f] < th["free"]:
            return None, "low_conf:" + f
    for w in re.findall(r"[А-ЯЁ]+", vals["Issue_organization_ru"]):
        if w not in vocab:
            return None, "unknown_word_org"

    if not re.fullmatch(r"\d\d \d\d \d{6}", vals["Licence_number"]) \
            or not re.fullmatch(r"\d{3}-\d{3}", vals["Issue_organisation_code"]) \
            or vals["Sex_ru"] not in ("МУЖ.", "ЖЕН."):
        return None, "format"
    birth, issue = parse_date(vals["Birth_date"]), parse_date(vals["Issue_date"])
    if not birth or not issue or not (1900 <= birth.year <= 2012) or not (1997 <= issue.year <= 2026):
        return None, "implausible_year"
    if not passport_valid(birth, issue):
        return None, "expired_or_bad_dates"
    return vals, "ok_mrz" if mrz_ok else "ok_nomrz"


def main(inp, out):
    vocab = load_vocab()
    n_acc = n = 0
    with open(inp, encoding="utf-8") as fi, open(out, "w", encoding="utf-8") as fo:
        for line in fi:
            doc = json.loads(line)
            vals, _ = process(doc, vocab)
            rec = {"doc_id": doc["doc_id"], "decision": "accept" if vals else "reject"}
            if vals:
                rec["fields"] = vals
                n_acc += 1
            n += 1
            fo.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"accepted {n_acc} / {n}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
