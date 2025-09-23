
#!/usr/bin/env python3
# apply_mandatory5_patch.py
"""
Patch your bot to require at least 5 mandatory filters out of 8.
- Adds config fields to src/config.py: MANDATORY_FILTERS, MANDATORY_REQUIRE_N
- Enforces the gate in src/signals/detector_h15.py after `greens` dict.
Usage:
    python apply_mandatory5_patch.py --root /path/to/bot3
"""
import argparse, sys, re
from pathlib import Path

def patch_config(p: Path) -> bool:
    txt = p.read_text(encoding="utf-8")
    if "MANDATORY_REQUIRE_N" in txt and "MANDATORY_FILTERS" in txt:
        return False
    # Try to insert after SWING_LOOKBACK_H15 line inside Settings class
    pattern = r"(SWING_LOOKBACK_H15:\s*int\s*=\s*12[^\n]*\n)"
    repl = r"\1\n    MANDATORY_FILTERS: list[str] = [\"liquidity\",\"atr\",\"trend\",\"sr\",\"adx\"]\n    MANDATORY_REQUIRE_N: int = 5\n"
    new = re.sub(pattern, repl, txt, count=1)
    if new == txt:
        # Fallback: just before 'def load_settings'
        idx = txt.find("def load_settings")
        if idx != -1:
            head = txt[:idx]
            tail = txt[idx:]
            ins = "\n    MANDATORY_FILTERS: list[str] = [\"liquidity\",\"atr\",\"trend\",\"sr\",\"adx\"]\n    MANDATORY_REQUIRE_N: int = 5\n"
            # crude insert at end of class by searching last occurrence of 'SWING_LOOKBACK_H15' or class end
            cstart = head.find("class Settings(BaseModel):")
            if cstart != -1:
                new = head[:cstart] + head[cstart:] + ins + tail
            else:
                new = head + ins + tail
    p.write_text(new, encoding="utf-8")
    return True

def patch_detector(p: Path) -> bool:
    txt = p.read_text(encoding="utf-8")
    if "MANDATORY_REQUIRE_N" in txt and "mandatory and req_n > 0" in txt:
        return False
    # Find the greens dict
    g_start = txt.find("greens = {")
    if g_start == -1:
        raise RuntimeError("greens dict not found in detector_h15.py")
    # Find closing brace of that dict
    # Simple heuristic: find the next '}\n' after g_start
    close_idx = txt.find("}\n", g_start)
    if close_idx == -1:
        raise RuntimeError("could not locate end of greens dict")
    insert_at = close_idx + 2
    gate = (
        "\n    # Mandatory filters gate (require N of selected filters)\n"
        "    mandatory = getattr(s, \"MANDATORY_FILTERS\", [])\n"
        "    req_n = int(getattr(s, \"MANDATORY_REQUIRE_N\", 0) or 0)\n"
        "    if mandatory and req_n > 0:\n"
        "        cnt = sum(1 for name in mandatory if greens.get(name, False))\n"
        "        if cnt < req_n:\n"
        "            return None\n"
        "\n"
    )
    new = txt[:insert_at] + gate + txt[insert_at:]
    p.write_text(new, encoding="utf-8")
    return True

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=str, required=True, help="Path to your bot root (folder containing src/)")
    args = ap.parse_args()
    root = Path(args.root)
    cfg = root / "src" / "config.py"
    det = root / "src" / "signals" / "detector_h15.py"
    changed = []
    if not cfg.exists() or not det.exists():
        print("✗ Could not find expected files. Make sure --root points to your bot folder containing src/.")
        sys.exit(1)
    if patch_config(cfg):
        changed.append("src/config.py")
    if patch_detector(det):
        changed.append("src/signals/detector_h15.py")
    if changed:
        print("✓ Patched:", ", ".join(changed))
    else:
        print("• No changes applied (already patched).")

if __name__ == "__main__":
    main()
