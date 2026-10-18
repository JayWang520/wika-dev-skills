#!/usr/bin/env python3
"""直接构造 WIKA .app 升级包（首选脚本路径，与已验证工具格式同构）。

用法:
  build_app.py --zip <userapp.zip> --date YYYYMMDD -o out.app [--check-md5 ref.app]

说明:
- TLV 字段固定为 SDC190H 惯例: PRODUCT/MODEL/BOARD='*', APP_VER='1.0.0', OEM='XCMG'
- MD5 record 算法（已对 mgmt-tool 产物逆向验证，2026-09-03）:
      MD5 = md5( magic[0x00..0x10] + 全部后续 record 字节[0x50..EOF] )
  即整包流式写入时跳过 32 字节 MD5 hex 值本身（值写入时不回喂摘要）。
  三个工具产包（V1.00/V1.01/SDC190H_V1.01）全部精确命中。
- --check-md5: 可选参考包，自算 MD5 与其头字段比对一致才写出（不再复制旧值）。
"""
import argparse, hashlib, sys

def rec(tag, val):
    return tag.encode().ljust(16, b'\0') + str(len(val)).encode().ljust(16, b'\0') + val

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--zip', required=True)
    ap.add_argument('--date', required=True, help='YYYYMMDD')
    ap.add_argument('-o', '--output', required=True)
    ap.add_argument('--check-md5', help='可选参考 .app，仅校验本脚本 MD5 算法与其一致')
    a = ap.parse_args()

    zipdata = open(a.zip, 'rb').read()
    magic = b'HIRSCHMANNIMAGE\x00'
    body = (rec('MD5', b'0' * 32)      # 占位，值稍后替换并参与计算的位置被跳过
            + rec('PRODUCT', b'*\x00')
            + rec('MODEL', b'*\x00')
            + rec('BOARD', b'*\x00')
            + rec('APP_VER', b'1.0.0\x00')
            + rec('DATE', a.date.encode() + b'\x00')
            + rec('OEM', b'XCMG\x00')
            + rec('USERAPP', zipdata))
    md5hex = hashlib.md5(magic + body[0x40:]).hexdigest().encode()  # body[0:0x40] = MD5 tag+len，之后全部参与
    data = magic + body[:0x20] + md5hex + body[0x40:]

    if a.check_md5:
        ref = open(a.check_md5, 'rb').read()[0x30:0x50]
        if ref != md5hex:
            sys.exit(f'FAIL: computed md5 {md5hex.decode()} != reference {ref.decode()}')

    open(a.output, 'wb').write(data)
    print(f'OK: {a.output} ({len(data)} bytes) md5={md5hex.decode()}')

if __name__ == '__main__':
    main()
