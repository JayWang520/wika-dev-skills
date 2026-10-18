---
name: esafenet-decrypt
description: Identify and decrypt Esafenet (亿赛通/e-Safenet/CDG) transparent file encryption containers. Use when a file starts with magic e0a891e7d8f205ac or contains the ASCII string Esafenet, when the user mentions 亿赛通, Esafenet, e-safenet, CDG 加密, 透明加密解密, or asks to recover a 512-byte XOR pad from a known plaintext/ciphertext pair and decrypt matching files (pdf/docx/xlsx/any). Not for PDF open passwords, Office passwords, ZIP passwords, or generic malware unpacking.
---

# Esafenet Decrypt

Whole-file container used by 亿赛通 transparent encryption. Layout is **4096-byte header + XOR body**; body keystream is a **512-byte repeating pad**. Same pad often applies to every file under the same key/policy.

For field-level format details, read [references/format.md](references/format.md).

## Important

- Only decrypt files the user owns or is authorized to recover. Do not use this against third-party protected content without authorization.
- Never invent a pad. Always recover it from a known plaintext pair (or use a previously recovered pad file the user supplies).
- Always run `identify` first when the format is unknown.

## Instructions

Run scripts with `"$MIMO_PYTHON"` when set, else `python3`.

### Step 1 — Identify

```bash
"$MIMO_PYTHON" -X utf8 scripts/esafenet.py identify /path/to/file
```

Expected for Esafenet:

```json
{
  "is_esafenet": true,
  "magic": "e0a891e7d8f205ac",
  "product": "Esafenet",
  "header_size": 4096,
  "orig_size": <n>,
  "body_size": <n>,
  "size_ok": true
}
```

If `is_esafenet` is false, stop and report the sniff hint (`zip` / `pdf` / unknown). Do not force-decrypt.

### Step 2 — Recover pad (known plaintext pair)

Need one plaintext file and its matching Esafenet-encrypted file (same content).

```bash
"$MIMO_PYTHON" -X utf8 scripts/esafenet.py recover-pad /path/plain.ext /path/plain.ext.encrypted -o /path/pad.bin
```

Pass only when the JSON reports `period_ok: true` and `roundtrip_ok: true`. Save the pad file; it may decrypt sibling files under the same key.

If `period_ok` is false, the sample is not this 512-byte-cycle variant — stop and inspect with [references/format.md](references/format.md). Do not guess.

### Step 3 — Decrypt

Single file:

```bash
"$MIMO_PYTHON" -X utf8 scripts/esafenet.py decrypt /path/pad.bin /path/file.encrypted -o /path/file.decrypted.ext
```

Batch:

```bash
"$MIMO_PYTHON" -X utf8 scripts/esafenet.py decrypt /path/pad.bin /path/dir/*.encrypted --out-dir /path/out
```

Check the JSON `type` (`pdf` / `zip` / `ole`) and `zip_ok` when applicable. Present the output file(s) to the user.

### Step 4 — Cross-file pad reuse check

If the user brings more encrypted files from the same batch, try the existing pad first (Step 3). Success (`type` is a real document magic) confirms same-key reuse. If output is high-entropy garbage or `orig_size` mismatches, recover a new pad from another known pair.

## Examples

1. User: 「这个文件是不是亿赛通加密的？」→ `identify`, report header fields.
2. User: 「有明文和密文，帮我解密同批其它文件」→ `recover-pad` then `decrypt` on the rest.
3. User: 「批量解密这几个 docx」→ `identify` each, `decrypt` with the known pad, `--out-dir`, then `present_files` the results.

## Troubleshooting

| Symptom | Cause | Fix |
|---------|-------|-----|
| `not Esafenet magic` | Not this container | Report as unknown; do not strip 4096 blindly |
| `plain size != encrypted body` | Pair does not match | Use the true plaintext of that ciphertext |
| `period_ok: false` | Keystream not 512-periodic | Variant/different cipher; stop |
| Decrypt output not PDF/ZIP | Wrong pad or wrong pair | Re-recover pad from a matching pair of this batch |
| `zip_ok: false` | Truncated or wrong pad | Verify sizes; try another pair |
| Need authorized open on locked PC | Policy/DRM | Prefer 亿赛通 client or admin 「解密/外发」 |

## Scripts

- [`scripts/esafenet.py`](scripts/esafenet.py) — `identify` / `recover-pad` / `decrypt`
