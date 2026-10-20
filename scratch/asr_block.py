    # ---- Auto captions (AsrTools / bk_asr) -----------------------------------
    ASR_TRACK = 1
    ASR_CAPTION_Y = 318
    ASR_CAPTION_SIZE = 28

    def _asr_default_media(self):
        clip = getattr(self, "_selected_clip", None)
        candidates = []
        if clip is not None and clip.clip_type in ("video", "audio") and clip.file_path:
            candidates.append(clip.file_path)
        candidates.append(getattr(self, "video_path", None))
        if self.media_files:
            candidates.append(self.media_files[0])
        for path in candidates:
            if path and os.path.exists(path):
                return path
        return None

    def _auto_captions(self):
        dialog = ctk.CTkToplevel(self.root)
        dialog.title("Auto Captions")
        dialog.geometry("470x600")
        dialog.transient(self.root)
        dialog.grab_set()

        body = ctk.CTkFrame(dialog, fg_color=UI_PANEL, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True)

        head = ctk.CTkFrame(body, fg_color=UI_HEADER, height=44, corner_radius=0)
        head.pack(fill=tk.X)
        head.pack_propagate(False)
        ctk.CTkLabel(head, text="Auto Captions", text_color=UI_TEXT,
                     font=(UI_FONT, 14, "bold")).pack(side=tk.LEFT, padx=14)
        ctk.CTkLabel(head, text="powered by AsrTools", text_color=UI_DIM,
                     font=(UI_FONT, 11)).pack(side=tk.RIGHT, padx=14)

        scroll = ctk.CTkScrollableFrame(body, fg_color="transparent",
                                        scrollbar_button_color=UI_BORDER,
                                        scrollbar_button_hover_color=UI_HOVER)
        scroll.pack(fill=tk.BOTH, expand=True, padx=12, pady=10)

        state = {"media": self._asr_default_media(), "busy": False}

        def field(parent, label):
            frame = ctk.CTkFrame(parent, fg_color=UI_HEADER, height=34, corner_radius=0)
            frame.pack(fill=tk.X, pady=(0, 4))
            frame.pack_propagate(False)
            ctk.CTkLabel(frame, text=label, width=96, anchor="w", text_color=UI_MUTED,
                         font=(UI_FONT, 12)).pack(side=tk.LEFT, padx=(10, 4), fill=tk.Y)
            return frame

        media_row = field(scroll, "Media")
        media_lbl = ctk.CTkLabel(media_row, text="", anchor="w", text_color=UI_TEXT,
                                 font=(UI_FONT, 12))
        media_lbl.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=4)

        def refresh_media_lbl():
            path = state["media"]
            if not path:
                media_lbl.configure(text="No file selected", text_color=UI_DIM)
            elif not os.path.exists(path):
                media_lbl.configure(text="Missing: " + os.path.basename(path), text_color="#FF8A8A")
            else:
                media_lbl.configure(text=os.path.basename(path), text_color=UI_TEXT)

        def choose():
            path = filedialog.askopenfilename(parent=dialog, title="Choose media",
                                              filetypes=[("Media", "*.mp3 *.wav *.aac *.m4a *.flac *.ogg "
                                                          "*.mp4 *.avi *.mov *.mkv *.ts *.webm")])
            if path:
                state["media"] = path
                refresh_media_lbl()

        ctk.CTkButton(media_row, text="Browse", width=68, height=24, corner_radius=6,
                      fg_color=UI_FIELD, hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER,
                      text_color=UI_TEXT, font=(UI_FONT, 11), command=choose).pack(side=tk.RIGHT, padx=8)
        refresh_media_lbl()

        engine_menu = ctk.CTkOptionMenu(field(scroll, "Engine"), values=ASR_ENGINES, width=210, height=28,
                                        corner_radius=6, fg_color=UI_FIELD, button_color=UI_HOVER,
                                        button_hover_color=UI_ACCENT_SOFT, text_color=UI_TEXT,
                                        border_width=1, border_color=UI_BORDER,
                                        dropdown_fg_color=UI_HEADER, dropdown_hover_color=UI_HOVER,
                                        dropdown_text_color=UI_TEXT)
        engine_menu.set("Bcut (Bilibili)")

        lang_menu = ctk.CTkOptionMenu(field(scroll, "Language"), values=ASR_LANGS, width=210, height=28,
                                      corner_radius=6, fg_color=UI_FIELD, button_color=UI_HOVER,
                                      button_hover_color=UI_ACCENT_SOFT, text_color=UI_TEXT,
                                      border_width=1, border_color=UI_BORDER,
                                      dropdown_fg_color=UI_HEADER, dropdown_hover_color=UI_HOVER,
                                      dropdown_text_color=UI_TEXT)
        lang_menu.set("Auto")

        format_menu = ctk.CTkOptionMenu(field(scroll, "Subtitle file"), values=ASR_FORMATS, width=210,
                                        height=28, corner_radius=6, fg_color=UI_FIELD, button_color=UI_HOVER,
                                        button_hover_color=UI_ACCENT_SOFT, text_color=UI_TEXT,
                                        border_width=1, border_color=UI_BORDER,
                                        dropdown_fg_color=UI_HEADER, dropdown_hover_color=UI_HOVER,
                                        dropdown_text_color=UI_TEXT)
        format_menu.set("SRT")

        timeline_var = tk.BooleanVar(value=True)
        ctk.CTkCheckBox(scroll, text="Place captions on the timeline", variable=timeline_var,
                        checkbox_width=18, checkbox_height=18, corner_radius=5, border_width=2,
                        fg_color=UI_ACCENT, hover_color=UI_ACCENT_SOFT, border_color=UI_BORDER,
                        text_color=UI_TEXT, font=(UI_FONT, 12)).pack(anchor="w", pady=(10, 6))

        note = ctk.CTkLabel(scroll, text="", anchor="w", justify=tk.LEFT, wraplength=380,
                            text_color=UI_DIM, font=(UI_FONT, 11))
        note.pack(fill=tk.X, pady=(2, 8))

        def show_note(*_a):
            engine = engine_menu.get()
            if engine == "Faster Whisper (local)":
                note.configure(text="Runs offline on CPU. Language and timing are honoured.")
            elif engine == "JianYing (CapCut)":
                note.configure(text="CapCut cloud engine. Needs internet and a reachable "
                                    "signature relay (asrtools-update.bkfeng.top).")
            else:
                note.configure(text="Cloud engine: the audio track is uploaded for transcription. "
                                    "Language is auto-detected; the audio lane is cached for retries.")

        engine_menu.configure(command=show_note)
        show_note()

        progress = ctk.CTkProgressBar(body, height=6, corner_radius=3, fg_color=UI_BORDER,
                                      progress_color=UI_ACCENT, mode="determinate")
        progress.pack(fill=tk.X, padx=14, pady=(0, 4))
        progress.set(0)

        status = ctk.CTkLabel(body, text="Ready", anchor="w", text_color=UI_MUTED, font=(UI_FONT, 11))
        status.pack(fill=tk.X, padx=14, pady=(0, 8))

        def set_state(pct, text):
            try:
                progress.set(max(0.0, min(1.0, pct / 100.0)))
                status.configure(text=text)
            except tk.TclError:
                pass

        buttons = ctk.CTkFrame(body, fg_color="transparent")
        buttons.pack(fill=tk.X, padx=14, pady=(0, 14))

        def start():
            if state["busy"]:
                return
            media = state["media"]
            if not media or not os.path.exists(media):
                messagebox.showwarning("No media", "Choose a video or audio file first.", parent=dialog)
                return
            engine = engine_menu.get()
            lang = lang_menu.get()
            out_format = format_menu.get()
            to_timeline = bool(timeline_var.get())

            state["busy"] = True
            run_btn.configure(state="disabled", text="Transcribing...")
            set_state(2, "Preparing audio...")

            def report(pct, text):
                # Worker threads must not touch Tk widgets; hop back via after().
                try:
                    dialog.after(0, lambda p=pct, t=str(text): set_state(p, t))
                except tk.TclError:
                    pass

            def work():
                try:
                    segments = self._run_asr(media, engine, lang, report)
                    saved = self._asr_write(segments, media, out_format)
                    report(100, "%d caption lines written" % len(segments))
                    dialog.after(0, lambda: finish(True, segments, saved, to_timeline))
                except BaseException as exc:
                    dialog.after(0, lambda e=exc: finish(False, None, None, to_timeline, e))

            def finish(ok, segments, saved, to_timeline, error=None):
                state["busy"] = False
                try:
                    run_btn.configure(state="normal", text="Transcribe")
                except tk.TclError:
                    return
                if ok:
                    created = self._asr_clips(segments) if to_timeline else []
                    detail = "Captions: %d lines\nSaved: %s" % (len(segments), saved or "-")
                    if created:
                        detail += "\nAdded to the timeline text lane."
                    messagebox.showinfo("Auto Captions", detail, parent=dialog)
                    self.set_status("Auto captions: %d lines from %s" % (len(segments),
                                                                        os.path.basename(media)))
                else:
                    message = str(error) if error is not None else "Unknown error"
                    if error is not None and not message:
                        message = error.__class__.__name__
                    set_state(0, "Failed")
                    messagebox.showerror("Auto Captions failed", message, parent=dialog)

            import threading
            threading.Thread(target=work, daemon=True).start()

        run_btn = ctk.CTkButton(buttons, text="Transcribe", height=38, corner_radius=8,
                                fg_color=UI_ACCENT, hover_color=UI_ACCENT_SOFT, text_color="#06212A",
                                font=(UI_FONT, 13, "bold"), command=start)
        run_btn.pack(side=tk.LEFT, fill=tk.X, expand=True)
        ctk.CTkButton(buttons, text="Close", width=88, height=38, corner_radius=8, fg_color=UI_FIELD,
                      hover_color=UI_HOVER, border_width=1, border_color=UI_BORDER, text_color=UI_TEXT,
                      font=(UI_FONT, 12), command=dialog.destroy).pack(side=tk.RIGHT, padx=(10, 0))

    def _run_asr(self, media_path, engine, lang_name, report):
        """Transcribe one file -> list of {text, start_ms, end_ms} dicts."""
        asr = asr_module()
        language = ASR_LANG_CODES.get(lang_name)
        try:
            audio_path, _tmp = asr_audio_for_upload(media_path)
        except RuntimeError:
            if engine != "Faster Whisper (local)":
                raise
            # faster-whisper decodes containers itself, so ffmpeg is optional here
            audio_path = media_path
        if engine == "Faster Whisper (local)":
            return asr_local_segments(audio_path, language, report)
        cls = asr.engine_class(engine)
        report(12, "Uploading audio to %s..." % engine)
        data = cls(audio_path, use_cache=True).run()
        report(88, "Reading transcript...")
        segments = asr.to_segments(data)
        if not segments:
            raise RuntimeError("%s returned no speech. Try another engine or check the audio track."
                               % engine)
        return segments

    def _asr_write(self, segments, media_path, out_format):
        if not segments:
            raise RuntimeError("No speech was recognised in this file.")
        asr = asr_module()
        data = asr.ASRData([asr.ASRDataSeg(s["text"], s["start_ms"], s["end_ms"]) for s in segments])
        stem = os.path.splitext(media_path)[0]
        out_path = stem + "." + out_format.lower()
        try:
            asr_data_to_file(data, out_path)
        except OSError:
            out_path = os.path.join(OUTPUT_DIR, os.path.basename(stem) + "." + out_format.lower())
            asr_data_to_file(data, out_path)
        return out_path

    def _asr_clips(self, segments):
        """Put each transcript line on the timeline text lane as an editable clip."""
        created = []
        for seg in segments:
            start = max(0.0, seg["start_ms"] / 1000.0)
            duration = max(0.4, (seg["end_ms"] - seg["start_ms"]) / 1000.0)
            clip = TimelineClip("", start, duration, "text", self.ASR_TRACK)
            clip.text_content = seg["text"]
            clip.font = "Arial"
            clip.font_size = self.ASR_CAPTION_SIZE
            clip.text_color = "#FFFFFF"
            clip.bg_color = "#000000"
            clip.x_pos = 320
            clip.y_pos = self.ASR_CAPTION_Y
            self.timeline_clips.append(clip)
            created.append(clip)
        try:
            self.draw_timeline_clips()
        except Exception as exc:
            print("Timeline redraw after captions failed: %s" % exc)
        if created and hasattr(self, "draw_preview_frame"):
            try:
                self.draw_preview_frame(int(created[0].start_time * 30))
            except Exception:
                pass
        self.set_status("%d caption clips on the text lane" % len(created))
        return created

    def _import_subtitles(self):
        path = filedialog.askopenfilename(
            title="Import subtitles",
            filetypes=[("Subtitles", "*.srt *.ass *.ssa *.vtt *.json")])
        if not path:
            return
        try:
            asr = asr_module()
            data = asr.from_subtitle_file(path)
            segments = asr.to_segments(data)
        except Exception as exc:
            messagebox.showerror("Import Subtitles", "Could not read this subtitle file:\n%s" % exc)
            return
        if not segments:
            messagebox.showwarning("Import Subtitles", "No caption lines found in\n" + path)
            return
        self._asr_clips(segments)
        messagebox.showinfo("Import Subtitles",
                            "%d lines from %s\n\nThey are on the timeline text lane, ready to edit."
                            % (len(segments), os.path.basename(path)))

