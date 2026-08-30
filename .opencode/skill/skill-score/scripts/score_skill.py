#!/usr/bin/env python3
"""score_skill.py — deterministic sub-scoring for /skill-score.

Stdlib only. Computes the mechanical parts of the rubric (Tier-1 point tally,
length checks, when-trigger + anti-trigger detection, reference-path existence,
nearest-neighbor proximity) and the hard-gate checks that files alone can decide.
Everything requiring meaning is emitted as NEEDS_MODEL for the skill body to judge.

Usage:
    python3 score_skill.py <skill-dir-or-SKILL.md> [--origin core|user] [--json]
    python3 score_skill.py --all [--skills-dir .claude/skills] [--json]

Exit codes: 0 ran OK, 3 usage/error. The script reports mechanical sub-scores and
NEEDS_MODEL flags — it does NOT emit the final SHIP/REVISE/NO verdict, which requires
the model's judgment on the NEEDS_MODEL items (see the skill body, Step 5).
"""
import argparse
import json
import re
import sys
from pathlib import Path

TRIGGER_RE = re.compile(r"\b(when|whenever)\b", re.IGNORECASE)
ANTI_RE = re.compile(r"\b(not for|don'?t use (this )?for|instead of|rather than)\b", re.IGNORECASE)
# crude "names another skill to route to" signal
USE_OTHER_RE = re.compile(r"\buse\s+[`/]?[a-z][a-z0-9-]+", re.IGNORECASE)
MECHANISM_WORDS = re.compile(r"\b(MCP|config|manifest|registry|frontmatter|\.py|\.cjs|_server|track_event)\b")

DONE_CLAIM_RE = re.compile(r"(✅|\bdone\b|\bcreated\b|\bsaved\b|\bcomplete[d]?\b|\bfixed\b|\bshipped\b)", re.IGNORECASE)
INSPECT_RE = re.compile(r"(read ?back|verify|confirm|inspect|show the|check the result|re-read|validate)", re.IGNORECASE)
DESTRUCTIVE_RE = re.compile(r"\b(delete|rm |overwrite|publish|post to|send (the |an )?(email|message|slack)|push|deploy|upload)\b", re.IGNORECASE)
AUTHORITY_RE = re.compile(r"(confirm|ask (the )?user|wait for (user )?approval|require.*confirmation|\[y/n\]|before .*proceed)", re.IGNORECASE)
PII_SINK_RE = re.compile(r"\b(publish|upload|share|external|heydex|api\.)", re.IGNORECASE)
PII_GUARD_RE = re.compile(r"(redact|confirm before|review before|strip|exclude .*personal|PII)", re.IGNORECASE)


