"""Bao cho Explorer rang bieu tuong cua mot file da doi — khong xoa cache.

    python scratch\\refresh_shell_icon.py

Vi sao can: shortcut Desktop tro `Clinging.exe,0`, nen Explorer ve theo nhom
bieu tuong trong .exe va GIU ket qua trong iconcache. Sau khi cai ban moi,
duong dan khong doi nen cache cu van duoc phat ra — nguoi dung thay bieu tuong
cu tren mot exe da mang bieu tuong moi, va moi probe doc PE deu bao khop.

VI SAO KHONG XOA iconcache_*.db: do la bo nho dem cua Explorer, xoa thi phai
danh mot `ie4uinit -ClearIconCache` hay kiil Explorer. SHChangeNotify la API
chinh thuc cho dung mot viec nay va khong lay mat cua cai nao khac.

Thu tu nay quan trong hon no trong: SHCNE_UPDATEITEM tren exe va tren .lnk phai
chay TRUOC ASSOCCHANGED. ASSOCCHANGED buoc Explorer doc lai .lnk, neu no chay
truoc thi no phat hanh chinh vet icon cu ma UPDATEITEM chua kip xoa.
"""

import ctypes
import os
import sys

SHCNE_ASSOCCHANGED = 0x08000000
SHCNE_UPDATEITEM = 0x00002000
SHCNE_ATTRIBUTES = 0x00000800
SHCNF_IDLIST = 0x00000000
SHCNF_PATHW = 0x00000005
SHCNF_FLUSH = 0x00001000
SHCNF_FLUSHNOWAIT = 0x00002000

USERPROFILE = os.environ.get("USERPROFILE", "")
TARGETS = [
    os.path.join(USERPROFILE, "Desktop", "Clinging.lnk"),
    os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows",
                 "Start Menu", "Programs", "Clinging", "Clinging.lnk"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "Clinging",
                 "Clinging.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs",
                 "ClingingMSI", "Clinging.exe"),
]


def main():
    notify = ctypes.windll.shell32.SHChangeNotify
    notify.argtypes = [ctypes.c_int, ctypes.c_uint, ctypes.c_wchar_p,
                       ctypes.c_void_p]
    touched = 0
    for path in TARGETS:
        if not os.path.exists(path):
            print("  bo qua (khong co file): %s" % path)
            continue
        # UPDATEITEM chi co tac dung neu Explorer thay file khac lan doc cuoi,
        # nen cham mtime cua .lnk truoc; noi dung cua no khong doi.
        if path.lower().endswith(".lnk"):
            os.utime(path, None)
        for event in (SHCNE_UPDATEITEM, SHCNE_ATTRIBUTES):
            notify(event, SHCNF_PATHW | SHCNF_FLUSHNOWAIT, path, None)
        touched += 1
        print("  da bao Explorer: %s" % path)
    notify(SHCNE_ASSOCCHANGED, SHCNF_IDLIST | SHCNF_FLUSH, None, None)
    print("ASSOCCHANGED da phat cho %d duong dan" % touched)
    return 0 if touched else 1


if __name__ == "__main__":
    sys.exit(main())
