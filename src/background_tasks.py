import os
import sys
import time
import threading
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import subprocess
import json

_background_tasks = {}
_task_counter = 0

class BackgroundTask:
    def __init__(self, task_id, name, command, output_dir):
        self.task_id = task_id
        self.name = name
        self.command = command
        self.output_dir = output_dir
        self.process = None
        self.is_paused = False
        self.is_cancelled = False
        self.is_running = False
        self.progress = 0
        self.status = "Chờ..."
        self.log_lines = []
        self._start_time = None
    
    def get_task_info(self):
        return {
            "task_id": self.task_id,
            "name": self.name,
            "status": self.status,
            "progress": self.progress,
            "output_dir": self.output_dir,
            "uptime": int(time.time() - self._start_time) if self._start_time else 0,
            "is_running": self.is_running,
            "is_paused": self.is_paused
        }

def run_cut_in_background(app, video_path, num_segments, output_dir, project_name, segment_duration, total_duration, MOVIEPY):
    global _task_counter
    
    task_id = f"cut_{_task_counter}"
    _task_counter += 1
    
    task = BackgroundTask(
        task_id=task_id,
        name=f"Cắt video: {os.path.basename(video_path)}",
        command="cut_video",
        output_dir=output_dir
    )
    _background_tasks[task_id] = task
    
    if not app.root.winfo_exists():
        return
    
    progress_win = ctk.CTkToplevel(app.root)
    progress_win.title(f"Đang cắt video - {task.name}")
    progress_win.geometry("600x400")
    progress_win.transient(app.root)
    progress_win.grab_set()
    
    header = ctk.CTkFrame(progress_win, fg_color="#1A1A1A", height=50)
    header.pack(fill=tk.X)
    header.pack_propagate(False)
    
    ctk.CTkLabel(header, text=f"⏳ {task.name}", text_color="#00E5FF", font=("Segoe UI", 12, "bold")).pack(side=tk.LEFT, padx=15, pady=10)
    
    status_lbl = ctk.CTkLabel(header, text="Đang khởi tạo...", text_color="#888")
    status_lbl.pack(side=tk.RIGHT, padx=15)
    
    progress_frame = ctk.CTkFrame(progress_win, fg_color="transparent")
    progress_frame.pack(fill=tk.X, padx=20, pady=15)
    
    ctk.CTkLabel(progress_frame, text="Tiến trình:", text_color="#AAAAAA").pack(anchor="w")
    progress_bar = ctk.CTkProgressBar(progress_frame, height=20)
    progress_bar.pack(fill=tk.X, pady=5)
    progress_bar.set(0)
    
    detail_frame = ctk.CTkFrame(progress_frame, fg_color="#2B2B2B", height=60)
    detail_frame.pack(fill=tk.X, pady=5)
    detail_frame.pack_propagate(False)
    detail_lbl = ctk.CTkLabel(detail_frame, text="", text_color="white", anchor="w")
    detail_lbl.pack(side=tk.LEFT, padx=10, fill=tk.X, expand=True)
    
    info_frame = ctk.CTkFrame(progress_win, fg_color="transparent")
    info_frame.pack(fill=tk.X, padx=20, pady=10)
    
    ctk.CTkLabel(info_frame, text=f"Đầu ra: {output_dir}", text_color="#888", font=("Segoe UI", 10)).pack(anchor="w")
    
    btn_frame = ctk.CTkFrame(progress_win, fg_color="#1A1A1A", height=60)
    btn_frame.pack(fill=tk.X, side=tk.BOTTOM)
    btn_frame.pack_propagate(False)
    
    pause_btn = ctk.CTkButton(btn_frame, text="⏸ Tạm dừng", fg_color="#FF9800", text_color="white", width=120, height=36)
    cancel_btn = ctk.CTkButton(btn_frame, text="⏹ Huỷ", fg_color="#F44336", text_color="white", width=100, height=36)
    minimize_btn = ctk.CTkButton(btn_frame, text="📥 Chạy nền", fg_color="#333", text_color="white", width=100, height=36)
    
    minimize_btn.pack(side=tk.LEFT, padx=20)
    pause_btn.pack(side=tk.RIGHT, padx=10)
    cancel_btn.pack(side=tk.RIGHT, padx=10)
    
    task._start_time = time.time()
    task.is_running = True
    
    def update_ui():
        while task.is_running and progress_win.winfo_exists():
            info = task.get_task_info()
            
            status_lbl.configure(text=info["status"])
            progress_bar.set(info["progress"])
            
            elapsed = info["uptime"]
            mins = elapsed // 60
            secs = elapsed % 60
            detail_lbl.configure(text=f"Đoạn {int(info['progress'] * num_segments)}/{num_segments} | ⏱ {mins:02d}:{secs:02d}")
            
            if task.is_paused:
                pause_btn.configure(text="▶ Tiếp tục")
            else:
                pause_btn.configure(text="⏸ Tạm dừng")
            
            progress_win.update()
            time.sleep(0.5)
        
        if progress_win.winfo_exists():
            progress_win.destroy()
    
    threading.Thread(target=update_ui, daemon=True).start()
    
    def do_cut():
        try:
            VideoFileClip = MOVIEPY['VideoFileClip']
            base_name = os.path.splitext(os.path.basename(video_path))[0]
            
            task.status = "Đang cắt..."
            total_processed = 0
            
            for i in range(num_segments):
                while task.is_paused and not task.is_cancelled:
                    time.sleep(0.2)
                
                if task.is_cancelled:
                    task.status = "Đã huỷ"
                    break
                
                start_time = i * segment_duration
                end_time = min((i + 1) * segment_duration, total_duration)
                
                output_name = f"{i+1}.{project_name}_{base_name}.mp4"
                output_path = os.path.join(output_dir, output_name)
                
                clip = VideoFileClip(video_path)
                subclip = clip.subclipped(start_time, end_time)
                
                task.status = f"Đang xuất đoạn {i+1}/{num_segments}..."
                
                subclip.write_videofile(
                    output_path,
                    codec="libx264",
                    audio_codec="aac",
                    logger=None,
                    preset="ultrafast",
                    ffmpeg_params=["-threads", "1"]
                )
                
                clip.close()
                subclip.close()
                
                total_processed += 1
                task.progress = total_processed / num_segments
            
            if task.is_cancelled:
                task.status = "Đã huỷ"
            else:
                task.status = "Hoàn tất"
                task.progress = 1.0
                
                if progress_win.winfo_exists():
                    progress_win.destroy()
                    messagebox.showinfo("Hoàn tất", f"Đã cắt {total_processed}/{num_segments} đoạn video!\n\nLưu tại: {output_dir}")
                    
                    try:
                        os.startfile(output_dir)
                    except:
                        pass
        
        except Exception as e:
            task.status = f"Lỗi: {str(e)}"
            import traceback
            traceback.print_exc()
        finally:
            task.is_running = False
    
    def toggle_pause():
        task.is_paused = not task.is_paused
    
    def cancel_task():
        task.is_cancelled = True
        task.is_running = False
    
    def minimize_to_background():
        if progress_win.winfo_exists():
            progress_win.withdraw()
    
    pause_btn.configure(command=toggle_pause)
    cancel_btn.configure(command=cancel_task)
    minimize_btn.configure(command=minimize_to_background)
    
    threading.Thread(target=do_cut, daemon=True).start()
    
    return task_id

