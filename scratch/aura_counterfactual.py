"""Counterfactual của cả hai probe aura: gay seam thi probe PHAI do.

Khong sua file nguon. Patch tam module ma tung ben goi:
  export  -> core.frame_composer.paint_aura_for_effects
  preview -> core.aura_paint.paint_aura_for_effects (paint() nap tai dung luc chay)
Neu ben nao van xanh thi no khong do dung seam, probe do vo nghia.
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def load(name):
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(HERE, "scratch", name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


import core.aura_paint as aura_paint
import core.frame_composer as frame_composer

noop = lambda *a, **k: None
aura_paint.paint_aura_for_effects = noop
frame_composer.paint_aura_for_effects = noop

probes = ("aura_export_probe", "aura_preview_probe")
still_green = []
for name in probes:
    probe = load(name)
    try:
        probe.main()
        still_green.append(name)
        print("%s VAN XANH khi seam bi gay -> probe do vo nghia" % name)
    except Exception as exc:
        print("%s do: %s" % (name, exc))

sys.exit(1 if still_green else 0)
