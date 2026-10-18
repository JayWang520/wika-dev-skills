#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
WIKA_translate_skill - i18n helper for WIKA LangStr-based translation cpp files.

Translation files follow a fixed convention (see references/format.md):

    #include "FUNC_ChineseSimp.h"
    FUNC_ChineseSimp::FUNC_ChineseSimp()
    {
        LangStr.clear();
        LangStr.append("控制器总线报警");
        LangStr.append("DM总线报警");
        ...
    }

* The class fills a QStringList / QList<QString> named `LangStr`.
* The CHINESE file (master) holds every UI string in order.
* Each language file MUST hold the SAME number of entries in the SAME order
  (translation is by index). Keeping this index alignment is the hard invariant.

Subcommands
-----------
  scan          find Chinese terms in source files NOT yet in the master cpp.
  apply-master  append new (Chinese) terms to the master cpp (idempotent).
  init-lang     generate a brand-new language cpp from the (full) master.
  add-lang      append only the NEW entries (master tail) to a language cpp.
  check         verify every language cpp has the same entry count as master.

Only the Python standard library is used.
"""

import argparse
import json
import os
import re
import sys

# A double-quoted C string literal (handles escaped quotes/backslashes).
STRING_RE = re.compile(r'"[^"\\]*(?:\\.[^"\\]*)*"')
# Captures the raw content inside LangStr.append("...").
APPEND_RE = re.compile(r'Lang[Ss]tr\.append\(\s*"([^"\\]*(?:\\.[^"\\]*)*)"\s*\)\s*;')
# CJK ideographs (covers the bulk of WIKA UI terms).
CJK_RE = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')

SRC_EXTS = {".cpp", ".cc", ".cxx", ".c", ".h", ".hpp", ".hxx", ".ui"}


# --------------------------------------------------------------------------
# Parsing helpers
# --------------------------------------------------------------------------

def read_entries(path):
    """Ordered list of raw string contents inside LangStr.append(...)."""
    entries = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = APPEND_RE.search(line)
            if m:
                entries.append(m.group(1))
    return entries


def class_base_from_path(path):
    """FUNC_English.cpp -> FUNC_English (class name == header base)."""
    name = os.path.basename(path)
    if name.lower().endswith(".cpp"):
        name = name[:-4]
    return name


def strip_block_comments(line, in_block):
    """Remove /* ... */ regions from a line. Returns (code, in_block)."""
    out = []
    i = 0
    n = len(line)
    while i < n:
        if in_block:
            j = line.find("*/", i)
            if j == -1:
                return "", True
            i = j + 2
            in_block = False
        else:
            k = line.find("/*", i)
            if k == -1:
                out.append(line[i:])
                i = n
            else:
                out.append(line[i:k])
                i = k + 2
                in_block = True
    return "".join(out), in_block


def strip_line_comment(code):
    """Remove // comments, but never inside a string literal."""
    spans = [(m.start(), m.end()) for m in STRING_RE.finditer(code)]
    idx = code.find("//")
    while idx != -1:
        if not any(s <= idx < e for s, e in spans):
            return code[:idx]
        idx = code.find("//", idx + 2)
    return code


def find_chinese_terms(code):
    """Yield raw contents of double-quoted strings that contain CJK."""
    for m in STRING_RE.finditer(code):
        content = m.group(0)[1:-1]  # strip surrounding quotes
        if CJK_RE.search(content):
            yield content


CTOR_RE = re.compile(r'\b([A-Za-z_]\w*)::\1\s*\(')