def show_tasks_manager(app):
    if not app.root.winfo_exists():
        return
    
    win = ctk.CTkToplevel(app.root)
    win.title("Quản lý tác vụ nền")
    win.geometry("500x400")
    win.transient(app.root)
    win.grab_set()
    
    ctk.CTkLabel(win, text="📋 Tác vụ đang chạy", text_color="white", font=("Segoe UI", 14, "bold")).pack(pady=15)
    
    scroll = ctk.CTkScrollableFrame(win, width=460, height=280, fg_color="#1A1A1A")
    scroll.pack(fill=tk.BOTH, expand=True, padx=20, pady=10)
    
    def refresh_tasks():
        for w in scroll.winfo_children():
            w.destroy()
        
        active_tasks = [t for t in _background_tasks.values() if t.is_running]
        
        if not active_tasks:
            ctk.CTkLabel(scroll, text="Không có tác vụ nào", text_color="#666").pack(pady=20)
            return
        
        for task in active_tasks:
            info = task.get_task_info()
            task_frame = ctk.CTkFrame(scroll, fg_color="#2B2B2B")
            task_frame.pack(fill=tk.X, pady=5)
            
            name_lbl = ctk.CTkLabel(task_frame, text=info["name"], text_color="white", font=("Segoe UI", 11, "bold"), anchor="w")
            name_lbl.pack(fill=tk.X, padx=10, pady=(10, 5))
            
            status_lbl = ctk.CTkLabel(task_frame, text=f"Trạng thái: {info['status']}", text_color="#00E5FF", anchor="w")
            status_lbl.pack(fill=tk.X, padx=10)
            
            btn_row = ctk.CTkFrame(task_frame, fg_color="transparent")
            btn_row.pack(fill=tk.X, padx=10, pady=5)
            
            if info['is_paused']:
                ctk.CTkButton(btn_row, text="▶ Tiếp tục", fg_color="#FF9800", text_color="white", width=80, height=28, command=lambda t=task: setattr(t, 'is_paused', False)).pack(side=tk.LEFT, padx=5)
            else:
                ctk.CTkButton(btn_row, text="⏸ Tạm dừng", fg_color="#FF9800", text_color="white", width=80, height=28, command=lambda t=task: setattr(t, 'is_paused', True)).pack(side=tk.LEFT, padx=5)
            
            ctk.CTkButton(btn_row, text="⏹ Huỷ", fg_color="#F44336", text_color="white", width=70, height=28, command=lambda t=task: setattr(t, 'is_cancelled', True)).pack(side=tk.LEFT, padx=5)
        
        win.after(1000, refresh_tasks)
    
    refresh_tasks()
    
    ctk.CTkButton(win, text="Đóng", fg_color="#333", text_color="white", width=100, command=win.destroy).pack(pady=15)

def get_active_tasks():
    return [t for t in _background_tasks.values() if t.is_running]