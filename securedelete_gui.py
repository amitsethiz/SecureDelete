#!/usr/bin/env python3
"""SecureDelete — Professional Secure File Shredder GUI"""
import os, time, shutil, sys, threading, ctypes, re
import customtkinter as ctk
from tkinter import filedialog, messagebox

# Backend — import shared functions from the CLI module (no duplication)
from securedelete import (
    CHUNK_SIZE, TEMP_DIR_NAME,
    get_free_space, format_bytes, format_time,
    make_fill_data, random_name,
    shred_file, shred_directory,
    wipe_free_space,
    get_browser_data_summary,
)


# ===========================================================================
# 2. THREAD-SAFE CONSOLE REDIRECTOR
# ===========================================================================
class TextRedirector:
    def __init__(self, text_widget, app):
        self.text_widget = text_widget
        self.app = app

    def write(self, str_data):
        if not str_data or str_data == "\r": return
        self.app.after(0, self._append_text, str_data)

    def _append_text(self, str_data):
        self.text_widget.configure(state="normal")
        self.text_widget.insert("end", str_data)
        self.text_widget.see("end")
        self.text_widget.configure(state="disabled")

    def flush(self): pass


# ===========================================================================
# 3. DESIGN PALETTE
# ===========================================================================
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

BG      = "#0d1117"   # window background
SURFACE = "#161b22"   # header / tab bar background
CARD    = "#1c2333"   # card background
BORDER  = "#30363d"   # card borders / separators
INPUT   = "#21262d"   # text inputs / list boxes
RED     = "#e53935"   # danger / destructive actions
RED_H   = "#c62828"   # danger hover
GREEN   = "#2e7d32"   # safe / recover actions
GREEN_H = "#1b5e20"   # safe hover
BLUE    = "#1565c0"   # info / neutral actions
BLUE_H  = "#0d47a1"   # info hover
TEXT    = "#e6edf3"   # primary text
MUTED   = "#7d8590"   # secondary / hint text
SUCCESS = "#3fb950"   # success highlight


