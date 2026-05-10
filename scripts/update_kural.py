"""
update_kural.py: Gacha-based daily Thirukkural selector.

Pipeline per run:
  1. Load 1330 kurals from CSV (order = canonical; 10 per chapter x 133).
  2. Load persisted weight state from data/gacha_state.json (or init fresh).
  3. Recover weights toward baseline (rho pull).
  4. Sample: chapter ~ w_c, then kural ~ v_{c,k}.
  5. Apply cooldown (alpha decay + epsilon floor) to chosen chapter/kural;
     redistribute removed mass across siblings.
  6. Normalize, persist state, rewrite README between markers.
"""

import csv, json, random, re, sys, datetime as dt
from pathlib import Path

CSV_PATH    = Path("data/Thirukural.csv")
STATE_PATH  = Path("data/gacha_state.json")
README_PATH = Path("README.md")
START, END  = "<!-- KURAL:START -->", "<!-- KURAL:END -->"

N_CHAPTERS, PER_CHAPTER = 133, 10
ALPHA_CH, ALPHA_K = 0.20, 0.25
EPS_CH,   EPS_K   = 0.001, 0.02
RHO_CH,   RHO_K   = 0.10,  0.15


def load_kurals():
    with CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if len(rows) != N_CHAPTERS * PER_CHAPTER:
        print(f"WARN: expected {N_CHAPTERS*PER_CHAPTER} rows, got {len(rows)}", file=sys.stderr)
    kurals = []
    for i, r in enumerate(rows):
        verse = " ".join((r["Verse"] or "").split()).strip()
        kurals.append({
            "global_id":  i + 1,
            "chapter_ix": i // PER_CHAPTER,          # 0..132
            "kural_ix":   i %  PER_CHAPTER,          # 0..9
            "book":       (r["Section Name"] or "").strip(),
            "chapter":    (r["Chapter Name"] or "").strip(),
            "tamil":      verse,
            "translation":(r["Translation"] or "").strip(),
        })
    return kurals


def load_state():
    if STATE_PATH.exists():
        return json.loads(STATE_PATH.read_text())
    return {
        "chapter_w": [1.0 / N_CHAPTERS] * N_CHAPTERS,
        "kural_w":   [[1.0 / PER_CHAPTER] * PER_CHAPTER for _ in range(N_CHAPTERS)],
    }


def recover(weights, base, rho):
    return [w + rho * (base - w) for w in weights]

def normalize(ws):
    s = sum(ws)
    return [w / s for w in ws] if s > 0 else ws

def sample(weights):
    return random.choices(range(len(weights)), weights=weights, k=1)[0]


def cooldown(weights, chosen, alpha, eps):
    old = weights[chosen]
    new = max(eps, alpha * old)
    delta = old - new
    weights[chosen] = new
    others = [i for i in range(len(weights)) if i != chosen]
    if others and delta > 0:
        share = delta / len(others)
        for i in others:
            weights[i] += share
    return normalize(weights)


def main():
    kurals = load_kurals()
    state = load_state()
    random.seed(dt.date.today().isoformat())

    state["chapter_w"] = normalize(recover(state["chapter_w"], 1.0/N_CHAPTERS, RHO_CH))
    state["kural_w"] = [normalize(recover(kw, 1.0/PER_CHAPTER, RHO_K)) for kw in state["kural_w"]]

    c = sample(state["chapter_w"])
    k = sample(state["kural_w"][c])
    chosen = kurals[c * PER_CHAPTER + k]
  
    state["chapter_w"] = cooldown(state["chapter_w"], c, ALPHA_CH, EPS_CH)
    state["kural_w"][c] = cooldown(state["kural_w"][c], k, ALPHA_K, EPS_K)
  
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state))

    block = (
        f"### 📜 Thirukkural of the Day\n\n"
        f"> {chosen['tamil']}  \n>\n"
        f"> *{chosen['translation']}*\n\n"
        f"*{chosen['book']} · {chosen['chapter']}*  \n"
        f"<sub>Kural #{chosen['global_id']} · {dt.date.today():%B %d, %Y}</sub>"
    )

    orig = README_PATH.read_text(encoding="utf-8")
    pat = re.compile(re.escape(START) + r".*?" + re.escape(END), re.DOTALL)
    if not pat.search(orig):
        print(f"ERROR: missing markers {START} / {END}", file=sys.stderr); sys.exit(1)
    new = pat.sub(f"{START}\n{block}\n{END}", orig)
    if new != orig:
        README_PATH.write_text(new, encoding="utf-8")
        print(f"Picked #{chosen['global_id']} ({chosen['chapter']}) — README updated")
    else:
        print("No change.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
