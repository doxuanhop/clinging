import os
import tkinter as tk
from tkinter import messagebox, filedialog

def cut_video_logic(app, MOVIEPY, video_path, num_segments, save_dir, project_name, progress_callback=None, cancel_callback=None):
    success_count = 0
    base_name = os.path.splitext(os.path.basename(video_path))[0]
    
    try:
        VideoFileClip = MOVIEPY['VideoFileClip']
        
        clip = VideoFileClip(video_path)
        total_duration = clip.duration
        file_size = os.path.getsize(video_path) / (1024 * 1024)
        segment_duration = total_duration / num_segments
        clip.close()
        del clip
        
        for i in range(num_segments):
            if cancel_callback and cancel_callback():
                break
            
            start_time = i * segment_duration
            end_time = min((i + 1) * segment_duration, total_duration)
            
            clip_temp = None
            subclip = None
            
            try:
                clip_temp = VideoFileClip(video_path)
                clip_temp = clip_temp.subclipped(start_time, end_time)
                
                output_name = f"{i+1}.{project_name}_{base_name}.mp4"
                output_path = os.path.join(save_dir, output_name)
                
                clip_temp.write_videofile(output_path, 
                                    codec="libx264", 
                                    audio_codec="aac", 
                                    logger=None, 
                                    preset="ultrafast",
                                    ffmpeg_params=["-threads", "1"])
                
                subclip = clip_temp
                
            except Exception as e:
                print(f"Lỗi đoạn {i+1}: {e}")
                if clip_temp:
                    try:
                        clip_temp.close()
                        del clip_temp
                    except:
                        pass
            
            if subclip:
                try:
                    subclip.close()
                    del subclip
                except:
                    pass
                subclip = None
                
                if os.path.exists(output_path):
                    output_size = os.path.getsize(output_path) / (1024 * 1024)
                    success_count += 1
                    
                    mins_part = int(segment_duration // 60)
                    secs_part = int(segment_duration % 60)
                    
                    if progress_callback:
                        progress_callback(i + 1, num_segments, {
                            'segment': i + 1,
                            'total': num_segments,
                            'start_time': start_time,
                            'end_time': end_time,
                            'duration': segment_duration,
                            'duration_str': f"{mins_part}:{secs_part:02d}",
                            'output_size': output_size,
                            'file_size': file_size,
                            'total_duration': total_duration,
                            'project_name': project_name
                        })
            
            try:
                import gc
                gc.collect()
            except:
                pass
        
        if success_count > 0:
            messagebox.showinfo("Hoàn tất", f"Đã cắt {success_count}/{num_segments} đoạn")
        else:
            messagebox.showerror("Lỗi", "Không thể cắt video")
            
    except Exception as e:
        import traceback
        traceback.print_exc()
        messagebox.showerror("Lỗi", str(e))

def split_video_logic(app, MOVIEPY):
    if not app.current_file:
        messagebox.showwarning("Warning", "No video loaded")
        return
    
    d = ctk.CTkToplevel(app.root)
    d.title("Split Video")
    d.geometry("400x350")
    
    ctk.CTkLabel(d, text="Split Mode", font=("Segoe UI", 14, "bold")).pack(pady=10)
    
    btn_frame = ctk.CTkFrame(d, fg_color="transparent")
    btn_frame.pack(pady=10, padx=20, fill=tk.BOTH, expand=True)
    
    def do_split_at_current():
        try:
            clip = MOVIEPY['VideoFileClip'](app.current_file)
            current_time = app.timeline_slider.get() / 30
            
            save_dir = filedialog.askdirectory(title="Select folder to save parts")
            if not save_dir: return
            
            base_name = os.path.splitext(os.path.basename(app.current_file))[0]
            
            p1 = clip.subclip(0, current_time)
            p2 = clip.subclip(current_time, clip.duration)
            
            p1.write_videofile(os.path.join(save_dir, f"{base_name}_part1.mp4"), codec="libx264", audio_codec="aac", logger=None)
            p2.write_videofile(os.path.join(save_dir, f"{base_name}_part2.mp4"), codec="libx264", audio_codec="aac", logger=None)
            
            p1.close()
            p2.close()
            clip.close()
            messagebox.showinfo("Success", "Split into 2 parts")
            d.destroy()
        except Exception as e:
            messagebox.showerror("Error", str(e))

    ctk.CTkButton(btn_frame, text="Split at Playhead", fg_color="#00B4F0", command=do_split_at_current).pack(pady=10, fill=tk.X)
    ctk.CTkButton(d, text="Close", command=d.destroy).pack(pady=10)

def merge_videos_logic(app, MOVIEPY):
    files = filedialog.askopenfilenames(filetypes=[("Video", "*.mp4 *.avi *.mov *.mkv")])
    if files:
        try:
            clips = [MOVIEPY['VideoFileClip'](f) for f in files]
            app.processed_clip = MOVIEPY['concatenate_videoclips'](clips)
            messagebox.showinfo("Success", f"Merged {len(files)} videos")
        except Exception as e:
            messagebox.showerror("Error", str(e))

def add_audio_logic(app, MOVIEPY):
    import shutil
    import subprocess
    
    if not app.current_file: return
    audio_file = filedialog.askopenfilename(filetypes=[("Audio", "*.mp3 *.wav *.aac *.m4a *.flac *.ogg")])
    if audio_file:
        try:
            import os
            ffmpeg_path = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe") or "ffmpeg"
            
            common_paths = [
                r"C:\ffmpeg\bin\ffmpeg.exe",
                r"C:\Program Files\ffmpeg\bin\ffmpeg.exe",
                os.path.expanduser(r"~\AppData\Local\Programs\ffmpeg\bin\ffmpeg.exe"),
            ]
            for path2 in common_paths:
                if os.path.exists(path2):
                    ffmpeg_path = path2
                    break
            
            if not ffmpeg_path:
                messagebox.showerror("Error", "ffmpeg not found. Please install ffmpeg.")
                return
            
            clip = MOVIEPY['VideoFileClip'](app.current_file)
            
            output_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "video")
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.splitext(os.path.basename(app.current_file))[0]
            out_path = os.path.join(output_dir, f"{base_name}_with_audio.mp4")
            
            cmd = [ffmpeg_path, "-y", "-i", app.current_file, "-i", audio_file, "-c", "v", "copy", "-c:a", "aac", "-map", "0:v:0", "-map", "1:a:0", out_path]
            result = subprocess.run(cmd, capture_output=True)
            
            clip.close()
            
            if result.returncode == 0:
                messagebox.showinfo("Success", f"Audio added to {out_path}")
            else:
                messagebox.showerror("Error", "Failed to add audio")
        except Exception as e:
            messagebox.showerror("Error", str(e))

def extract_audio_logic(app, MOVIEPY):
    if not app.current_file: return
    try:
        clip = MOVIEPY['VideoFileClip'](app.current_file)
        if not clip.audio:
            messagebox.showwarning("Warning", "No audio in video")
            return
        filename = filedialog.asksaveasfilename(defaultextension=".mp3", filetypes=[("MP3", "*.mp3")])
        if filename:
            clip.audio.write_audiofile(filename, logger=None)
            messagebox.showinfo("Success", "Audio saved")
    except Exception as e:
        messagebox.showerror("Error", str(e))