# ===========================================================================
# 4. MAIN APPLICATION
# ===========================================================================
class SecureDeleteApp(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("SecureDelete")
        self.geometry("980x740")
        self.minsize(860, 660)
        self.configure(fg_color=BG)

        self.targets              = []
        self.recover_items        = []
        self.recover_checkboxes   = []

        # Build layout: header → console (bottom, reserve space first) → tabs (fill middle)
        self._build_header()
        self._build_console()   # pack bottom BEFORE tabs so tabs fill the gap
        self._build_tabs()

        sys.stdout = TextRedirector(self.console_text, self)
        print("🛡  SecureDelete ready.  Running as Administrator.\n")

    # ───────────────────────────────────────────────────────────────────────
    # HEADER
    # ───────────────────────────────────────────────────────────────────────
    def _build_header(self):
        hdr = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=58)
        hdr.pack(fill="x", side="top")
        hdr.pack_propagate(False)

        # Logo
        ctk.CTkLabel(
            hdr, text="🛡  SecureDelete",
            font=ctk.CTkFont("Segoe UI", 21, "bold"), text_color=TEXT
        ).pack(side="left", padx=20)

        # Admin badge
        ctk.CTkLabel(
            hdr, text=" ⚡ ADMIN ",
            fg_color="#b71c1c", corner_radius=5,
            font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color="white"
        ).pack(side="right", padx=20)

        ctk.CTkLabel(
            hdr, text="Secure file shredder & privacy cleaner  •  v1.0",
            font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED
        ).pack(side="right", padx=4)

    # ───────────────────────────────────────────────────────────────────────
    # CONSOLE  (packed BEFORE tabs so it stays at the bottom)
    # ───────────────────────────────────────────────────────────────────────
    def _build_console(self):
        # Thin header bar for the console
        bar = ctk.CTkFrame(self, fg_color=SURFACE, corner_radius=0, height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        ctk.CTkLabel(
            bar, text="▸  Console Output",
            font=ctk.CTkFont("Segoe UI", 11, "bold"), text_color=MUTED
        ).pack(side="left", padx=12)

        ctk.CTkButton(
            bar, text="Clear", width=48, height=20,
            fg_color="transparent", hover_color=BORDER,
            text_color=MUTED, font=ctk.CTkFont("Segoe UI", 10),
            command=self._clear_console
        ).pack(side="right", padx=12)

        # Console textbox
        pane = ctk.CTkFrame(self, fg_color="#080c12", corner_radius=0)
        pane.pack(fill="x", side="bottom")

        self.console_text = ctk.CTkTextbox(
            pane, height=148, fg_color="#080c12",
            text_color="#4ade80", font=("Consolas", 11),
            corner_radius=0, border_width=0
        )
        self.console_text.pack(fill="both", padx=14, pady=(6, 8))
        self.console_text.configure(state="disabled")

    def _clear_console(self):
        self.console_text.configure(state="normal")
        self.console_text.delete("1.0", "end")
        self.console_text.configure(state="disabled")

    # ───────────────────────────────────────────────────────────────────────
    # TABS
    # ───────────────────────────────────────────────────────────────────────
    def _build_tabs(self):
        self.tabview = ctk.CTkTabview(
            self, fg_color=SURFACE,
            segmented_button_fg_color=CARD,
            segmented_button_selected_color=RED,
            segmented_button_selected_hover_color=RED_H,
            segmented_button_unselected_color=CARD,
            segmented_button_unselected_hover_color=BORDER,
        )
        self.tabview.pack(fill="both", expand=True, padx=12, pady=(6, 0))
        self.tabview._segmented_button.configure(
            font=ctk.CTkFont("Segoe UI", 13, "bold")
        )

        self.tab_shred   = self.tabview.add("  🔥  Shred  ")
        self.tab_wipe    = self.tabview.add("  🧹  Wipe  ")
        self.tab_clean   = self.tabview.add("  🔒  Privacy  ")
        self.tab_recover = self.tabview.add("  ♻️  Recover  ")

        self.setup_shred_tab()
        self.setup_wipe_tab()
        self.setup_clean_tab()
        self.setup_recover_tab()

    # ───────────────────────────────────────────────────────────────────────
    # HELPERS
    # ───────────────────────────────────────────────────────────────────────
    def _section_label(self, parent, text):
        ctk.CTkLabel(
            parent, text=text,
            font=ctk.CTkFont("Segoe UI", 10, "bold"), text_color=MUTED
        ).pack(anchor="w", padx=2, pady=(10, 2))

    def _card(self, parent, fill="x", expand=False, pady=(0, 6)):
        f = ctk.CTkFrame(
            parent, fg_color=CARD,
            border_color=BORDER, border_width=1, corner_radius=8
        )
        f.pack(fill=fill, expand=expand, pady=pady)
        return f

    def _segmented_passes(self, parent, var_name):
        seg = ctk.CTkSegmentedButton(
            parent, values=["1", "3", "7"], width=130,
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            selected_color=RED, selected_hover_color=RED_H,
            unselected_color=BORDER, unselected_hover_color="#484f58",
            text_color=TEXT,
        )
        seg.set("3")
        setattr(self, var_name, seg)
        return seg

    def _action_btn(self, parent, text, command, color=RED, hover=RED_H, height=48):
        return ctk.CTkButton(
            parent, text=text, height=height,
            fg_color=color, hover_color=hover,
            font=ctk.CTkFont("Segoe UI", 15, "bold"),
            corner_radius=8, command=command
        )

    def _secondary_btn(self, parent, text, command, width=None, height=32):
        kw = dict(width=width) if width else {}
        return ctk.CTkButton(
            parent, text=text, height=height, **kw,
            fg_color=BORDER, hover_color="#484f58",
            font=ctk.CTkFont("Segoe UI", 11), text_color=TEXT,
            corner_radius=6, command=command
        )

    # ───────────────────────────────────────────────────────────────────────
    # SHRED TAB
    # ───────────────────────────────────────────────────────────────────────
    def setup_shred_tab(self):
        # ── File zone ──
        self._section_label(self.tab_shred, "FILES & FOLDERS TO SHRED")
        zone = self._card(self.tab_shred, fill="x")
        zone_inner = ctk.CTkFrame(zone, fg_color="transparent")
        zone_inner.pack(fill="both", padx=14, pady=10)

        top = ctk.CTkFrame(zone_inner, fg_color="transparent")
        top.pack(fill="x")
        self.shred_count_lbl = ctk.CTkLabel(
            top, text="No items selected",
            font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED
        )
        self.shred_count_lbl.pack(side="left")
        self._secondary_btn(top, "✕  Clear", self.clear_targets, width=72, height=26).pack(side="right")

        self.target_listbox = ctk.CTkTextbox(
            zone_inner, height=110,
            fg_color=INPUT, text_color="#94a3b8",
            font=("Consolas", 11), corner_radius=6
        )
        self.target_listbox.pack(fill="x", pady=(6, 0))
        self.target_listbox.configure(state="disabled")

        btn_row = ctk.CTkFrame(zone_inner, fg_color="transparent")
        btn_row.pack(fill="x", pady=(8, 0))
        ctk.CTkButton(btn_row, text="📄  Add Files", height=32,
                      fg_color=BLUE, hover_color=BLUE_H,
                      font=ctk.CTkFont("Segoe UI", 12), corner_radius=6,
                      command=self.add_files).pack(side="left", padx=(0, 6))
        ctk.CTkButton(btn_row, text="📁  Add Folder", height=32,
                      fg_color=BLUE, hover_color=BLUE_H,
                      font=ctk.CTkFont("Segoe UI", 12), corner_radius=6,
                      command=self.add_folder).pack(side="left")

        # ── Passes ──
        self._section_label(self.tab_shred, "OVERWRITE PASSES")
        pc = self._card(self.tab_shred)
        prow = ctk.CTkFrame(pc, fg_color="transparent")
        prow.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(prow,
                     text="1 = fast    |    3 = recommended    |    7 = DoD 5220.22-M",
                     font=ctk.CTkFont("Segoe UI", 11), text_color=MUTED
                     ).pack(side="left")
        self._segmented_passes(prow, "shred_passes").pack(side="right")

        # ── Action ──
        self.btn_shred_action = self._action_btn(
            self.tab_shred, "🔥  SHRED SELECTED FILES", self.run_shred
        )
        self.btn_shred_action.pack(fill="x", pady=(14, 2))
        ctk.CTkLabel(
            self.tab_shred,
            text="⚠  Files are permanently overwritten and cannot be recovered",
            font=ctk.CTkFont("Segoe UI", 11), text_color="#6b7280"
        ).pack()

    # ───────────────────────────────────────────────────────────────────────
    # WIPE TAB
    # ───────────────────────────────────────────────────────────────────────
    def setup_wipe_tab(self):
        # ── Drive selection ──
        self._section_label(self.tab_wipe, "TARGET DRIVE")
        dc = self._card(self.tab_wipe)
        drow = ctk.CTkFrame(dc, fg_color="transparent")
        drow.pack(fill="x", padx=14, pady=12)

        ctk.CTkLabel(drow, text="Drive:", font=ctk.CTkFont("Segoe UI", 13), text_color=TEXT).pack(side="left")
        self.wipe_drive = ctk.CTkOptionMenu(
            drow, values=["Loading..."], width=130,
            fg_color=INPUT, button_color=BORDER, text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 13)
        )
        self.wipe_drive.pack(side="left", padx=8)
        self._secondary_btn(drow, "🔄", self.refresh_wipe_drives, width=36).pack(side="left")

        self.wipe_free_lbl = ctk.CTkLabel(
            drow, text="", font=ctk.CTkFont("Segoe UI", 12), text_color=MUTED
        )
        self.wipe_free_lbl.pack(side="left", padx=14)

        # ── Passes ──
        self._section_label(self.tab_wipe, "OVERWRITE PASSES")
        pc = self._card(self.tab_wipe)
        prow = ctk.CTkFrame(pc, fg_color="transparent")
        prow.pack(fill="x", padx=14, pady=10)
        ctk.CTkLabel(prow, text="More passes = more secure, but slower",
                     font=ctk.CTkFont("Segoe UI", 11), text_color=MUTED).pack(side="left")
        self._segmented_passes(prow, "wipe_passes").pack(side="right")

        # ── Progress ──
        self._section_label(self.tab_wipe, "PROGRESS")
        pgc = self._card(self.tab_wipe)
        pg_inner = ctk.CTkFrame(pgc, fg_color="transparent")
        pg_inner.pack(fill="x", padx=14, pady=12)

        self.wipe_progress = ctk.CTkProgressBar(
            pg_inner, height=14, corner_radius=6,
            progress_color=RED, fg_color=BORDER
        )
        self.wipe_progress.pack(fill="x")
        self.wipe_progress.set(0)

        self.wipe_status_lbl = ctk.CTkLabel(
            pg_inner, text="Ready to wipe",
            font=ctk.CTkFont("Consolas", 11), text_color=MUTED
        )
        self.wipe_status_lbl.pack(anchor="w", pady=(6, 0))

        # ── Action buttons ──
        brow = ctk.CTkFrame(self.tab_wipe, fg_color="transparent")
        brow.pack(fill="x", pady=(12, 2))

        self.btn_wipe_action = self._action_btn(brow, "🧹  WIPE FREE SPACE", self.run_wipe)
        self.btn_wipe_action.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.btn_wipe_stop = ctk.CTkButton(
            brow, text="⏹  Stop", height=48, width=110,
            fg_color=BORDER, hover_color="#484f58",
            font=ctk.CTkFont("Segoe UI", 13, "bold"),
            corner_radius=8, command=self.stop_wipe, state="disabled"
        )
        self.btn_wipe_stop.pack(side="left")

        ctk.CTkLabel(
            self.tab_wipe,
            text="⚠  Free space is filled with random data to make deleted files unrecoverable",
            font=ctk.CTkFont("Segoe UI", 11), text_color="#6b7280"
        ).pack()

        self.refresh_wipe_drives()

    def setup_clean_tab(self):
        # ── Bottom row: Passes + Action  (packed FIRST so cols can fill remaining space) ──
        bottom = ctk.CTkFrame(self.tab_clean, fg_color="transparent")
        bottom.pack(fill="x", side="bottom", pady=(8, 2))

        # ── Progress indicator ──
        prog_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        prog_frame.pack(fill="x", pady=(0, 4))

        self.clean_progress = ctk.CTkProgressBar(
            prog_frame, height=12, corner_radius=6,
            progress_color=RED, fg_color=BORDER
        )
        self.clean_progress.pack(fill="x")
        self.clean_progress.set(0)

        self.clean_status_lbl = ctk.CTkLabel(
            prog_frame, text="Ready to clean",
            font=ctk.CTkFont("Consolas", 11), text_color=MUTED
        )
        self.clean_status_lbl.pack(anchor="w", pady=(4, 0))

        pc = ctk.CTkFrame(bottom, fg_color=CARD, border_color=BORDER,
                          border_width=1, corner_radius=8)
        pc.pack(fill="x", pady=(6, 6))
        prow = ctk.CTkFrame(pc, fg_color="transparent")
        prow.pack(fill="x", padx=14, pady=8)
        ctk.CTkLabel(prow, text="Overwrite Passes:",
                     font=ctk.CTkFont("Segoe UI", 13), text_color=TEXT).pack(side="left")
        self._segmented_passes(prow, "clean_passes").pack(side="right")

        self.btn_clean_action = self._action_btn(
            bottom, "🔒  CLEAN PRIVACY TRACES", self.run_clean
        )
        self.btn_clean_action.pack(fill="x")

        # ── Scrollable two-column layout (fills remaining space above the button) ──
        cols = ctk.CTkFrame(self.tab_clean, fg_color="transparent")
        cols.pack(fill="both", expand=True, pady=(4, 0))
        cols.columnconfigure(0, weight=1)
        cols.columnconfigure(1, weight=1)

        # ═══════════════════════════════════════════════
        # LEFT COLUMN — System Traces
        # ═══════════════════════════════════════════════
        sys_scroll = ctk.CTkScrollableFrame(
            cols, fg_color=CARD, border_color=BORDER,
            border_width=1, corner_radius=8,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color="#484f58"
        )
        sys_scroll.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=2)

        ctk.CTkLabel(sys_scroll, text="🖥  SYSTEM TRACES",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=MUTED
                     ).pack(anchor="w", padx=14, pady=(10, 4))
        ctk.CTkFrame(sys_scroll, fg_color=BORDER, height=1).pack(fill="x", padx=10, pady=(0, 6))

        self.sw_temp       = self._switch_row(sys_scroll, "Temp & Prefetch Files",
                                              "Windows Temp, user Temp, Prefetch cache", on=True)
        self.sw_recent     = self._switch_row(sys_scroll, "Recent Files & Jump Lists",
                                              "Windows Recent, AutoDest, CustomDest", on=True)
        self.sw_explorer   = self._switch_row(sys_scroll, "Explorer Thumbnail Cache",
                                              "thumbcache_*.db, iconcache_*.db", on=True)
        self.sw_inet       = self._switch_row(sys_scroll, "IE / Edge Legacy Cache",
                                              "INetCache, INetCookies, WebCache DB", on=True)
        self.sw_crash      = self._switch_row(sys_scroll, "Crash Dumps & WER Reports",
                                              "CrashDumps, WER ReportArchive/Queue", on=False)
        self.sw_dns        = self._switch_row(sys_scroll, "Flush DNS Cache",
                                              "ipconfig /flushdns", on=False)
        self.sw_logs       = self._switch_row(sys_scroll, "Windows Event Logs",
                                              "Requires admin  •  clears 1000+ logs", on=False)
        ctk.CTkFrame(sys_scroll, fg_color="transparent", height=6).pack()

        # ═══════════════════════════════════════════════
        # RIGHT COLUMN — Browser Data
        # ═══════════════════════════════════════════════
        br_scroll = ctk.CTkScrollableFrame(
            cols, fg_color=CARD, border_color=BORDER,
            border_width=1, corner_radius=8,
            scrollbar_button_color=BORDER, scrollbar_button_hover_color="#484f58"
        )
        br_scroll.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=2)

        ctk.CTkLabel(br_scroll, text="🌐  BROWSER DATA",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=MUTED
                     ).pack(anchor="w", padx=14, pady=(10, 4))
        ctk.CTkFrame(br_scroll, fg_color=BORDER, height=1).pack(fill="x", padx=10, pady=(0, 4))
        ctk.CTkLabel(
            br_scroll,
            text="History  •  Cache  •  Cookies  •  Sessions  •  Storage  •  Autofill\n"
                 "Passwords, bookmarks & extensions are always preserved.",
            font=ctk.CTkFont("Segoe UI", 10), text_color=MUTED, justify="left"
        ).pack(anchor="w", padx=14, pady=(0, 8))

        # (switch_widget, browser_name, size_label_widget)
        self._browser_rows: list = []

        browser_defs = [
            ("Chrome",    "Google Chrome"),
            ("Edge",      "Microsoft Edge"),
            ("Brave",     "Brave Browser"),
            ("Firefox",   "Mozilla Firefox"),
            ("Opera",     "Opera Browser"),
            ("Opera GX",  "Opera GX"),
            ("Vivaldi",   "Vivaldi Browser"),
            ("Chromium",  "Chromium (portable)"),
            ("Waterfox",  "Waterfox"),
            ("LibreWolf", "LibreWolf"),
            ("IE Legacy", "IE / Edge Legacy"),
        ]
        for bname, bdesc in browser_defs:
            sw, lbl = self._browser_switch_row(br_scroll, bname, bdesc)
            self._browser_rows.append((sw, bname, lbl))
        ctk.CTkFrame(br_scroll, fg_color="transparent", height=6).pack()

        # Kick off background size scan
        threading.Thread(target=self._scan_browser_sizes, daemon=True).start()


    def _switch_row(self, parent, title: str, subtitle: str, on: bool = False) -> ctk.CTkSwitch:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=5)

        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(txt, text=title, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=TEXT
                     ).pack(anchor="w")
        ctk.CTkLabel(txt, text=subtitle, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=MUTED
                     ).pack(anchor="w")

        sw = ctk.CTkSwitch(row, text="", width=52,
                           button_color=RED, button_hover_color=RED_H,
                           progress_color=RED, fg_color=BORDER)
        sw.pack(side="right")
        if on:
            sw.select()
        return sw

    def _browser_switch_row(self, parent, title: str, subtitle: str) -> tuple:
        """Switch row that also shows a live size label. Returns (switch, size_label)."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=4)

        sw = ctk.CTkSwitch(row, text="", width=52,
                           button_color=RED, button_hover_color=RED_H,
                           progress_color=RED, fg_color=BORDER)
        sw.pack(side="right")

        txt = ctk.CTkFrame(row, fg_color="transparent")
        txt.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(txt, text=title, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 12, "bold"), text_color=TEXT
                     ).pack(anchor="w")
        srow = ctk.CTkFrame(txt, fg_color="transparent")
        srow.pack(anchor="w", fill="x")
        ctk.CTkLabel(srow, text=subtitle, anchor="w",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=MUTED
                     ).pack(side="left")
        size_lbl = ctk.CTkLabel(srow, text="  scanning…", anchor="w",
                                font=ctk.CTkFont("Segoe UI", 10), text_color="#444c56")
        size_lbl.pack(side="left")
        return sw, size_lbl

    def _scan_browser_sizes(self):
        """Background thread: scan each browser's data size and update the label."""
        for sw, bname, lbl in self._browser_rows:
            try:
                count, total = get_browser_data_summary(bname)
                if total > 0:
                    text = f"  •  {format_bytes(total)} ({count} files)"
                    color = MUTED
                else:
                    text = "  •  not installed"
                    color = "#444c56"
            except Exception:
                text = ""
                color = "#444c56"
            self.after(0, lambda l=lbl, t=text, c=color: l.configure(text=t, text_color=c))

    # ───────────────────────────────────────────────────────────────────────
    # RECOVER TAB
    # ───────────────────────────────────────────────────────────────────────
    def setup_recover_tab(self):
        # ── Deep Scan ──
        self._section_label(self.tab_recover, "DEEP SCAN  —  Recover Permanently Deleted Files")
        dc = self._card(self.tab_recover)
        dc_inner = ctk.CTkFrame(dc, fg_color="transparent")
        dc_inner.pack(fill="x", padx=14, pady=10)

        ctrl = ctk.CTkFrame(dc_inner, fg_color="transparent")
        ctrl.pack(fill="x")

        ctk.CTkLabel(ctrl, text="Drive:", font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT).pack(side="left")
        drives = [f"{d}:" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:")]
        if not drives: drives = ["C:"]
        self.deep_drive = ctk.CTkOptionMenu(
            ctrl, values=drives, width=80,
            fg_color=INPUT, button_color=BORDER, text_color=TEXT,
            font=ctk.CTkFont("Segoe UI", 12)
        )
        self.deep_drive.pack(side="left", padx=(6, 14))

        ctk.CTkLabel(ctrl, text="Limit (MB):", font=ctk.CTkFont("Segoe UI", 12), text_color=TEXT).pack(side="left")
        self.deep_limit = ctk.CTkEntry(
            ctrl, width=80, fg_color=INPUT, border_color=BORDER,
            text_color=TEXT, font=ctk.CTkFont("Segoe UI", 12)
        )
        self.deep_limit.insert(0, "1024")
        self.deep_limit.pack(side="left", padx=6)
        ctk.CTkLabel(ctrl, text="(0 = full drive)",
                     font=ctk.CTkFont("Segoe UI", 10), text_color=MUTED).pack(side="left", padx=4)

        self.btn_stop_deep = ctk.CTkButton(
            ctrl, text="⏹  Stop", width=88, height=30,
            fg_color=BORDER, hover_color="#484f58",
            font=ctk.CTkFont("Segoe UI", 11), text_color=TEXT,
            corner_radius=6, command=self.stop_deep_scan, state="disabled"
        )
        self.btn_stop_deep.pack(side="right", padx=(4, 0))

        self.btn_deep_action = ctk.CTkButton(
            ctrl, text="🔍  Run Deep Scan", height=30,
            fg_color=BLUE, hover_color=BLUE_H,
            font=ctk.CTkFont("Segoe UI", 12, "bold"),
            corner_radius=6, command=self.run_deep_scan
        )
        self.btn_deep_action.pack(side="right", padx=4)

        self.deep_progress = ctk.CTkProgressBar(
            dc_inner, height=10, corner_radius=4, progress_color=BLUE, fg_color=BORDER
        )
        self.deep_progress.pack(fill="x", pady=(10, 2))
        self.deep_progress.set(0)

        self.deep_status_lbl = ctk.CTkLabel(
            dc_inner, text="Configure options and click Run Deep Scan",
            font=ctk.CTkFont("Consolas", 11), text_color=MUTED
        )
        self.deep_status_lbl.pack(anchor="w")

        # ── Recycle Bin ──
        self._section_label(self.tab_recover, "RECYCLE BIN RECOVERY")
        rbc = self._card(self.tab_recover, fill="both", expand=True, pady=(0, 4))
        rb_inner = ctk.CTkFrame(rbc, fg_color="transparent")
        rb_inner.pack(fill="both", expand=True, padx=14, pady=10)

        rb_top = ctk.CTkFrame(rb_inner, fg_color="transparent")
        rb_top.pack(fill="x", pady=(0, 6))

        self._secondary_btn(rb_top, "🔄  Refresh", self.refresh_recover_list, width=100).pack(side="left", padx=(0, 4))
        self._secondary_btn(rb_top, "Select All", self.select_all_recover, width=90).pack(side="left", padx=4)
        self._secondary_btn(rb_top, "Deselect All", self.deselect_all_recover, width=95).pack(side="left", padx=4)

        self.recover_scroll = ctk.CTkScrollableFrame(
            rb_inner, height=100,
            fg_color=INPUT, border_color=BORDER, border_width=1, corner_radius=6
        )
        self.recover_scroll.pack(fill="both", expand=True, pady=(0, 8))

        self.btn_recover_action = self._action_btn(
            rb_inner, "♻️  RECOVER SELECTED",
            self.run_recover, color=GREEN, hover=GREEN_H, height=44
        )
        self.btn_recover_action.pack(fill="x")
        self.btn_recover_action.configure(state="disabled")

    # ───────────────────────────────────────────────────────────────────────
    # UI STATE LOGIC
    # ───────────────────────────────────────────────────────────────────────
    def update_target_ui(self):
        def _do():
            self.target_listbox.configure(state="normal")
            self.target_listbox.delete("1.0", "end")
            if not self.targets:
                self.target_listbox.insert("end",
                    "  No items yet.\n  Click 'Add Files' or 'Add Folder' to get started.")
                self.shred_count_lbl.configure(text="No items selected", text_color=MUTED)
            else:
                for t in self.targets:
                    self.target_listbox.insert("end", f"  {t}\n")
                n = len(self.targets)
                self.shred_count_lbl.configure(
                    text=f"{n} item{'s' if n != 1 else ''} selected", text_color=SUCCESS
                )
            self.target_listbox.configure(state="disabled")
        self.after(0, _do)

    def add_files(self):
        files = filedialog.askopenfilenames(title="Select files to shred")
        if files:
            self.targets.extend(files)
            self.update_target_ui()

    def add_folder(self):
        folder = filedialog.askdirectory(title="Select folder to shred")
        if folder:
            self.targets.append(folder)
            self.update_target_ui()

    def clear_targets(self):
        self.targets.clear()
        self.update_target_ui()

    def refresh_wipe_drives(self):
        drives = [f"{d}:\\" for d in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if os.path.exists(f"{d}:")]
        self.wipe_drive.configure(values=drives or ["C:\\"])
        if drives:
            self.wipe_drive.set(drives[0])
            self._update_free_lbl(drives[0])

        def _fetch_android():
            from securedelete import get_android_devices
            androids = get_android_devices()
            def _update():
                final = list(drives)
                for dev in androids:
                    final.append(f"Android: {dev['name']} [{dev['id']}]")
                if not final:
                    final = ["C:\\"]
                self.wipe_drive.configure(values=final)
            self.after(0, _update)
        threading.Thread(target=_fetch_android, daemon=True).start()

    def _update_free_lbl(self, drive):
        try:
            free = get_free_space(drive)
            self.wipe_free_lbl.configure(text=f"Free: {format_bytes(free)}", text_color=SUCCESS)
        except Exception:
            self.wipe_free_lbl.configure(text="")

    # ───────────────────────────────────────────────────────────────────────
    # SHRED THREAD
    # ───────────────────────────────────────────────────────────────────────
    def run_shred(self):
        if not self.targets:
            messagebox.showwarning("No Files Selected",
                                   "Add files or folders to shred first.")
            return
        if messagebox.askyesno(
            "⚠  Confirm Permanent Destruction",
            f"You are about to permanently shred {len(self.targets)} item(s).\n\n"
            "Files will be overwritten multiple times and deleted.\n"
            "This action CANNOT be undone.\n\nContinue?"
        ):
            self.btn_shred_action.configure(state="disabled", text="⏳  Shredding…")
            threading.Thread(target=self._shred_thread, daemon=True).start()

    def _shred_thread(self):
        passes = int(self.shred_passes.get())
        ok, fail = 0, 0
        print(f"--- Shred started  ({passes} passes) ---")
        for t in list(self.targets):
            t = os.path.abspath(t)
            if os.path.isdir(t):
                s, f = shred_directory(t, passes=passes)
                ok += s; fail += f
            elif os.path.isfile(t):
                if shred_file(t, passes=passes): ok += 1
                else: fail += 1
        print(f"\n--- SHRED COMPLETE ---  Destroyed: {ok}   Failed: {fail}\n")
        self.targets.clear()
        self.update_target_ui()
        self.after(0, lambda: self.btn_shred_action.configure(
            state="normal", text="🔥  SHRED SELECTED FILES"))

    # ───────────────────────────────────────────────────────────────────────
    # WIPE THREAD
    # ───────────────────────────────────────────────────────────────────────
    def stop_wipe(self):
        if hasattr(self, "wipe_stop_event"):
            self.wipe_stop_event.set()
        self.btn_wipe_stop.configure(state="disabled")
        self.wipe_status_lbl.configure(text="⏳  Stopping wipe…")

    def run_wipe(self):
        drive = self.wipe_drive.get()
        if messagebox.askyesno(
            "⚠  Confirm Wipe",
            f"This will fill ALL free space on {drive} with random data.\n"
            "Previously deleted files will become unrecoverable.\n\n"
            "This can take a long time. Continue?"
        ):
            self.btn_wipe_action.configure(state="disabled", text="⏳  Wiping…")
            self.btn_wipe_stop.configure(state="normal")
            self.wipe_progress.set(0)
            self.wipe_stop_event = threading.Event()
            threading.Thread(target=self._wipe_thread, args=(drive,), daemon=True).start()

    def _wipe_thread(self, drive):
        passes = int(self.wipe_passes.get())

        def _ui(current_pass, total_passes, written, free, speed):
            pct = (written / free) if free > 0 else 0
            text = (f"Pass {current_pass}/{total_passes}  ·  "
                    f"{format_bytes(written)} / {format_bytes(free)} "
                    f"({pct*100:.1f}%)  ·  {format_bytes(speed)}/s")
            self.after(0, lambda: self.wipe_status_lbl.configure(text=text))
            self.after(0, lambda: self.wipe_progress.set(pct))

        if drive.startswith("Android:"):
            from securedelete import wipe_android_free_space
            m = re.search(r"\[(.*?)\]", drive)
            device_id = m.group(1) if m else drive
            wipe_android_free_space(device_id, passes=passes, update_callback=_ui)
        else:
            wipe_free_space(drive, passes=passes,
                            update_callback=_ui, stop_event=self.wipe_stop_event)

        stopped = self.wipe_stop_event.is_set()
        self.after(0, lambda: self.wipe_status_lbl.configure(
            text="🛑  Wipe stopped." if stopped else "✅  Wipe complete!"
        ))
        self.after(0, lambda: self.wipe_progress.set(
            self.wipe_progress.get() if stopped else 1.0))
        self.after(0, lambda: self.btn_wipe_action.configure(
            state="normal", text="🧹  WIPE FREE SPACE"))
        self.after(0, lambda: self.btn_wipe_stop.configure(state="disabled"))


    def run_clean(self):
        any_on = any(sw.get() for sw, _, _ in self._browser_rows) or \
                 any([self.sw_temp.get(), self.sw_recent.get(), self.sw_explorer.get(),
                      self.sw_inet.get(), self.sw_crash.get(), self.sw_dns.get(), self.sw_logs.get()])
        if not any_on:
            messagebox.showwarning("Nothing Selected", "Enable at least one cleanup option first.")
            return
        if messagebox.askyesno("⚠  Confirm Privacy Cleanup", "Selected system traces and browser histories will be permanently shredded.\nOpen browsers will be closed automatically.\n\nContinue?"):
            self.btn_clean_action.configure(state="disabled", text="⏳  Cleaning…")
            self.after(0, lambda: self.clean_progress.set(0))
            self.after(0, lambda: self.clean_status_lbl.configure(text="🔍  Scanning...", text_color=MUTED))
            threading.Thread(target=self._clean_thread, daemon=True).start()

    def _clean_thread(self):
        from securedelete import (
            clear_event_logs, close_browsers, shred_browser_data,
            shred_system_activities, shred_inet_cache, shred_crash_dumps,
            flush_dns_cache, shred_thumbnail_cache,
        )
        passes = int(self.clean_passes.get())

        def _set_progress(pct: float, status: str = "", color=None):
            self.after(0, lambda: self.clean_progress.set(min(pct, 1.0)))
            if status:
                c = color or MUTED
                self.after(0, lambda s=status, cl=c: self.clean_status_lbl.configure(text=s, text_color=cl))

        sys_drive = os.environ.get("SYSTEMDRIVE", "C:") + "\\"
        try:
            free_before = shutil.disk_usage(sys_drive).free
        except Exception:
            free_before = 0

        # ── Collect which browsers to clean ──
        to_clean = [bname for sw, bname, _ in self._browser_rows if sw.get()]

        # ── Estimate total work for progress bar ──
        total_steps  = sum([
            bool(self.sw_temp.get()),
            bool(self.sw_recent.get()),
            bool(self.sw_explorer.get()),
            bool(self.sw_inet.get()),
            bool(self.sw_crash.get()),
            bool(self.sw_dns.get()),
            bool(self.sw_logs.get()),
            len(to_clean),
        ])
        total_steps = max(total_steps, 1)
        step        = 0

        def _advance(label: str):
            nonlocal step
            pct = step / total_steps
            _set_progress(pct, f"  {pct*100:.0f}%  —  {label}")
            step += 1

        # ══════════════════════════════════════════
        # SYSTEM TRACES
        # ══════════════════════════════════════════

        # Temp & Prefetch
        if self.sw_temp.get():
            _advance("Cleaning Temp & Prefetch...")
            L      = os.environ.get("LOCALAPPDATA", "")
            windir = os.environ.get("WINDIR", "C:\\Windows")
            temp   = os.environ.get("TEMP", "")
            for path in [os.path.join(windir, "Temp"), temp,
                         os.path.join(L, "Temp"),
                         os.path.join(windir, "Prefetch")]:
                if path and os.path.isdir(path):
                    fc = sum(len(f) for _, _, f in os.walk(path))
                    print(f"  [SYSTEM] Cleaning {path} ({fc} files)")
                    s, f = shred_directory(path, passes=passes, verbose=False)
                    os.makedirs(path, exist_ok=True)
                    print(f"           ✓ {s} shredded, {f} failed")

        # Recent Files & Jump Lists
        if self.sw_recent.get():
            _advance("Cleaning Recent Files & Jump Lists...")
            A = os.environ.get("APPDATA", "")
            for path in [
                os.path.join(A, r"Microsoft\Windows\Recent"),
                os.path.join(A, r"Microsoft\Windows\Recent\AutomaticDestinations"),
                os.path.join(A, r"Microsoft\Windows\Recent\CustomDestinations"),
            ]:
                if os.path.isdir(path):
                    s, f = shred_directory(path, passes=passes, verbose=False)
                    os.makedirs(path, exist_ok=True)
                    print(f"  [SYSTEM] Recent: {s} shredded, {f} failed")

        # Explorer Thumbnail Cache
        if self.sw_explorer.get():
            _advance("Cleaning Explorer Thumbnail Cache...")
            shred_thumbnail_cache(passes=passes, verbose=True)

        # IE / Edge Legacy Cache
        if self.sw_inet.get():
            _advance("Cleaning IE / Edge Legacy Cache...")
            shred_inet_cache(passes=passes, verbose=True)

        # Crash Dumps
        if self.sw_crash.get():
            _advance("Cleaning Crash Dumps...")
            shred_crash_dumps(passes=passes, verbose=True)

        # DNS
        if self.sw_dns.get():
            _advance("Flushing DNS Cache...")
            flush_dns_cache(verbose=True)

        # Event Logs
        if self.sw_logs.get():
            _advance("Clearing Windows Event Logs...")
            clear_event_logs(verbose=True)

        # ══════════════════════════════════════════
        # BROWSERS
        # ══════════════════════════════════════════
        if to_clean:
            _set_progress(step / total_steps, "  Closing browsers...")
            print("  [BROWSER] Closing browsers...")
            close_browsers()
            time.sleep(1)
            for browser in to_clean:
                _advance(f"Cleaning {browser}...")
                shred_browser_data(browser, passes=passes, verbose=True)
                for sw, bname, lbl in self._browser_rows:
                    if bname == browser:
                        self.after(0, lambda l=lbl: l.configure(
                            text="  •  cleaned ✓", text_color=SUCCESS))

        # ── Space freed summary ──
        try:
            free_after  = shutil.disk_usage(sys_drive).free
            space_saved = free_after - free_before
        except Exception:
            space_saved = 0

        saved_str   = format_bytes(max(space_saved, 0))
        _set_progress(1.0, f"  ✅  Complete!  —  Space freed: {saved_str}", color=SUCCESS)

        print(f"\n{'='*60}")
        print(f"  ✅  Privacy Cleanup Complete!")
        if space_saved > 0:
            print(f"  💾  Space freed on {sys_drive}:  {saved_str}")
        else:
            print(f"  💾  Space delta on {sys_drive}:  {format_bytes(abs(space_saved))} "
                  f"(may reflect concurrent disk activity)")
        print(f"{'='*60}\n")

        self.after(0, lambda: self.btn_clean_action.configure(
            state="normal", text="🔒  CLEAN PRIVACY TRACES"))

    # ───────────────────────────────────────────────────────────────────────
    # RECOVER METHODS
    # ───────────────────────────────────────────────────────────────────────
    def refresh_recover_list(self):
        self.btn_recover_action.configure(state="disabled")
        for w in self.recover_scroll.winfo_children():
            w.destroy()
        self.recover_checkboxes.clear()
        ctk.CTkLabel(self.recover_scroll, text="⏳  Scanning Recycle Bin…",
                     text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12)).pack(pady=14)
        threading.Thread(target=self._refresh_recover_thread, daemon=True).start()

    def _refresh_recover_thread(self):
        from securedelete import get_recycle_bin_items
        items = get_recycle_bin_items()
        self.after(0, self._render_recover_items, items)

    def _render_recover_items(self, items):
        for w in self.recover_scroll.winfo_children():
            w.destroy()
        self.recover_items = items
        self.recover_checkboxes.clear()

        if not items:
            ctk.CTkLabel(self.recover_scroll, text="Recycle Bin is empty.",
                         text_color=MUTED, font=ctk.CTkFont("Segoe UI", 12)).pack(pady=16)
        else:
            for item in items:
                name = item.get("Name", "Unknown")
                size = item.get("Size", "?")
                date = item.get("DateDeleted", "?")
                chk = ctk.CTkCheckBox(
                    self.recover_scroll,
                    text=f"{name}   •   {size}   •   Deleted: {date}",
                    font=ctk.CTkFont("Segoe UI", 11), text_color=TEXT,
                    hover_color=GREEN, checkmark_color="white",
                    border_color=BORDER, fg_color=GREEN
                )
                chk.pack(anchor="w", padx=10, pady=4)
                self.recover_checkboxes.append((chk, item))

        self.btn_recover_action.configure(state="normal")

    def select_all_recover(self):
        for chk, _ in self.recover_checkboxes: chk.select()

    def deselect_all_recover(self):
        for chk, _ in self.recover_checkboxes: chk.deselect()

    def run_recover(self):
        to_recover = [item for chk, item in self.recover_checkboxes if chk.get()]
        if not to_recover:
            messagebox.showwarning("Nothing Selected", "Select items to recover first.")
            return
        if messagebox.askyesno(
            "Confirm Recovery",
            f"Recover {len(to_recover)} item(s) to their original locations?"
        ):
            self.btn_recover_action.configure(state="disabled", text="⏳  Recovering…")
            threading.Thread(target=self._recover_thread, args=(to_recover,), daemon=True).start()

    def _recover_thread(self, to_recover):
        from securedelete import recover_recycle_bin_item
        print(f"\n--- Recovering {len(to_recover)} item(s)… ---")
        ok, fail = 0, 0
        for item in to_recover:
            name = item.get("Name")
            print(f"  Restoring: {name}…")
            if recover_recycle_bin_item(item.get("Path")): ok += 1
            else: fail += 1
        print(f"\n--- COMPLETE ---  Recovered: {ok}   Failed: {fail}\n")
        self.after(0, self.refresh_recover_list)
        self.after(0, lambda: self.btn_recover_action.configure(
            state="normal", text="♻️  RECOVER SELECTED"))

    def stop_deep_scan(self):
        if hasattr(self, "deep_stop_event"):
            self.deep_stop_event.set()
        self.btn_stop_deep.configure(state="disabled")
        self.deep_status_lbl.configure(text="⏳  Stopping scan…")

    def run_deep_scan(self):
        drive = self.deep_drive.get()
        try:
            limit_mb = int(self.deep_limit.get())
        except ValueError:
            messagebox.showerror("Invalid Input", "Scan limit must be a number.")
            return
        msg = (f"Raw signature carve on {drive}  (limit: {limit_mb} MB).\n"
               if limit_mb > 0 else
               f"Full drive raw signature carve on {drive}.\n")
        if messagebox.askyesno("Confirm Deep Scan",
                               msg + "Results saved to 'Recovered_Files' folder.\n\n"
                               "This may take significant time. Continue?"):
            self.btn_deep_action.configure(state="disabled", text="⏳  Scanning…")
            self.btn_stop_deep.configure(state="normal")
            self.deep_stop_event = threading.Event()
            self.deep_progress.set(0)
            threading.Thread(target=self._deep_scan_thread,
                             args=(drive, limit_mb), daemon=True).start()

    def _deep_scan_thread(self, drive, limit_mb):
        from securedelete import carve_drive
        limit_bytes = limit_mb * 1024 * 1024
        out_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Recovered_Files")

        print(f"\n{'='*60}")
        print(f"  Deep Carve: {drive}  " +
              (f"(limit: {limit_mb} MB)" if limit_mb > 0 else "(full drive)"))
        print(f"{'='*60}\n")

        total_size = limit_bytes
        if limit_bytes == 0:
            try: total_size = shutil.disk_usage(drive).total
            except: total_size = 0

        def _ui(current, total, found):
            actual = total if total > 0 else total_size
            pct = (current / actual) if actual > 0 else 0
            text = (f"{format_bytes(current)} / {format_bytes(actual)} "
                    f"({pct*100:.1f}%)  ·  {found} file(s) found"
                    if actual > 0 else
                    f"{format_bytes(current)} scanned  ·  {found} file(s) found")
            self.after(0, lambda: self.deep_status_lbl.configure(text=text))
            self.after(0, lambda: self.deep_progress.set(pct))

        t0 = time.time()
        found = carve_drive(drive, out_dir, max_scan_bytes=limit_bytes,
                            update_callback=_ui, stop_event=self.deep_stop_event)
        elapsed = time.time() - t0
        print(f"\n--- SCAN COMPLETE ---  {found} file(s) recovered  ({elapsed:.1f}s)\n")

        if found > 0:
            try: os.startfile(out_dir)
            except: pass

        stopped = self.deep_stop_event.is_set()
        self.after(0, lambda: self.deep_status_lbl.configure(
            text=f"{'🛑  Stopped' if stopped else '✅  Complete'}  ·  {found} file(s) recovered."))
        self.after(0, lambda: self.deep_progress.set(1.0))
        self.after(0, lambda: self.btn_deep_action.configure(
            state="normal", text="🔍  Run Deep Scan"))
        self.after(0, lambda: self.btn_stop_deep.configure(state="disabled"))


# ===========================================================================
# ENTRY POINT
# ===========================================================================
if __name__ == "__main__":
    def is_admin():
        try: return ctypes.windll.shell32.IsUserAnAdmin()
        except: return False

    if not is_admin():
        script = os.path.abspath(sys.argv[0])
        args = f'"{script}" ' + " ".join(sys.argv[1:])
        ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, args, None, 1)
        sys.exit()
    else:
        app = SecureDeleteApp()
        app.mainloop()