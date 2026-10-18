#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""codegraph — 轻量本地代码知识图谱（C++/QML/JS/Python，纯标准库）。

把工程的符号定义索引到 <root>/.codegraph/codegraph.db（SQLite+FTS5），
引用/影响面按需实时 grep 计算（永不因代码改动而过期）。
用法见同目录 ../SKILL.md。"""
import argparse
import hashlib
import os
import re
import sqlite3
import subprocess
import sys
import time

DB_DIR = ".codegraph"
DB_NAME = "codegraph.db"
VERSION = "1"

LANG_BY_EXT = {
    ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp", ".c": "cpp",
    ".h": "cpp", ".hpp": "cpp",
    ".qml": "qml", ".js": "js", ".py": "py",
    ".pro": "qmake", ".pri": "qmake",
}
GREP_EXTS = (".cpp", ".h", ".hpp", ".cc", ".cxx", ".c", ".qml", ".js", ".py")
SKIP_DIRS = {".codegraph", ".git", "node_modules", ".venv", "venv", "__pycache__", ".designer"}
SKIP_DIR_PREFIX = ("build-", "build_", "Build-")

# 常见控制关键字/宏，避免把调用误判为定义
BLOCK = {
    "if", "for", "while", "switch", "catch", "return", "sizeof", "case", "do",
    "else", "new", "delete", "emit", "connect", "define", "include", "ifdef",
    "ifndef", "endif", "pragma", "typedef", "using", "namespace", "operator",
    "assert", "qDebug", "qWarning", "qCritical", "qFatal", "qInfo",
    "static_cast", "dynamic_cast", "reinterpret_cast", "const_cast",
}

RE_CLASS = re.compile(r"^\s*(?:template\s*<[^>]*>\s*)?(class|struct|union)\s+([A-Za-z_]\w*)")
RE_ENUM = re.compile(r"^\s*enum\s+(?:class\s+)?([A-Za-z_]\w*)")
RE_DEFINE = re.compile(r"^\s*#\s*define\s+([A-Za-z_]\w*)")
RE_QUALIFIED = re.compile(
    r"^\s*(?:virtual\s+|static\s+|inline\s+|explicit\s+)*"
    r"[\w:<>,*&~\[\]\s]*?\b([A-Za-z_]\w*::~?[A-Za-z_]\w*)\s*\([^;]*$"
)
RE_FUNC = re.compile(
    r"^\s*(?:virtual\s+|static\s+|inline\s+|explicit\s+|friend\s+)*"
    r"(?:const\s+|unsigned\s+|signed\s+|struct\s+)*"
    r"[\w:<>,*&]+\s+[\w:<>,*&~\s]*?([A-Za-z_]\w*)\s*\([^;{}]*\)\s*"
    r"(?:const\s*)?(?:override\s*)?(?:noexcept\s*)?(?:final\s*)?(?:\{|$)"
)
RE_FUNC_OPEN = re.compile(
    r"^\s*(?:virtual\s+|static\s+|inline\s+|explicit\s+|friend\s+)*"
    r"(?:const\s+|unsigned\s+|signed\s+|struct\s+)*"
    r"[\w:<>,*&]+\s+[\w:<>,*&~\s]*?([A-Za-z_]\w*)\s*\(\s*$"
)
RE_QML_FUNC = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
RE_QML_SIGNAL = re.compile(r"\bsignal\s+([A-Za-z_]\w*)\s*\(")
RE_QML_PROP = re.compile(r"^\s*(?:readonly\s+)?property\s+[\w<>.]+\s+([A-Za-z_]\w*)")
RE_QML_ID = re.compile(r"^\s*id\s*:\s*([A-Za-z_]\w*)")
RE_JS_FUNC = re.compile(r"\bfunction\s+([A-Za-z_]\w*)\s*\(")
RE_JS_ASSIGN = re.compile(r"^\s*(?:const|let|var)\s+([A-Za-z_]\w*)\s*[:=]\s*function\b")
RE_JS_CLASS = re.compile(r"^\s*class\s+([A-Za-z_]\w*)")
RE_PY_DEF = re.compile(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)")
RE_PY_CLASS = re.compile(r"^\s*class\s+([A-Za-z_]\w*)")


# ---------- 扫描与解析 ----------

def iter_sources(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames
                       if d not in SKIP_DIRS and not d.startswith(SKIP_DIR_PREFIX)]
        for fn in filenames:
            if fn.startswith(("moc_", "ui_", "qrc_")):
                continue  # Qt 生成文件，不进图谱
            ext = os.path.splitext(fn)[1].lower()
            if ext in LANG_BY_EXT:
                ap = os.path.join(dirpath, fn)
                rel = os.path.relpath(ap, root).replace(os.sep, "/")
                yield rel, ap, LANG_BY_EXT[ext]


def ok_name(nm):
    return len(nm) >= 2 and nm not in BLOCK


def extract(rel, lang, text):
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("//") or s.startswith("*") or s.startswith("/*"):
            continue
        sig = s[:120]
        if lang == "cpp":
            m = RE_CLASS.match(line)
            if m:
                out.append((m.group(2), m.group(1), i, sig)); continue
            m = RE_ENUM.match(line)
            if m:
                out.append((m.group(1), "enum", i, sig)); continue
            m = RE_DEFINE.match(line)
            if m:
                out.append((m.group(1), "macro", i, sig)); continue
            if s.startswith("#"):
                continue
            first = s.split()[0]
            if first in BLOCK or not re.match(r"[\w:<>,*&~]", first):
                continue
            m = RE_QUALIFIED.match(line)
            if m:
                nm = m.group(1)
                if ok_name(nm.split("::")[-1]):
                    out.append((nm, "fn", i, sig))
                continue
            m = RE_FUNC.match(line) or RE_FUNC_OPEN.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "fn", i, sig))
        elif lang == "qml":
            m = RE_QML_FUNC.search(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "fn", i, sig)); continue
            m = RE_QML_SIGNAL.search(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "signal", i, sig)); continue
            m = RE_QML_PROP.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "property", i, sig)); continue
            m = RE_QML_ID.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "id", i, sig))
        elif lang == "js":
            m = RE_JS_CLASS.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "class", i, sig)); continue
            m = RE_JS_ASSIGN.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "fn", i, sig)); continue
            m = RE_JS_FUNC.search(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "fn", i, sig))
        elif lang == "py":
            m = RE_PY_CLASS.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "class", i, sig)); continue
            m = RE_PY_DEF.match(line)
            if m and ok_name(m.group(1)):
                out.append((m.group(1), "fn", i, sig))
    # 同文件同名同行去重（qualified 与 plain 可能重复命中）
    seen, uniq = set(), []
    for nm, kind, ln, sig in out:
        k = (nm, ln)
        if k not in seen:
            seen.add(k)
            uniq.append((nm, kind, ln, sig))
    return uniq


def sha1_file(ap):
    h = hashlib.sha1()
    with open(ap, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------- 数据库 ----------

def db_path(root):
    return os.path.join(root, DB_DIR, DB_NAME)


def connect(root):
    d = os.path.join(root, DB_DIR)
    os.makedirs(d, exist_ok=True)
    con = sqlite3.connect(db_path(root))
    con.executescript("""
        CREATE TABLE IF NOT EXISTS meta(k TEXT PRIMARY KEY, v TEXT);
        CREATE TABLE IF NOT EXISTS files(
            path TEXT PRIMARY KEY, lang TEXT, size INTEGER, mtime REAL, sha1 TEXT);
        CREATE TABLE IF NOT EXISTS symbols(
            id INTEGER PRIMARY KEY, name TEXT, base TEXT, kind TEXT,
            lang TEXT, file TEXT, line INTEGER, sig TEXT);
        CREATE INDEX IF NOT EXISTS idx_symbols_base ON symbols(base);
        CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file);
        CREATE VIRTUAL TABLE IF NOT EXISTS sym_fts USING fts5(
            name, sig, file, tokenize='unicode61', prefix='2 3 4');
    """)
    return con


def drop_file(con, rel):
    ids = [r[0] for r in con.execute("SELECT id FROM symbols WHERE file=?", (rel,))]
    for sid in ids:
        con.execute("DELETE FROM sym_fts WHERE rowid=?", (sid,))
    con.execute("DELETE FROM symbols WHERE file=?", (rel,))
    con.execute("DELETE FROM files WHERE path=?", (rel,))


def index_file(con, root, rel, ap, lang):
    with open(ap, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8", errors="replace")
    con.execute("DELETE FROM files WHERE path=?", (rel,))
    con.execute("INSERT INTO files(path, lang, size, mtime, sha1) VALUES(?,?,?,?,?)",
                (rel, lang, len(raw), os.path.getmtime(ap), hashlib.sha1(raw).hexdigest()))
    for nm, kind, ln, sig in extract(rel, lang, text):
        cur = con.execute(
            "INSERT INTO symbols(name, base, kind, lang, file, line, sig) VALUES(?,?,?,?,?,?,?)",
            (nm, nm.split("::")[-1], kind, lang, rel, ln, sig))
        con.execute("INSERT INTO sym_fts(rowid, name, sig, file) VALUES(?,?,?,?)",
                    (cur.lastrowid, nm, sig, rel))
    return len(extract(rel, lang, text))


def require_db(root):
    if not os.path.exists(db_path(root)):
        sys.exit(f"[codegraph] 工程尚无索引 ({db_path(root)})，先运行: codegraph build {root}")


# ---------- grep 实时引用 ----------

def grep_refs(root, name):
    pat = r"\b" + re.escape(name) + r"\b"
    cmd = ["grep", "-rnE", "-I"]
    cmd += [f"--include=*{e}" for e in GREP_EXTS]
    cmd += [f"--exclude-dir={d}" for d in sorted(SKIP_DIRS)]
    cmd += [f"--exclude-dir={p}*" for p in SKIP_DIR_PREFIX]
    cmd += ["--exclude=moc_*", "--exclude=ui_*", "--exclude=qrc_*"]
    cmd += ["--", pat, "."]
    r = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    return [l for l in r.stdout.splitlines() if l]


def norm_rel(root, p):
    # 相对路径按工程根解释（而不是当前工作目录）
    if not os.path.isabs(p):
        p = os.path.join(root, p)
    p = os.path.abspath(p)
    try:
        return os.path.relpath(p, root).replace(os.sep, "/")
    except ValueError:
        return p.replace(os.sep, "/")


def split_grep_line(line):
    # "./Program/x.cpp:123:content"
    parts = line.split(":", 2)
    if len(parts) < 3:
        return None
    f, ln, txt = parts
    if f.startswith("./"):
        f = f[2:]
    return f, ln, txt.strip()


# ---------- 命令 ----------

def cmd_build(root):
    t0 = time.time()
    con = connect(root)
    con.execute("DELETE FROM sym_fts")
    con.execute("DELETE FROM symbols")
    con.execute("DELETE FROM files")
    nf = ns = 0
    kinds = {}
    for rel, ap, lang in iter_sources(root):
        ns += index_file(con, root, rel, ap, lang)
        nf += 1
    for (k, c) in con.execute("SELECT kind, COUNT(*) FROM symbols GROUP BY kind"):
        kinds[k] = c
    meta = {"root": root, "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "version": VERSION, "files": str(nf), "symbols": str(ns)}
    for k, v in meta.items():
        con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES(?,?)", (k, v))
    con.commit()
    kd = " ".join(f"{k}:{v}" for k, v in sorted(kinds.items(), key=lambda x: -x[1]))
    print(f"[codegraph] build 完成: {nf} 文件, {ns} 符号 ({kd}), 用时 {time.time()-t0:.1f}s")
    print(f"[codegraph] 索引: {db_path(root)}")


def cmd_update(root):
    require_db(root)
    t0 = time.time()
    con = connect(root)
    indexed = {r[0]: (r[1], r[2]) for r in con.execute("SELECT path, size, sha1 FROM files")}
    seen, added, changed, removed = set(), 0, 0, 0
    for rel, ap, lang in iter_sources(root):
        seen.add(rel)
        if rel not in indexed:
            drop_file(con, rel)
            index_file(con, root, rel, ap, lang)
            added += 1
        else:
            size, old_sha = indexed.pop(rel)
            if size != os.path.getsize(ap) or sha1_file(ap) != old_sha:
                drop_file(con, rel)
                index_file(con, root, rel, ap, lang)
                changed += 1
    for rel in indexed:  # 磁盘上已不存在
        drop_file(con, rel)
        removed += 1
    con.execute("INSERT OR REPLACE INTO meta(k,v) VALUES('built_at', ?)",
                (time.strftime("%Y-%m-%d %H:%M:%S"),))
    con.commit()
    print(f"[codegraph] update 完成: 新增 {added}, 更新 {changed}, 删除 {removed}, "
          f"用时 {time.time()-t0:.1f}s")


def cmd_status(root):
    require_db(root)
    con = connect(root)
    ns, = con.execute("SELECT COUNT(*) FROM symbols").fetchone()
    built = con.execute("SELECT v FROM meta WHERE k='built_at'").fetchone()
    indexed = {r[0]: (r[1], r[2]) for r in con.execute("SELECT path, size, sha1 FROM files")}
    new, mod = [], []
    disk = set()
    for rel, ap, lang in iter_sources(root):
        disk.add(rel)
        if rel not in indexed:
            new.append(rel)
        else:
            size, old_sha = indexed[rel]
            if size != os.path.getsize(ap) or sha1_file(ap) != old_sha:
                mod.append(rel)
    gone = sorted(set(indexed) - disk)
    print(f"[codegraph] 索引: {len(indexed)} 文件 / {ns} 符号, 建于 {built[0] if built else '?'}")
    print(f"[codegraph] 待更新: 新增 {len(new)}, 修改 {len(mod)}, 删除 {len(gone)}")
    for label, items in (("新增", new), ("修改", mod), ("删除", gone)):
        for p in items[:15]:
            print(f"  {label}: {p}")
        if len(items) > 15:
            print(f"  ...（{label}共 {len(items)} 个）")
    if not (new or mod or gone):
        print("[codegraph] 索引与磁盘一致，无需更新")


def cmd_search(root, query):
    require_db(root)
    con = connect(root)
    toks = [t for t in re.findall(r"[A-Za-z_]\w*", query) if len(t) >= 2]
    if not toks:
        sys.exit("[codegraph] 查询词太短")
    match = " AND ".join(f'"{t}"*' for t in toks)
    rows = con.execute(
        "SELECT s.name, s.kind, s.file, s.line, s.sig FROM sym_fts f "
        "JOIN symbols s ON s.id = f.rowid WHERE sym_fts MATCH ? "
        "ORDER BY bm25(sym_fts) LIMIT 40", (match,)).fetchall()
    print(f"[codegraph] search '{query}' → {len(rows)} 条（最多显示 40）")
    for name, kind, f, ln, sig in rows:
        print(f"  {f}:{ln}  [{kind}] {name}    {sig}")


def cmd_defs(root, name):
    require_db(root)
    con = connect(root)
    base = name.split("::")[-1]
    rows = con.execute(
        "SELECT name, kind, file, line, sig FROM symbols WHERE base=? OR name=? "
        "ORDER BY file, line LIMIT 60", (base, name)).fetchall()
    print(f"[codegraph] defs '{name}' → {len(rows)} 处定义")
    for nm, kind, f, ln, sig in rows:
        print(f"  {f}:{ln}  [{kind}] {nm}    {sig}")


def cmd_refs(root, name, cap=100):
    require_db(root)
    pat_name = name if "::" in name else name.split("::")[-1]
    lines = grep_refs(root, pat_name)
    print(f"[codegraph] refs '{name}' → {len(lines)} 处引用（含定义行，最多显示 {cap}）")
    for l in lines[:cap]:
        p = split_grep_line(l)
        if p:
            print(f"  {p[0]}:{p[1]}  {p[2][:110]}")
    if len(lines) > cap:
        print(f"  ...（共 {len(lines)} 处）")


def cmd_impact(root, targets, cap_sym=40):
    require_db(root)
    con = connect(root)
    # 同名方法（在多处类中重复定义）按类名过滤，避免把别的类的同名方法算进来
    common = {r[0] for r in con.execute(
        "SELECT base FROM symbols WHERE kind='fn' GROUP BY base "
        "HAVING COUNT(DISTINCT file) > 5")}
    all_dep = {}
    for t in targets:
        rel = norm_rel(root, t)
        row = con.execute("SELECT COUNT(*) FROM symbols WHERE file=?", (rel,)).fetchone()
        if not row[0]:
            print(f"=== {rel}: 索引里没有该文件的符号（可能非源码/路径错误）")
            continue
        syms = con.execute(
            "SELECT name, kind, line FROM symbols WHERE file=? ORDER BY line", (rel,)).fetchall()
        print(f"=== {rel}: {len(syms)} 个符号，外部引用如下 ===")
        shown = 0
        for name, kind, ln in syms:
            if kind == "id":
                continue
            parts = name.split("::")
            base, cls = parts[-1], (parts[0] if len(parts) > 1 else None)
            cls_files = None
            if base in common and cls:
                cls_files = set()
                for l in grep_refs(root, cls):
                    p2 = split_grep_line(l)
                    if p2:
                        cls_files.add(p2[0])
            deps = {}
            for l in grep_refs(root, base):
                p = split_grep_line(l)
                if not p or p[0] == rel:
                    continue
                if cls_files is not None and p[0] not in cls_files:
                    continue
                deps[p[0]] = deps.get(p[0], 0) + 1
            if deps:
                fl = ", ".join(f"{f}({n})" for f, n in
                               sorted(deps.items(), key=lambda x: -x[1])[:6])
                mark = "  [同名方法已按类过滤]" if cls_files is not None else ""
                print(f"  [{kind}] {name}  ({rel}:{ln}) ← {len(deps)} 文件: {fl}{mark}")
                all_dep.update(deps)
                shown += 1
            if shown >= cap_sym:
                print("  ...（符号过多，已截断）")
                break
    if all_dep:
        print(f"\n[codegraph] 合计影响 {len(all_dep)} 个文件: "
              + ", ".join(sorted(all_dep)[:30]))


def cmd_explore(root, term):
    require_db(root)
    con = connect(root)
    rel = norm_rel(root, term)
    hit = con.execute("SELECT COUNT(*) FROM files WHERE path=?", (rel,)).fetchone()[0]
    if hit:
        cmd_impact(root, [rel])
    else:
        cmd_defs(root, term)
        print()
        cmd_refs(root, term, cap=40)


def main():
    ap = argparse.ArgumentParser(prog="codegraph", description="轻量本地代码知识图谱")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, help_ in (("build", "全量建索引"), ("update", "增量更新"),
                        ("status", "查看索引状态/待更新文件")):
        p = sub.add_parser(name, help=help_)
        p.add_argument("root", help="工程根目录")
    p = sub.add_parser("search", help="按名字/关键字搜索符号")
    p.add_argument("root"); p.add_argument("query", nargs="+")
    p = sub.add_parser("defs", help="查符号定义位置")
    p.add_argument("root"); p.add_argument("name")
    p = sub.add_parser("refs", help="查符号的全部引用")
    p.add_argument("root"); p.add_argument("name")
    p = sub.add_parser("impact", help="改某文件的影响面")
    p.add_argument("root"); p.add_argument("files", nargs="+")
    p = sub.add_parser("explore", help="一个入口查完：文件名→影响面；符号→定义+引用")
    p.add_argument("root"); p.add_argument("term")
    args = ap.parse_args()

    root = os.path.abspath(args.root)
    if not os.path.isdir(root):
        sys.exit(f"[codegraph] 目录不存在: {root}")

    if args.cmd == "build":
        cmd_build(root)
    elif args.cmd == "update":
        cmd_update(root)
    elif args.cmd == "status":
        cmd_status(root)
    elif args.cmd == "search":
        cmd_search(root, " ".join(args.query))
    elif args.cmd == "defs":
        cmd_defs(root, args.name)
    elif args.cmd == "refs":
        cmd_refs(root, args.name)
    elif args.cmd == "impact":
        cmd_impact(root, args.files)
    elif args.cmd == "explore":
        cmd_explore(root, args.term)


if __name__ == "__main__":
    main()
