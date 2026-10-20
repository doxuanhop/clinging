"""Counterfactual cho gate 'undo cho chu + hinh hoc clip'.

Chung minh gate do vi DUNG ly do, khong phai xanh vi dau vao rong:
  (a) _push_text ghi thang vao model (khong push lenh) -> gate do RED o buoc go
      chu, vi khong co step undo.
  (b) SetClipTextCommand.merges_with bo guard khac khoa -> buoc bold bi tron vao
      buoc chu -> gate do RED o dong "bold khong thanh mot buoc undo rieng".
Moi phep thu doi BYTE, chay `python main.py --selftest` o subprocess rieng, doc
report JSON, ROI byte ve cu va xac minh gate xanh lai. File duoc phuc hoi byte
trong finally nen repo khong bao giu lan dam.
"""
import json, os, subprocess, sys, tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PP = os.path.join(ROOT, "ui", "properties_panel.py")
CM = os.path.join(ROOT, "core", "commands.py")
REPORT = os.path.join(os.environ.get("TEMP", ROOT), "clinging_selftest.json")

PP_ORIG = open(PP, encoding="utf-8").read()
CM_ORIG = open(CM, encoding="utf-8").read()
PP_BYTES = PP_ORIG.encode("utf-8")
CM_BYTES = CM_ORIG.encode("utf-8")

PUSH = (
    "        main_window.timeline_panel.undo_stack.push(\n"
    "            SetClipTextCommand(main_window.timeline_panel.model,\n"
    "                               self.clip_id, **requested))\n"
    "        self._refresh_canvas()")
DIRECT = (
    "        for _k, _v in requested.items():\n"
    "            setattr(self.clip_model, _k, _v)\n"
    "        self._refresh_canvas()")

MERGE = ("        keys = set(self._requested)\n"
         "        if keys != set(other._requested) or not keys:\n"
         "            return False")
MERGE_RELAXED = ("        keys = set(self._requested)\n"
                 "        if not keys:\n"
                 "            return False")


def run_selftest():
    if os.path.exists(REPORT):
        os.remove(REPORT)
    subprocess.run([sys.executable, "main.py", "--selftest"],
                   cwd=ROOT, capture_output=True, text=True,
                   encoding="utf-8", errors="replace")
    data = json.load(open(REPORT, encoding="utf-8"))
    gate = next(r for r in data["checks"] if r["name"] == UNDO_NAME)
    return data["failed"], gate


def write(path, text):
    open(path, "w", encoding="utf-8", newline="").write(text)


def restore():
    open(PP, "wb").write(PP_BYTES)
    open(CM, "wb").write(CM_BYTES)


UNDO_NAME = None  # set below from source scan


def discover_gate_name():
    import re
    src = open(os.path.join(ROOT, "diagnostics.py"), encoding="utf-8").read()
    m = re.search(r'col\.check\("([^"]*undo[^"]*)"', src)
    return m.group(1)


def main():
    global UNDO_NAME
    UNDO_NAME = discover_gate_name()
    print("gate:", UNDO_NAME)
    results = []
    try:
        # Baseline: duoc khi chua mutation.
        failed, gate = run_selftest()
        assert UNDO_NAME not in failed, "baseline gate da DO: %s" % gate["detail"]
        results.append(("baseline xanh", True))

        # (a) _push_text ghi thang, khong tao lenh undo.
        assert PP_ORIG.count(PUSH) == 1, "needle push khong duy nhat"
        write(PP, PP_ORIG.replace(PUSH, DIRECT))
        failed, gate = run_selftest()
        red_a = (UNDO_NAME in failed) and ("buoc" in gate["detail"] or "undo" in gate["detail"])
        results.append(("(a) push tat -> gate do ly do buoc/go chu: %s" % gate["detail"], red_a))
        restore()

        # (b) merges_with khong con phan biet khoa -> bold tron vao buoc chu.
        assert CM_ORIG.count(MERGE) == 1, "needle merge khong duy nhat"
        write(CM, CM_ORIG.replace(MERGE, MERGE_RELAXED))
        failed, gate = run_selftest()
        red_b = (UNDO_NAME in failed) and ("bold" in gate["detail"])
        results.append(("(b) merge mo -> gate do ly do bold rieng: %s" % gate["detail"], red_b))
        restore()

        # Sau khi hoi: gate phai xanh lai va file nguyen ven.
        assert open(PP, encoding="utf-8").read() == PP_ORIG, "PP khong phuc hoi byte"
        assert open(CM, encoding="utf-8").read() == CM_ORIG, "CM khong phuc hoi byte"
        failed, gate = run_selftest()
        restored_green = UNDO_NAME not in failed
        results.append(("hoi byte -> gate xanh lai", restored_green))
    finally:
        restore()

    print("=" * 60)
    ok = True
    for name, passed in results:
        print(("PASS " if passed else "FAIL ") + name)
        ok = ok and passed
    print("=" * 60)
    print("ALL PASS" if ok else "COUNTERFACTUAL FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