def find_ctor_close(lines, base=None):
    """Return (line_index, class_name) of the constructor's closing brace.

    Matches the first self-referential constructor `Class::Class(` in the file,
    so it works regardless of the file's base name. `base` is accepted for
    backward compatibility but no longer required.
    """
    start = None
    class_name = None
    for i, line in enumerate(lines):
        m = CTOR_RE.search(line)
        if m:
            start = i
            class_name = m.group(1)
            break
    if start is None:
        return None, None
    depth = 0
    entered = False
    for i in range(start, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
                entered = True
            elif ch == "}":
                depth -= 1
                if entered and depth == 0:
                    return i, class_name
    return None, class_name


LANGSTR_ID_RE = re.compile(r'\bLang[Ss]tr\b')


def detect_langstr_id(path):
    """Detect whether the file declares LangStr or Langstr (case-sensitive id)."""
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                m = LANGSTR_ID_RE.search(line)
                if m:
                    return m.group(0)
    except OSError:
        pass
    return "Langstr"


def emit_line(value, untranslated=False, lang_id="Langstr"):
    # Escape double quotes; keep backslashes verbatim to match source style.
    safe = value.replace('"', '\\"')
    line = '    %s.append("%s");' % (lang_id, safe)
    if untranslated:
        line += "  // UNTRANSLATED"
    return line


def load_json(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def iter_source_files(paths):
    for p in paths:
        if os.path.isdir(p):
            for root, _dirs, files in os.walk(p):
                for f in files:
                    if os.path.splitext(f)[1].lower() in SRC_EXTS:
                        yield os.path.join(root, f)
        else:
            yield p


def insert_before_ctor_close(lines, base=None, block=None):
    """Insert `block` (list of strings) right before the ctor's closing brace."""
    close_idx, _ = find_ctor_close(lines, base)
    if close_idx is None:
        return None
    return lines[:close_idx] + [l + "\n" for l in block] + lines[close_idx:]


# --------------------------------------------------------------------------
# Subcommands
# --------------------------------------------------------------------------

def cmd_scan(args):
    master = set(read_entries(args.master))
    seen = set()
    new_terms = []
    for src in iter_source_files(args.sources):
        in_block = False
        with open(src, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                code, in_block = strip_block_comments(line, in_block)
                code = strip_line_comment(code)
                for term in find_chinese_terms(code):
                    if term in master or term in seen:
                        continue
                    seen.add(term)
                    new_terms.append(term)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(new_terms, fh, ensure_ascii=False, indent=2)
        sys.stderr.write("[scan] %d new term(s) -> %s\n" % (len(new_terms), args.out))
    for t in new_terms:
        print(t)
    sys.stderr.write("[scan] %d new term(s) found.\n" % len(new_terms))
    return 0


def cmd_apply_master(args):
    terms = load_json(args.terms)
    if not isinstance(terms, list):
        sys.stderr.write("[apply-master] ERROR: terms file must be a JSON array\n")
        return 2
    with open(args.master, "r", encoding="utf-8", errors="replace") as fh:
        lines = fh.readlines()
    base = class_base_from_path(args.master)
    existing = set(read_entries(args.master))
    to_add = [t for t in terms if t not in existing]
    if not to_add:
        sys.stderr.write("[apply-master] master already contains all %d term(s).\n" % len(terms))
        return 0
    lang_id = detect_langstr_id(args.master)
    block = [emit_line(t, lang_id=lang_id) for t in to_add]
    new_lines = insert_before_ctor_close(lines, base, block)
    if new_lines is None:
        sys.stderr.write("[apply-master] ERROR: ctor close not found\n")
        return 2
    with open(args.master, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    sys.stderr.write("[apply-master] appended %d term(s) to %s.\n" % (len(to_add), args.master))
    return 0


def cmd_init_lang(args):
    master = read_entries(args.master)
    trans = load_json(args.translations) if args.translations else {}
    base = class_base_from_path(args.output)
    lang_id = detect_langstr_id(args.master)
    lines = ['// Auto-generated by WIKA_translate_skill',
             '#include "%s.h"' % base,
             '%s::%s()' % (base, base),
             '{',
             '    %s.clear();' % lang_id]
    for entry in master:
        tr = trans.get(entry)
        if tr is None:
            lines.append(emit_line(entry, untranslated=True, lang_id=lang_id))
        else:
            lines.append(emit_line(tr, lang_id=lang_id))
    lines.append('}')
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines) + "\n")
    sys.stderr.write("[init-lang] wrote %s with %d entries.\n" % (args.output, len(master)))
    return 0


def cmd_add_lang(args):
    master = read_entries(args.master)
    trans = load_json(args.translations) if args.translations else {}
    with open(args.lang, "r", encoding="utf-8", errors="replace") as fh:
        lang_lines = fh.readlines()
    base = class_base_from_path(args.lang)
    lang_entries = read_entries(args.lang)
    if len(lang_entries) > len(master):
        sys.stderr.write("[add-lang] ERROR: %s has %d entries, more than master (%d). "
                         "Aborting to protect alignment.\n"
                         % (args.lang, len(lang_entries), len(master)))
        return 2
    missing = master[len(lang_entries):]  # the new tail, in master order
    if not missing:
        sys.stderr.write("[add-lang] %s already aligned (%d entries).\n"
                         % (args.lang, len(lang_entries)))
        return 0
    lang_id = detect_langstr_id(args.lang)
    block = []
    for entry in missing:
        tr = trans.get(entry)
        if tr is None:
            block.append(emit_line(entry, untranslated=True, lang_id=lang_id))
        else:
            block.append(emit_line(tr, lang_id=lang_id))
    new_lines = insert_before_ctor_close(lang_lines, base, block)
    if new_lines is None:
        sys.stderr.write("[add-lang] ERROR: ctor close not found in %s\n" % args.lang)
        return 2
    with open(args.lang, "w", encoding="utf-8") as fh:
        fh.writelines(new_lines)
    sys.stderr.write("[add-lang] appended %d new entr(y/ies) to %s.\n"
                     % (len(missing), args.lang))
    return 0


def cmd_check(args):
    master = read_entries(args.master)
    problems = 0
    for lang in args.langs:
        lang_entries = read_entries(lang)
        if len(lang_entries) != len(master):
            problems += 1
            sys.stderr.write("[check] %s: count MISMATCH (lang=%d, master=%d)\n"
                             % (lang, len(lang_entries), len(master)))
        else:
            sys.stderr.write("[check] %s: OK (%d entries, count aligned)\n"
                             % (lang, len(master)))
    return 1 if problems else 0


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def build_parser():
    ap = argparse.ArgumentParser(description="WIKA LangStr translation helper")
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="find new Chinese terms not in master")
    s.add_argument("--master", required=True)
    s.add_argument("--sources", nargs="+", required=True)
    s.add_argument("--out", help="write new terms as a JSON array")
    s.set_defaults(func=cmd_scan)

    s = sub.add_parser("apply-master", help="append new Chinese terms to master cpp")
    s.add_argument("--master", required=True)
    s.add_argument("--terms", required=True, help="JSON array of Chinese terms")
    s.set_defaults(func=cmd_apply_master)

    s = sub.add_parser("init-lang", help="create a new language cpp from master")
    s.add_argument("--master", required=True)
    s.add_argument("--output", required=True)
    s.add_argument("--translations", help="JSON {chinese: translation} for ALL entries")
    s.set_defaults(func=cmd_init_lang)

    s = sub.add_parser("add-lang", help="append new entries to an existing language cpp")
    s.add_argument("--master", required=True)
    s.add_argument("--lang", required=True)
    s.add_argument("--translations", help="JSON {chinese: translation} for NEW entries")
    s.set_defaults(func=cmd_add_lang)

    s = sub.add_parser("check", help="verify language cpp(s) share master's entry count")
    s.add_argument("--master", required=True)
    s.add_argument("--langs", nargs="+", required=True)
    s.set_defaults(func=cmd_check)

    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
