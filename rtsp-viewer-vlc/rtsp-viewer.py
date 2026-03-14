import tkinter as tk
import json
import vlc
import time
import sys

CONFIG_FILE = "config.json"
WINDOW_WIDTH = 1100
WINDOW_HEIGHT = 650
SIDEBAR_WIDTH = 240
SIDEBAR_COLLAPSED = 32

BTN_FONT = ("Arial", 11)
BTN_HEIGHT = 2


class rtspviewer:
    def __init__(self, root):
        self.root = root
        self.root.title("rtsp-viewer")
        self.root.geometry(f"{WINDOW_WIDTH}x{WINDOW_HEIGHT}")
        self.root.minsize(WINDOW_WIDTH, WINDOW_HEIGHT)

        self.current_stream     = 0         # Current stream displayed
        self.switch_interval    = 5000      # in milliseconds (5000ms = 5s)
        self.rotation_enabled   = tk.BooleanVar(value=False)
        self.grid_enabled       = tk.BooleanVar(value=False)
        self.rotation_job       = None
        self.updating_mode      = False

        self.current_url = None
        self.sidebar_visible = True
        self.fullscreen = False
        self.stream_buttons = {}

        # ---------- Layout ----------
        self.sidebar_container = tk.Frame(root, width=SIDEBAR_WIDTH, bg="#1e1e1e")
        self.sidebar_container.pack(side="left", fill="y")
        self.sidebar_container.pack_propagate(False)

        # Toggle button
        self.toggle_btn = tk.Button(
            self.sidebar_container,
            text="◀",
            command=self.toggle_sidebar,
            bg="#1e1e1e",
            fg="white",
            relief="flat",
            font=("Arial", 12, "bold"),
        )
        self.toggle_btn.pack(anchor="ne", padx=4, pady=4)

        # Scrollable sidebar
        self.canvas = tk.Canvas(
            self.sidebar_container,
            bg="#1e1e1e",
            highlightthickness=0
        )
        self.scrollbar = tk.Scrollbar(
            self.sidebar_container,
            orient="vertical",
            command=self.canvas.yview
        )
        self.scrollable_frame = tk.Frame(self.canvas, bg="#1e1e1e")

        self.scrollable_frame.bind(
            "<Configure>",
            lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all"))
        )

        self.canvas_window = self.canvas.create_window(
            (0, 0),
            window=self.scrollable_frame,
            anchor="nw"
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        # Mouse enter/leave bindings (reliable on Linux/Pi)
        self.canvas.bind("<Enter>", self._bind_mousewheel)
        self.canvas.bind("<Leave>", self._unbind_mousewheel)
        self.canvas.bind("<Configure>", self._resize_sidebar)
        
        # Video area
        self.video_frame = tk.Frame(root, bg="black")
        self.video_frame.pack(side="right", fill="both", expand=True)

        self.single_container = tk.Frame(self.video_frame)
        self.single_container.pack(fill="both", expand=True)
        self.grid_container = tk.Frame(self.video_frame)
        self.video_panel = tk.Frame(self.single_container, bg="black")
        self.video_panel.pack(fill="both", expand=True)

        # ---------- VLC ----------
        self.instance = vlc.Instance(
            "--network-caching=400",
            "--avcodec-hw=none",
            "--no-xlib",
            "--rtsp-tcp",
            "--no-video-title-show",
            "--drop-late-frames",
            "--skip-frames",
            "--clock-jitter=0",
            "--clock-synchro=0",
        )

        self.player = self.instance.media_player_new()

        self.root.update_idletasks()
        if sys.platform.startswith("linux"):
            self.player.set_xwindow(self.video_panel.winfo_id())
        else:
            self.player.set_hwnd(self.video_panel.winfo_id())

        # ---------- Load config ----------
        self.streams = self.load_config()
        self.build_sidebar()
        self.bind_hotkeys()

        # Fullscreen key
        self.root.bind("f", self.toggle_fullscreen)
        self.root.bind("<Escape>", self.exit_fullscreen)

        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.nbstreams = len(self.streams)

        # Auto start
        if self.streams:
            self.play_stream(self.streams[0]["url"])

    # ================================
    # Scroll wheel
    # ================================
    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    # ================================
    # Sidebar toggle
    # ================================
    def toggle_sidebar(self):
        if self.sidebar_visible:
            self.sidebar_container.config(width=SIDEBAR_COLLAPSED)
            self.canvas.pack_forget()
            self.scrollbar.pack_forget()
            self.toggle_btn.config(text="▶")
            self.sidebar_visible = False
        else:
            self.sidebar_container.config(width=SIDEBAR_WIDTH)
            self.canvas.pack(side="left", fill="both", expand=True)
            self.scrollbar.pack(side="right", fill="y")
            self.toggle_btn.config(text="◀")
            self.sidebar_visible = True
    def _resize_sidebar(self, event):
        # Force inner frame to match canvas width
        self.canvas.itemconfig(self.canvas_window, width=event.width)

    # ================================
    # Fullscreen
    # ================================
    def toggle_fullscreen(self, event=None):
        self.fullscreen = not self.fullscreen
        self.root.attributes("-fullscreen", self.fullscreen)

    def exit_fullscreen(self, event=None):
        self.fullscreen = False
        self.root.attributes("-fullscreen", False)

    # ================================
    # Enable cycle streams
    # ================================
    def toggle_rotation(self):
        if self.updating_mode: return

        if self.rotation_enabled.get():
            # Disable grid
            self.updating_mode = True
            self.grid_enabled.set(False)
            self.updating_mode = False
            self.destroy_grid()

            self.player.stop()
            if sys.platform.startswith("linux"):    self.player.set_xwindow(self.video_panel.winfo_id())
            else:                                   self.player.set_hwnd(self.video_panel.winfo_id())
            self.root.update_idletasks()

            self.schedule_rotation()
        else:
            if self.rotation_job:
                self.root.after_cancel(self.rotation_job)
                self.rotation_job = None

    # ================================
    # Toggle Grid view
    # ================================
    def toggle_grid(self):
        if self.updating_mode: return

        if self.grid_enabled.get():
            # stop rotation
            self.updating_mode = True
            self.rotation_enabled.set(False)
            self.updating_mode = False
            if self.rotation_job:
                self.root.after_cancel(self.rotation_job)
            # stop player principal
            self.player.stop()
            # masquer vue simple
            self.single_container.pack_forget()
            # afficher grille
            self.grid_container.pack(fill="both", expand=True)
            self.create_grid()
        else:
            self.destroy_grid()
            # masquer grille
            self.grid_container.pack_forget()
            # réafficher vue normale
            self.single_container.pack(fill="both", expand=True)
            self.root.update_idletasks()
            
            if sys.platform.startswith("linux"):
                self.player.set_xwindow(self.video_panel.winfo_id())
            else:
                self.player.set_hwnd(self.video_panel.winfo_id())
            url = self.streams[self.current_stream]['url']

            media = self.instance.media_new(url)
            self.player.set_media(media)
            self.player.play()

    # ================================
    # Grid view
    # ================================
    def create_grid(self):

        self.grid_players = []
        self.grid_frames = []
        for r in range(2):
            for c in range(2):

                frame = tk.Frame(self.grid_container, bg="black")
                frame.grid(row=r, column=c, sticky="nsew")

                self.grid_container.grid_rowconfigure(r, weight=1)
                self.grid_container.grid_columnconfigure(c, weight=1)

                self.root.update_idletasks()

                player = self.instance.media_player_new()
                if sys.platform.startswith("linux"):
                    player.set_xwindow(frame.winfo_id())
                else:
                    player.set_hwnd(frame.winfo_id())

                index = r * 2 + c

                if index < len(self.streams):

                    media = self.instance.media_new(self.streams[index]['url'])
                    player.set_media(media)
                    player.play()

                self.grid_players.append(player)
                self.grid_frames.append(frame)

    def destroy_grid(self):

        if hasattr(self, "grid_players"):
            for p in self.grid_players:
                p.stop()

        for f in getattr(self, "grid_frames", []):
            f.destroy()

        self.grid_players = []
        self.grid_frames = []

    # ================================
    # Config
    # ================================
    def load_config(self):
        with open(CONFIG_FILE, "r") as f:
            data = json.load(f)
        return data.get("streams", [])

    # ================================
    # Sidebar buttons
    # ================================
    def build_sidebar(self):
        title = tk.Label(
            self.scrollable_frame,
            text="CAMERAS",
            fg="white",
            bg="#1e1e1e",
            font=("Arial", 13, "bold"),
        )
        title.pack(pady=10)

        for stream in self.streams:
            btn = tk.Button(
                self.scrollable_frame,
                text=stream["name"],
                anchor="w",
                command=lambda url=stream["url"]: self.play_stream(url),
                bg="#2b2b2b",
                fg="white",
                relief="flat",
                font=("Arial", 12),
                height=2,
                padx=14,
                pady=6,
                bd=0,
                highlightthickness=0,
            )
            btn.pack(fill="x", padx=8, pady=4)

        # Cycle streams toggle button
        self.rotate_checkbox = tk.Checkbutton(
            self.scrollable_frame,
            text="Cycle streams",
            variable=self.rotation_enabled,
            command=self.toggle_rotation,
            bg="#2b2b2b",
            fg="white",
            selectcolor="#2b2b2b",
            activebackground="#2b2b2b",
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            font=("Arial", 12)
        )
        self.rotate_checkbox.pack(anchor="w", padx=5, pady=5)

        # Enable grid mode
        self.grid_checkbox = tk.Checkbutton(
            self.scrollable_frame,
            text="Grid view (2x2)",
            variable=self.grid_enabled,
            command=self.toggle_grid,
            bg="#2b2b2b",
            fg="white",
            selectcolor="#2b2b2b",
            activebackground="#2b2b2b",
            activeforeground="white",
            relief="flat",
            borderwidth=0,
            font=("Arial", 12)
        )
        self.grid_checkbox.pack(anchor="w", padx=5, pady=2)

    # ================================
    # Hotkeys
    # ================================
    def bind_hotkeys(self):
        for stream in self.streams:
            key = f"<{stream['hotkey']}>"
            self.root.bind(key, lambda e, url=stream["url"]: self.play_stream(url))

    # ================================
    # Playback
    # ================================
    def play_stream(self, url):
        if url == self.current_url:
            return

        print(f"Switching to {url}")

        # Highlight active button
        if self.current_url in self.stream_buttons:
            self.stream_buttons[self.current_url].config(bg="#2b2b2b")

        if url in self.stream_buttons:
            self.stream_buttons[url].config(bg="#3a6ea5")

        self.current_url = url

        self.player.stop()
        self.root.update()

        self.root.after(200, lambda: self._start_media(url))

    def _start_media(self, url):
        media = self.instance.media_new(url)
        self.player.set_media(media)
        self.player.play()

    # ================================
    # Cycle streams
    # ================================
    def schedule_rotation(self):

        if not self.rotation_enabled.get():
            return

        self.switch_stream()

        self.rotation_job = self.root.after(
            self.switch_interval,
            self.schedule_rotation
        )

    def switch_stream(self):

        if not self.streams:
            return

        if self.current_stream >= self.nbstreams: self.current_stream = 0
        url = self.streams[self.current_stream]['url']
        self.player.stop()
        time.sleep(1)

        self.root.after(100, lambda: self._start_media(url))

        # media = self.instance.media_new(url)
        # self.player.set_media(media)
        # self.player.play()
        
        self.current_stream += 1

    # ================================
    # Cleanup
    # ================================
    def on_close(self):
        self.player.stop()
        time.sleep(0.2)
        self.root.destroy()
    def _bind_mousewheel(self, event=None):
        # Windows / Mac
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)
        # Linux (Raspberry Pi)
        self.canvas.bind_all("<Button-4>", self._on_mousewheel_linux)
        self.canvas.bind_all("<Button-5>", self._on_mousewheel_linux)

    def _unbind_mousewheel(self, event=None):
        self.canvas.unbind_all("<MouseWheel>")
        self.canvas.unbind_all("<Button-4>")
        self.canvas.unbind_all("<Button-5>")

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def _on_mousewheel_linux(self, event):
        if event.num == 4:
            self.canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self.canvas.yview_scroll(1, "units")

if __name__ == "__main__":
    root = tk.Tk()
    app = rtspviewer(root)
    root.mainloop()
