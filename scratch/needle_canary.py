"""Do dem: mau byte cua moi probe phan chung co con trach duoc dòng nao khong.

Mot probe phan chung khong chay duoc la mot probe IM LANG (docs/verification-gates.md
ghi 2 lan tra gia vi chuyen nay). File nay KHONG doi byte nao, chi doc tung
`MUTATIONS` cua probe bang cach import no roi dem so lan mau xuat hien trong file
nguon THAT. Mot vet lech (0 lan, hoac nhieu hon so lan probe doi hoi) la cua bi
han — do đó chạy file nay TRUOC khi quyet dinh mot cong nao "xanh".

```bash
python scratch/needle_canary.py            # moi probe: so vet / so lech
python scratch/needle_canary.py -v         # in nguyen van tung vet lech
```
"""

import importlib.util
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROBES = ["chroma_key_counterfactual", "color_grading_counterfactual",
          "trim_counterfactual", "detach_audio_counterfactual",
          "compress_counterfactual", "text_styling_counterfactual",
          "media_locator_counterfactual", "save_atomic_counterfactual",
          "clipboard_counterfactual", "undo_text_transform_counterfactual",
          "popart_project_counterfactual", "boot_laziness_counterfactual",
          "split_plan_counterfactual", "export_range_counterfactual"]


def entries(mod):
    """ lay (mo ta, duong dan, old, new, so_lan) tu moi kieu MUTATIONS.

    Bon hinh dang dang ton tai trong scratch/:
      (name, path, needle, repl, expect)                     — compress/trim/detach
      (desc, [(path, old, new, count)], expect)              — chroma/colour/media_locator
      (desc, [(path, old, new)], expect)                     — clipboard/popart/save_atomic
      (name, needle, repl, expect) + TARGET cap nhat         — save_atomic
    """
    out = []
    target = getattr(mod, "TARGET", None)
    for item in getattr(mod, "MUTATIONS", []):
        label = str(item[0])
        if len(item) == 5 and isinstance(item[1], str):
            out.append((label, item[1], item[2], item[3], 1))
        elif len(item) == 4 and target and isinstance(item[1], (bytes, str)):
            out.append((label, target, item[1], item[2], 1))
        else:
            for e in item[1]:
                if isinstance(e, (tuple, list)) and len(e) == 4:
                    out.append((label, e[0], e[1], e[2], e[3]))
                elif isinstance(e, (tuple, list)) and len(e) == 3:
                    out.append((label, e[0], e[1], e[2], 1))
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    verbose = "-v" in sys.argv
    missing, leaked, clean = [], [], 0
    for name in PROBES:
        path = os.path.join(ROOT, "scratch", name + ".py")
        if not os.path.exists(path):
            print("%-34s KHONG CO FILE" % name)
            missing.append(name)
            continue
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(mod)
        except SystemExit:
            pass  # co probe trieu host luc doc file
        except Exception as exc:
            print("%-34s KHONG IMPORT DUOC: %s: %s"
                  % (name, type(exc).__name__, str(exc)[:90]))
            missing.append(name)
            continue
        bad, total = [], 0
        for label, f, old, new, count in entries(mod):
            total += 1
            if not os.path.exists(f):
                bad.append((label, os.path.relpath(f, ROOT),
                            "KHONG CO FILE", old))
                continue
            data = open(f, "rb").read()
            needle = old if isinstance(old, bytes) else str(old).encode()
            n = data.count(needle)
            if n != count:
                bad.append((label, os.path.relpath(f, ROOT),
                            "mau tim thay %d lan, probe doi hoi %d" % (n, count),
                            needle))
        status = "%d vet  %s" % (total, "OK" if not bad else "%d LECH" % len(bad))
        if not total:
            status = "KHONG CO BANG VET (probe tham vet inline, canary khong noi duoc gi)"
        print("%-34s %s" % (name, status))
        for label, rel, why, needle in bad:
            print("     [%s] %s -> %s" % (label[:46], rel, why))
            if verbose:
                print("        old=%r" % needle[:120],)
        if total and not bad:
            clean += 1
        elif bad:
            leaked.append(name)
    print("ALL CLEAN: %d/%d probe con nguyen ven mau" % (clean, len(PROBES))
          if not leaked else
          "CAN SUA %d probe: %s" % (len(leaked), ", ".join(leaked)))
    return 1 if (leaked or missing) else 0


if __name__ == "__main__":
    sys.exit(main())
