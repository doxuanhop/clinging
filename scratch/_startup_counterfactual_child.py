import sys
sys.path.insert(0, 'D:\\Programming\\clinging')
import main
import ui.home_page as hp
from core.media_extractor import extract_video_thumbnail

# Cach viet cua ban cu: bìa duoc giai ma trong luc card dang duoc dung.
old_init = hp.RecentProjectCard.__init__


def sync_init(self, project_path, parent=None):
    old_init(self, project_path, parent)
    self._load_project_thumbnail()


hp.RecentProjectCard.__init__ = sync_init
# ... va chua co cache bia: goi thang vao bo giai ma.
hp.RecentProjectCard._cover_for_video = lambda self, path, h: extract_video_thumbnail(path, h)

entry = sys.modules["__main__"]
entry._boot = main._boot
entry.BOOT_MARKS = main.BOOT_MARKS
entry._mark = main._mark

import diagnostics
rc = diagnostics.run_startup_report(
    ["child", r"D:\Programming\clinging\scratch\startup_counterfactual.json"])
print("RC %d" % rc)
raise SystemExit(rc)
