import os

path = 'main.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add state variables to __init__
if 'self.assets_collapsed = False' not in content:
    content = content.replace(
        'self.selected_media_indices = []',
        'self.selected_media_indices = []\n        self.assets_collapsed = False\n        self.props_collapsed = False'
    )

# 2. Localize Player to Trình phát
content = content.replace(
    'ctk.CTkLabel(header, text="Player", text_color="white", font=("Segoe UI", 12)).pack(side=tk.LEFT)',
    'ctk.CTkLabel(header, text="Trình phát", text_color="white", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT)'
)

# 3. Modify create_assets_panel header
old_assets_header = '''        # Top Asset Tabs
        top_tabs_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        top_tabs_frame.pack(fill=tk.X, padx=5, pady=10)'''

new_assets_header = '''        # Assets Panel Header
        assets_header = ctk.CTkFrame(left_panel, fg_color="transparent")
        assets_header.pack(fill=tk.X, padx=5, pady=5)
        
        self.toggle_left_btn = ctk.CTkButton(assets_header, text="»", fg_color="transparent", 
                                            text_color="#AAAAAA", hover_color="#333333", 
                                            width=30, height=30, font=("Segoe UI", 14, "bold"),
                                            command=self.toggle_assets_panel)
        self.toggle_left_btn.pack(side=tk.RIGHT, padx=5)
        
        toggle_btn = ctk.CTkButton(assets_header, text="☰", fg_color="transparent", text_color="#FF4444", width=30, command=self.toggle_red_menu)
        toggle_btn.pack(side=tk.LEFT, padx=2)
        
        top_tabs_frame = ctk.CTkFrame(left_panel, fg_color="transparent")
        top_tabs_frame.pack(fill=tk.X, padx=5, pady=(0, 10))'''

if old_assets_header in content:
    content = content.replace(old_assets_header, new_assets_header)

# 4. Localize asset tabs
content = content.replace(
    'asset_tabs = [("Media", True), ("Audio", False), ("Text", False), ("Transitions", False), \n                      ("Effects", False), ("Elements", False), ("Stickers", False)]',
    'asset_tabs = [("Phương tiện", True), ("Âm thanh", False), ("Văn bản", False), ("Chuyển tiếp", False), \n                      ("Hiệu ứng", False), ("Bộ lọc", False), ("Nhãn dán", False)]'
)

# 5. Modify properties panel header
old_props_header = '''        self.props_tabs_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent", height=40)
        self.props_tabs_frame.pack(fill=tk.X, padx=5, pady=5)'''

new_props_header = '''        self.props_tabs_frame = ctk.CTkFrame(self.right_panel, fg_color="transparent", height=40)
        self.props_tabs_frame.pack(fill=tk.X, padx=5, pady=5)
        
        self.toggle_right_btn = ctk.CTkButton(self.props_tabs_frame, text="«", fg_color="transparent", 
                                             text_color="#AAAAAA", hover_color="#333333", 
                                             width=30, height=30, font=("Segoe UI", 14, "bold"),
                                             command=self.toggle_properties_panel)
        self.toggle_right_btn.pack(side=tk.RIGHT, padx=5)'''

if old_props_header in content:
    content = content.replace(old_props_header, new_props_header)

# 6. Add toggle methods
if 'def toggle_assets_panel(self):' not in content:
    methods = '''    def toggle_assets_panel(self):
        """Ẩn/hiện panel bên trái"""
        if self.assets_collapsed:
            self.middle_paned.add(self.assets_container, before=self.preview_container)
            self.assets_collapsed = False
            if hasattr(self, 'expand_left_btn'): self.expand_left_btn.place_forget()
        else:
            self.middle_paned.forget(self.assets_container)
            self.assets_collapsed = True
            self.show_expand_left_button()

    def show_expand_left_button(self):
        if not hasattr(self, 'expand_left_btn'):
            self.expand_left_btn = ctk.CTkButton(self.preview_container, text="»", width=30, height=30, 
                                                fg_color="#1E1E1E", text_color="#00E5FF", hover_color="#333333",
                                                corner_radius=4, command=self.toggle_assets_panel)
        self.expand_left_btn.place(x=5, y=5)

    def toggle_properties_panel(self):
        """Ẩn/hiện panel bên phải"""
        if self.props_collapsed:
            self.middle_paned.add(self.properties_container)
            self.props_collapsed = False
            if hasattr(self, 'expand_right_btn'): self.expand_right_btn.place_forget()
        else:
            self.middle_paned.forget(self.properties_container)
            self.props_collapsed = True
            self.show_expand_right_button()

    def show_expand_right_button(self):
        if not hasattr(self, 'expand_right_btn'):
            self.expand_right_btn = ctk.CTkButton(self.preview_container, text="«", width=30, height=30, 
                                                 fg_color="#1E1E1E", text_color="#00E5FF", hover_color="#333333",
                                                 corner_radius=4, command=self.toggle_properties_panel)
        self.root.update_idletasks()
        self.expand_right_btn.place(relx=1.0, x=-35, y=5)

    def toggle_red_menu(self):'''
    content = content.replace('    def toggle_red_menu(self):', methods)

# 7. Final cleanup of the duplicate toggle_red_menu button call in top_tabs_frame
# The script already handled this in step 3 by replacing the whole block

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

print("Successfully updated main.py")
