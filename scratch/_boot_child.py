import json, sys, time
sys.path.insert(0, 'D:\\Programming\\clinging')
mode = sys.argv[1]
import main
if mode == "no_cover":
    import ui.home_page as hp
    hp.RecentProjectCard._load_project_thumbnail = lambda self: None
elif mode == "no_cards":
    import ui.home_page as hp
    hp.HomePage._load_recent_projects = lambda self: None
elif mode == "baseline":
    pass
else:
    raise SystemExit("che do khong ton tai: " + mode)
t0 = time.perf_counter()
app, controller = main._boot()
boot = time.perf_counter() - t0
out = {"mode": mode,
       "boot_s": round(boot, 4),
       "marks": [{"name": n, "t_s": round(t, 4), "ram_kib": r}
                 for n, t, r in main.BOOT_MARKS],
       "cv2_loaded": "cv2" in sys.modules,
       "ram_kib": main._working_set_kib()}
print("RESULT " + json.dumps(out))
