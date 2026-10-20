import os

path = 'main.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix update_properties_panel to not destroy the toggle button
old_destroy = '        for w in self.props_tabs_frame.winfo_children(): w.destroy()'
new_destroy = '        for w in self.props_tabs_frame.winfo_children():\n            if w != getattr(self, "toggle_right_btn", None): w.destroy()'

content = content.replace(old_destroy, new_destroy)

# Also fix the left panel header if it has a similar issue
# (create_assets_panel doesn't use a destroy loop for its header, it only creates it once)
# But _switch_asset_tab might? No, it clears thumb_grid.

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Fixed update_properties_panel to preserve toggle button")
