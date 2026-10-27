"""Diagnostics on train: python tune.py"""
import collections
import json
import sys

import postprocess as pp


def norm(s):
    return " ".join(str(s or "").split()).upper()


def main():
    preds = [json.loads(l) for l in open("data/train_predictions.jsonl", encoding="utf-8")]
    labels = {d["doc_id"]: d["fields"] for d in map(json.loads, open("data/train_labels.jsonl", encoding="utf-8"))}
    vocab = pp.load_vocab()
    reasons = collections.Counter()
    good = bad = 0
    bad_examples = []
    for doc in preds:
        vals, why = pp.process(doc, vocab)
        reasons[why.split(":")[0]] += 1
        if vals is None:
            continue
        gt = labels[doc["doc_id"]]
        wrong = [f for f in pp.FIELDS if norm(vals[f]) != norm(gt[f])]
        if wrong:
            bad += 1
            bad_examples.append((doc["doc_id"], doc["source"], why, [(f, vals[f], gt[f]) for f in wrong]))
        else:
            good += 1
    print("reasons:", dict(reasons))
    print(f"accepted correct: {good}, accepted WRONG: {bad}")
    for e in bad_examples[:15]:
        print(e)


if __name__ == "__main__" and "--sweep" not in sys.argv:
    sys.stdout.reconfigure(encoding="utf-8")
    main()


def sweep():
    """Per-source sweep: thresholds 0 -> collect candidates -> simulate thresholds offline."""
    preds = [json.loads(l) for l in open("data/train_predictions.jsonl", encoding="utf-8")]
    labels = {d["doc_id"]: d["fields"] for d in map(json.loads, open("data/train_labels.jsonl", encoding="utf-8"))}
    vocab = pp.load_vocab()
    for s in pp.TH:
        pp.TH[s] = {"mrz": 0, "nomrz": 0, "free": 0}
    core = pp.FIELDS[:5] + pp.FIELDS[6:9]
    rows = collections.defaultdict(list)
    for doc in preds:
        vals, why = pp.process(doc, vocab)
        if vals is None:
            continue
        c = {f: pp.viz_min_conf(doc["viz"].get(f)) for f in pp.FIELDS}
        ok = all(norm(vals[f]) == norm(labels[doc["doc_id"]][f]) for f in pp.FIELDS)
        rows[doc["source"]].append((why, min(c[f] for f in core), min(c["Birth_place_ru"], c["Issue_organization_ru"]), ok))
    grid = [0.5, 0.9, 0.95, 0.97, 0.98, 0.99, 0.995, 0.999]
    for src, rs in rows.items():
        print(f"\n== {src}: candidates {len(rs)}, wrong among them {sum(not r[3] for r in rs)}")
        print("  path    core_th  free_th   good  bad")
        for path in ("ok_mrz", "ok_nomrz"):
            for ct in grid:
                for ft in grid:
                    sel = [r for r in rs if r[0] == path and r[1] >= ct and r[2] >= ft]
                    g, b = sum(r[3] for r in sel), sum(not r[3] for r in sel)
                    if ft in (0.9, 0.97, 0.99, 0.999) and ct in (0.5, 0.95, 0.99, 0.999):
                        print(f"  {path:8} {ct:6} {ft:7}  {g:5} {b:4}")


if __name__ == "__main__" and "--sweep" in sys.argv:
    sweep()
