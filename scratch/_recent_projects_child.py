
import os, sys, time
sys.path.insert(0, r"D:\Programming\clinging")

mode = sys.argv[1]
import main
if mode == "old":
    # Dung lai hanh vi CU: duong doc van ghi file. Khong phai mot cai cach khac
    # de "kiem tra ham save" — no phai chay dung cay widget cua app that.
    import ui.home_page as hp
    real = hp.HomePage._load_recent_projects
    def patched(self):
        real(self)
        recent = hp.load_recent_projects()
        hp.save_recent_projects(
            [p for p in recent if os.path.exists(p)][:10])
    hp.HomePage._load_recent_projects = patched

app, controller = main._boot()
deadline = time.time() + 12.0
while time.time() < deadline and not controller.isVisible():
    app.processEvents()
    time.sleep(0.02)
visible = bool(controller.isVisible())
for _ in range(20):
    app.processEvents()
    time.sleep(0.02)
cards = 0
grid = getattr(controller.home_page, "recent_grid", None)
for i in range(grid.count() if grid else 0):
    item = grid.itemAt(i)
    w = item.widget() if item else None
    if type(w).__name__ == "RecentProjectCard":
        cards += 1
controller.close()
app.quit()
print("BOOTED visible=%s cards=%d" % (visible, cards))
