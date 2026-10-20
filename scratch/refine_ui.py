import os

path = 'main.py'
with open(path, 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
skip_next = False
for i, line in enumerate(lines):
    # Remove duplicate toggle_red_menu button
    if 'toggle_btn = ctk.CTkButton(top_tabs_frame, text="☰", fg_color="transparent", text_color="#FF4444", width=30, command=self.toggle_red_menu)' in line:
        # Check if we already have it in assets_header
        # This is a bit risky but we know where it is
        continue
    new_lines.append(line)

content = ''.join(new_lines)

# Add icon loading logic to create_assets_panel
icon_logic = '''        # Load Icons for Tabs
        icon_path = os.path.join(os.path.dirname(__file__), "icons")
        self.tab_icons = {}
        icon_map = {
            "Phương tiện": "folder.png",
            "Âm thanh": "audio.png",
            "Văn bản": "text.png",
            "Chuyển tiếp": "transitions.png",
            "Hiệu ứng": "effects.png",
            "Bộ lọc": "filters.png",
            "Nhãn dán": "stickers.png"
        }
        
        for name, img_file in icon_map.items():
            full_path = os.path.join(icon_path, img_file)
            if os.path.exists(full_path):
                try:
                    img = Image.open(full_path)
                    self.tab_icons[name] = ctk.CTkImage(img, size=(20, 20))
                except: pass

        self._active_asset_tab = "Phương tiện"
'''

content = content.replace('        self._active_asset_tab = "Media"', icon_logic)

# Update tab creation loop to use icons
old_tab_loop = '''        for name, active in asset_tabs:
            color = "#00E5FF" if active else "#AAAAAA"
            btn = ctk.CTkButton(top_tabs_frame, text=name, fg_color="transparent", text_color=color,
                        hover_color="#333", width=40, font=("Segoe UI", 11), command=make_tab_cmd(name)).pack(side=tk.LEFT, expand=True)'''

new_tab_loop = '''        for name, active in asset_tabs:
            color = "#00E5FF" if active else "#AAAAAA"
            icon = self.tab_icons.get(name)
            btn = ctk.CTkButton(top_tabs_frame, text=name, image=icon, compound="top", fg_color="transparent", text_color=color,
                        hover_color="#333", width=40, font=("Segoe UI", 10), command=make_tab_cmd(name))
            btn.pack(side=tk.LEFT, expand=True)'''

content = content.replace(old_tab_loop, new_tab_loop)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Refined main.py with icons and cleaned up duplicate buttons")
