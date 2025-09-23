"""
Caracas Bot — Auto Tidy Toolkit
Автоматизирует наведение порядка в проекте:
• нормализует config.yaml под Settings (переименование ключей, добавление недостающих);
• добавляет __init__.py в подпакеты src/*;
• перемещает *.bak / дубли в archive/ (или удаляет по флагу);
• формирует отчёты: дерево с SHA1, дубли, ключи YAML, ключи кода, missing/dead keys;
• опционально прогоняет форматирование (ruff/black) — если установлены.

Использование (из корня проекта):
  python tools/tidy_bot.py --apply --archive-bak --add-inits

Режим сухого прогона:
  python tools/tidy_bot.py --dry-run
"""

import argparse, hashlib, os, re, sys, json, shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple, Any

RENAME_KEYS = {"API_KEY": "BINANCE_API_KEY","API_SECRET": "BINANCE_API_SECRET"}
REMOVE_KEYS = {"REQUIRE_VWAP"}

DEFAULTS = {
    "BINANCE_API_KEY": "",
    "BINANCE_API_SECRET": "",
    "TESTNET": False,
    "SYMBOLS": [],
    "SRT_MODE": "STRICT",
    "TOTAL_FILTERS_REQUIRED": 7,
    "MIN_RR1": 1.2,
    "EMA_FAST": 21,
    "EMA_MID": 50,
    "EMA_SLOW": 200,
    "RSI_PERIOD": 14,
    "RSI_BUY_LVL": 52.0,
    "RSI_SELL_LVL": 48.0,
    "OI_MIN_CHANGE_PCT_15M": 1.0,
}

def _import_yaml():
    try:
        import ruamel.yaml as ruyaml
        return "ruamel", ruyaml
    except Exception:
        import yaml
        return "pyyaml", yaml

def load_yaml(path: Path):
    ylib_name, ylib = _import_yaml()
    if ylib_name == "ruamel":
        yaml = ylib.YAML()
        yaml.preserve_quotes = True
        data = yaml.load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        return ylib_name, (yaml, data)
    else:
        data = ylib.safe_load(path.read_text(encoding="utf-8", errors="ignore")) or {}
        return ylib_name, data

def save_yaml(path: Path, ylib_name: str, obj):
    if ylib_name == "ruamel":
        yaml, data = obj
        with path.open("w", encoding="utf-8") as f:
            yaml.dump(data, f)
    else:
        import yaml
        with path.open("w", encoding="utf-8") as f:
            yaml.safe_dump(obj, f, allow_unicode=True, sort_keys=False)

def flatten_yaml(prefix: str, obj, out):
    from collections.abc import Mapping
    if isinstance(obj, Mapping):
        for k, v in obj.items():
            flatten_yaml(f"{prefix}.{k}" if prefix else str(k), v, out)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            flatten_yaml(f"{prefix}[{i}]", v, out)
    else:
        out.append((prefix, obj))

def sha1_bytes(b: bytes) -> str:
    import hashlib
    return hashlib.sha1(b).hexdigest()

def list_py_dirs(src_dir: Path):
    out = []
    for d in src_dir.rglob("*"):
        if d.is_dir():
            if any(part in (".venv", "__pycache__") for part in d.parts):
                continue
            if any(p.suffix == ".py" for p in d.iterdir() if p.is_file()):
                out.append(d)
    return out

def collect_python_files(root: Path):
    files = []
    for p in root.rglob("*.py"):
        if any(part in (".venv",) for part in p.parts):
            continue
        files.append(p)
    return files

def build_tree_hashes(root: Path):
    rows = []
    for p in root.rglob("*"):
        if any(part in (".venv",) for part in p.parts):
            continue
        if p.is_file():
            data = p.read_bytes()
            rows.append({"path": str(p.relative_to(root)), "size": len(data), "sha1": sha1_bytes(data)})
    return sorted(rows, key=lambda r: r["path"])

def exact_duplicates(rows):
    from collections import defaultdict
    by = defaultdict(list)
    for r in rows:
        by[r["sha1"]].append(r["path"])
    return [files for files in by.values() if len(files) > 1]

@dataclass
class Actions:
    add_inits: bool = False
    archive_bak: bool = False
    delete_bak: bool = False
    normalize_config: bool = True
    apply: bool = False

