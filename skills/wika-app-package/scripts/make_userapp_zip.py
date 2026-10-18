#!/usr/bin/env python3
"""制作 WIKA .app 升级包的 USERAPP zip 载荷。

关键点: zip 内文件名必须带前导 '/'（设备端按 /myapp 等绝对路径解压）。
zipfile.write() 会剥掉前导 '/', 所以用 ZipInfo 手工写。

用法: make_userapp_zip.py <载荷目录> <输出.zip>
载荷目录内需含: myapp Database.db can0.eds can0.h can0.var logo.bin app.info
"""
import sys, os, zipfile

FILES = ['/Database.db', '/app.info', '/can0.eds', '/can0.h', '/can0.var', '/logo.bin', '/myapp']

def main(srcdir, outzip):
    files = list(FILES)
    # 部分项目有第二路 CAN 配置（如 LW1200K 的 can1.*），载荷目录里存在就一并打入
    for extra in sorted(os.listdir(srcdir)):
        if extra.startswith('can1.') and ('/' + extra) not in files:
            files.append('/' + extra)
    # 部分项目额外带 update.md5sum（载荷清单校验文件），存在就一并打入
    if os.path.exists(os.path.join(srcdir, 'update.md5sum')):
        files.append('/update.md5sum')
    z = zipfile.ZipFile(outzip, 'w', zipfile.ZIP_DEFLATED)
    for f in files:
        path = os.path.join(srcdir, f.lstrip('/'))
        if not os.path.exists(path):
            sys.exit(f'缺少载荷文件: {path}')
        zi = zipfile.ZipInfo(f, date_time=(2026, 1, 1, 0, 0, 0))
        zi.compress_type = zipfile.ZIP_DEFLATED
        zi.external_attr = (0o755 if f == '/myapp' else 0o644) << 16
        with open(path, 'rb') as fp:
            z.writestr(zi, fp.read())
    z.close()
    print(f'OK: {outzip} ({os.path.getsize(outzip)} bytes, {len(files)} files)')

if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    main(sys.argv[1], sys.argv[2])