def parse_skill(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    fm = {}
    body = text
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", text, re.DOTALL)
    if m:
        raw, body = m.group(1), m.group(2)
        for line in raw.splitlines():
            if ":" in line and not line.startswith(" "):
                k, _, v = line.partition(":")
                fm[k.strip()] = v.strip()
    return fm, body, text


def resolve(path_arg: str) -> Path:
    p = Path(path_arg)
    if p.is_dir():
        p = p / "SKILL.md"
    return p


def token_set(s: str):
    return set(re.findall(r"[a-z0-9]+", (s or "").lower())) - {
        "the", "a", "an", "to", "for", "of", "and", "or", "use", "when", "with",
        "your", "you", "this", "that", "it", "in", "on", "dex", "skill",
    }


def nearest_neighbor(name, desc, others):
    """Jaccard on description tokens; returns (name, score 0-1)."""
    mine = token_set(desc)
    best, best_s = None, 0.0
    for oname, odesc in others:
        if oname == name:
            continue
        o = token_set(odesc)
        if not mine or not o:
            continue
        j = len(mine & o) / len(mine | o)
        if j > best_s:
            best, best_s = oname, j
    return best, round(best_s, 3)


def score_one(path: Path, origin: str, neighbors=None):
    fm, body, text = parse_skill(path)
    desc = fm.get("description", "")
    name = fm.get("name", path.parent.name)
    out = {"skill": name, "path": str(path), "origin": origin, "tier1": {}, "hard_gates": {}, "needs_model": []}

    # ---- Tier 1 ----
    t1 = out["tier1"]
    has_when = bool(TRIGGER_RE.search(desc))
    t1["T1.1_when_trigger"] = {"pts": 12 if has_when else 0, "max": 12,
                               "note": "has when/whenever" if has_when else "NO when-trigger"}
    if has_when:
        out["needs_model"].append("T1.1: confirm the when-clause names a REAL firing situation + user phrases, not filler.")

    has_anti = bool(ANTI_RE.search(desc)) and bool(USE_OTHER_RE.search(desc))
    t1["T1.2_anti_trigger"] = {"pts": 10 if has_anti else 0, "max": 10,
                               "note": "anti-trigger + names neighbor" if has_anti else "no 'Not for X; use Y'"}

    mechanism = bool(MECHANISM_WORDS.search(desc))
    t1["T1.3_outcome_not_mechanism"] = {"pts": 4 if mechanism else 8, "max": 8,
                                        "note": "mentions internal mechanism" if mechanism else "outcome-led"}

    lines = body.count("\n") + 1
    if lines <= 200:
        lp = 8
    elif lines <= 350:
        lp = 5
    else:
        lp = 0
    has_refs = (path.parent / "references").is_dir()
    t1["T1.4_thin_body"] = {"pts": lp, "max": 8, "note": f"{lines} body lines; references/={'yes' if has_refs else 'no'}"}

    out["needs_model"] += [
        "T1.5: does the body name a quality bar AND at least one anti-pattern? (score /8)",
        "T1.6: trace the missing-prereq path — is degradation honest, never faked? (score /8)",
        "T1.7: does it refer to people/skills by name and compose siblings vs re-implement? (score /6)",
    ]

    # ---- Hard gates decidable from files ----
    g = out["hard_gates"]
    # Gate 1: distinguishable
    if neighbors is not None:
        nn, nns = nearest_neighbor(name, desc, neighbors)
        g["G1_distinguishable"] = {"fail": nns >= 0.6, "note": f"nearest={nn} jaccard={nns}",
                                   "verdict": "NEEDS_MODEL"}
        out["needs_model"].append(f"G1: read '{nn}' description — is this one truly distinguishable in meaning? (proximity={nns})")
    else:
        g["G1_distinguishable"] = {"fail": None, "note": "run --all for proximity", "verdict": "NEEDS_MODEL"}

    # Gate 2: destructive without authority
    destructive = bool(DESTRUCTIVE_RE.search(body))
    authority = bool(AUTHORITY_RE.search(body))
    g["G2_destructive_authority"] = {
        "fail": destructive and not authority,
        "note": f"destructive_verbs={destructive} confirmation_present={authority}",
        "verdict": "NEEDS_MODEL" if destructive else "PASS",
    }
    if destructive:
        out["needs_model"].append("G2: destructive/external verbs present — confirm a real confirmation gate guards them.")

    # Gate 3: PII into shared artifact
    pii_sink = bool(PII_SINK_RE.search(body))
    pii_guard = bool(PII_GUARD_RE.search(body))
    g["G3_pii_shared"] = {"fail": pii_sink and not pii_guard,
                          "note": f"external_sink={pii_sink} redaction/guard={pii_guard}",
                          "verdict": "NEEDS_MODEL" if pii_sink else "PASS"}
    if pii_sink:
        out["needs_model"].append("G3: content leaves the machine — confirm redaction/confirmation before it does.")

    # Gate 4: claims success without inspecting
    claims = bool(DONE_CLAIM_RE.search(body))
    inspects = bool(INSPECT_RE.search(body))
    g["G4_inspect_output"] = {"fail": claims and not inspects,
                              "note": f"success_claim={claims} inspect_language={inspects}",
                              "verdict": "NEEDS_MODEL"}
    out["needs_model"].append("G4: find where the skill declares done — does it read back the produced artifact/tool result?")

    # ---- referenced-path existence ----
    ref_paths = re.findall(r"(references/[A-Za-z0-9._/-]+|scripts/[A-Za-z0-9._/-]+)", body)
    missing = [rp for rp in set(ref_paths) if not (path.parent / rp).exists()]
    out["stale_references"] = missing

    # ---- provisional tier1 tally ----
    t1_earned = sum(v["pts"] for v in t1.values())
    t1_max = sum(v["max"] for v in t1.values())
    out["tier1_provisional"] = {"earned": t1_earned, "max": t1_max,
                                "note": "excludes T1.5-1.7 (NEEDS_MODEL) — model adds up to 22 more"}
    out["frontmatter_ok"] = bool(fm.get("name") and fm.get("description"))
    return out


def gather_skills(skills_dir: Path):
    res = []
    for d in sorted(skills_dir.iterdir()):
        sk = d / "SKILL.md"
        if sk.is_file():
            fm, _, _ = parse_skill(sk)
            res.append((fm.get("name", d.name), fm.get("description", "")))
    return res


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("target", nargs="?")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--skills-dir", default=".claude/skills")
    ap.add_argument("--origin", choices=["core", "user"])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    def infer_origin(p: Path):
        if a.origin:
            return a.origin
        s = str(p)
        return "user" if ("-custom" in s or "skills-custom" in s) else "core"

    if a.all:
        sd = Path(a.skills_dir)
        if not sd.is_dir():
            print(f"skills dir not found: {sd}", file=sys.stderr)
            return 3
        neighbors = gather_skills(sd)
        reports = []
        for d in sorted(sd.iterdir()):
            sk = d / "SKILL.md"
            if sk.is_file():
                reports.append(score_one(sk, infer_origin(sk), neighbors))
        # collisions
        collisions = []
        for i, (n, desc) in enumerate(neighbors):
            nn, nns = nearest_neighbor(n, desc, neighbors)
            if nns >= 0.6:
                collisions.append({"a": n, "b": nn, "proximity": nns})
        payload = {"count": len(reports), "collisions": collisions, "reports": reports}
        if a.json:
            print(json.dumps(payload, indent=2))
        else:
            print(f"# skill-score --all ({len(reports)} skills)\n")
            for r in reports:
                gate_fail = any(g.get("fail") is True for g in r["hard_gates"].values())
                print(f"- {r['skill']:28} origin={r['origin']:4} "
                      f"tier1={r['tier1_provisional']['earned']}/{r['tier1_provisional']['max']} "
                      f"{'HARD-GATE-RISK' if gate_fail else ''} "
                      f"{'STALE-REFS' if r['stale_references'] else ''}")
            if collisions:
                print("\n## routing collisions (proximity >= 0.6)")
                for c in collisions:
                    print(f"  {c['a']} <-> {c['b']}  ({c['proximity']})")
        return 0

    if not a.target:
        ap.print_help()
        return 3
    p = resolve(a.target)
    if not p.is_file():
        print(f"not found: {p}", file=sys.stderr)
        return 3
    sd = p.parent.parent
    neighbors = gather_skills(sd) if sd.is_dir() else None
    r = score_one(p, infer_origin(p), neighbors)
    if a.json:
        print(json.dumps(r, indent=2))
    else:
        print(f"# {r['skill']}  (origin={r['origin']})")
        print(f"Tier-1 mechanical: {r['tier1_provisional']['earned']}/{r['tier1_provisional']['max']} "
              f"(+ up to 22 from model on T1.5-1.7)")
        for k, v in r["tier1"].items():
            print(f"  {k}: {v['pts']}/{v['max']} — {v['note']}")
        print("Hard gates:")
        for k, v in r["hard_gates"].items():
            print(f"  {k}: fail={v['fail']} — {v['note']}")
        if r["stale_references"]:
            print(f"STALE REFERENCES: {r['stale_references']}")
        print("\nNEEDS_MODEL (the skill body decides these):")
        for n in r["needs_model"]:
            print(f"  - {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