def tidy(root: Path, actions: Actions, min_rr1: float | None = None):
    report = {"changes": [], "warnings": [], "errors": [], "summary": {}}
    src = root / "src"
    cfg = root / "config.yaml"
    arch = root / "archive"
    arch.mkdir(exist_ok=True)

    rows = build_tree_hashes(root)
    (root / "tidy_report.tree.sha1.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    dups = exact_duplicates(rows)
    (root / "tidy_report.duplicates.json").write_text(json.dumps(dups, ensure_ascii=False, indent=2), encoding="utf-8")
    report["summary"]["duplicates_count"] = len(dups)

    bak_files = [Path(root, r["path"]) for r in rows if r["path"].endswith(".bak")]
    report["summary"]["bak_count"] = len(bak_files)
    for f in bak_files:
        if actions.archive_bak:
            if actions.apply:
                dest = arch / f.name
                dest.parent.mkdir(parents=True, exist_ok=True)
                try:
                    f.rename(dest)
                except Exception:
                    import shutil
                    shutil.move(str(f), str(dest))
                report["changes"].append(f"ARCHIVE {f} -> {dest}")
            else:
                report["changes"].append(f"[DRY] ARCHIVE {f}")
        elif actions.delete_bak:
            if actions.apply:
                f.unlink(missing_ok=True)
                report["changes"].append(f"DELETE {f}")
            else:
                report["changes"].append(f"[DRY] DELETE {f}")
        else:
            report["warnings"].append(f"Found .bak: {f} (use --archive-bak or --delete-bak)")

    if actions.add_inits and src.exists():
        pkg_dirs = list_py_dirs(src)
        for d in pkg_dirs:
            initp = d / "__init__.py"
            if not initp.exists():
                if actions.apply:
                    initp.write_text('"""Package."""\n', encoding="utf-8")
                    report["changes"].append(f"ADD __init__.py -> {d}")
                else:
                    report["changes"].append(f"[DRY] ADD __init__.py -> {d}")

    if actions.normalize_config and cfg.exists():
        yname, y = load_yaml(cfg)
        if yname == "ruamel":
            yaml_obj, data = y
            mapping = data
        else:
            mapping = y

        for old, new in RENAME_KEYS.items():
            if old in mapping and new not in mapping:
                val = mapping.pop(old)
                mapping[new] = val
                report["changes"].append(f"CONFIG: rename {old} -> {new}")
            elif old in mapping and new in mapping:
                report["warnings"].append(f"CONFIG: both {old} and {new} present; keeping {new}, dropping {old}")
                mapping.pop(old, None)
                report["changes"].append(f"CONFIG: drop {old} (duplicate of {new})")

        for dead in sorted(REMOVE_KEYS):
            if dead in mapping:
                mapping.pop(dead, None)
                report["changes"].append(f"CONFIG: remove dead key {dead}")

        for k, v in DEFAULTS.items():
            if k not in mapping:
                mapping[k] = v
                report["changes"].append(f"CONFIG: add missing {k}={v!r}")

        if min_rr1 is not None:
            mapping["MIN_RR1"] = float(min_rr1)
            report["changes"].append(f"CONFIG: set MIN_RR1={min_rr1}")

        if actions.apply:
            if yname == "ruamel":
                save_yaml(cfg, yname, (yaml_obj, mapping))
            else:
                save_yaml(cfg, yname, mapping)
        else:
            report["changes"].append(f"[DRY] CONFIG: would save normalized YAML")

        flat = []
        flatten_yaml("", mapping, flat)
        (root / "tidy_report.config_flat.csv").write_text(
            "yaml_path,value\n" + "\n".join([f"{p},{repr(v)}" for p, v in flat]), encoding="utf-8"
        )

    py_files = collect_python_files(root)
    attr_refs, sub_refs = [], []
    import ast
    for p in py_files:
        try:
            tree = ast.parse(Path(p).read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        class V(ast.NodeVisitor):
            def visit_Attribute(self, node):
                if isinstance(node.value, ast.Name) and node.attr.isupper():
                    if node.value.id in ("cfg","s","settings"):
                        attr_refs.append({"file": str(Path(p).relative_to(root)), "line": node.lineno, "key": node.attr})
                self.generic_visit(node)
            def visit_Subscript(self, node):
                try:
                    if isinstance(node.value, ast.Name) and node.value.id in ("cfg","config","CFG","s","settings"):
                        sl = getattr(node.slice, "value", None)
                        if isinstance(sl, ast.Constant) and isinstance(sl.value, str):
                            sub_refs.append({"file": str(Path(p).relative_to(root)), "line": node.lineno, "key": sl.value})
                except Exception:
                    pass
                self.generic_visit(node)
        V().visit(tree)

    (root / "tidy_report.cfg_attr_refs.json").write_text(json.dumps(attr_refs, ensure_ascii=False, indent=2), encoding="utf-8")
    (root / "tidy_report.cfg_subscript_refs.json").write_text(json.dumps(sub_refs, ensure_ascii=False, indent=2), encoding="utf-8")

    report["summary"]["changes"] = len(report["changes"])
    report["summary"]["warnings"] = len(report["warnings"])
    (root / "tidy_report.summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report

def main():
    ap = argparse.ArgumentParser(description="Auto-tidy for Caracas bot project")
    ap.add_argument("--root", default=".", help="Корень проекта (где лежит src/ и config.yaml)")
    ap.add_argument("--dry-run", action="store_true", help="Только отчёт без изменений")
    ap.add_argument("--apply", action="store_true", help="Внести изменения")
    ap.add_argument("--archive-bak", action="store_true", help="Переместить *.bak в archive/")
    ap.add_argument("--delete-bak", action="store_true", help="Удалить *.bak (опасно)")
    ap.add_argument("--add-inits", action="store_true", help="Добавить __init__.py в подпакеты src/*")
    ap.add_argument("--min-rr1", type=float, default=None, help="Принудительно выставить MIN_RR1 (например, 1.8)")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    actions = Actions(
        add_inits=args.add_inits,
        archive_bak=args.archive_bak,
        delete_bak=args.delete_bak,
        normalize_config=True,
        apply=args.apply and not args.dry_run,
    )
    rep = tidy(root, actions, min_rr1=args.min_rr1)
    print(json.dumps(rep["summary"], ensure_ascii=False, indent=2))
    if rep["warnings"]:
        print("\nWarnings:")
        for w in rep["warnings"]:
            print(" -", w)

if __name__ == "__main__":
    main()
