import tkinter as tk
from tkinter import scrolledtext
import threading
import time

class Sidebar(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("UFO³ Galaxy")
        self.geometry("300x600")
        self.overrideredirect(True)  # 隐藏标题栏

        self.is_hidden = True
        self.attributes("-alpha", 0.0) # 完全透明

        self.create_widgets()
        self.hide_sidebar()

    def create_widgets(self):
        self.main_frame = tk.Frame(self, bg="#2E2E2E")
        self.main_frame.pack(fill=tk.BOTH, expand=True)

        self.title_label = tk.Label(self.main_frame, text="UFO³ Galaxy", fg="white", bg="#2E2E2E", font=("Segoe UI", 12, "bold"))
        self.title_label.pack(pady=10)

        self.log_area = scrolledtext.ScrolledText(self.main_frame, wrap=tk.WORD, bg="#1E1E1E", fg="#D4D4D4", insertbackground="white")
        self.log_area.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        self.input_entry = tk.Entry(self.main_frame, bg="#3C3C3C", fg="white", insertbackground="white")
        self.input_entry.pack(pady=10, padx=10, fill=tk.X)
        self.input_entry.bind("<Return>", self.send_command)

    def send_command(self, event):
        command = self.input_entry.get()
        if command:
            self.log_message(f">> {command}")
            # 在这里添加将命令发送到 Node 50 的逻辑
            self.input_entry.delete(0, tk.END)

    def log_message(self, message):
        self.log_area.insert(tk.END, f"{message}\n")
        self.log_area.see(tk.END)

    def toggle_sidebar(self):
        if self.is_hidden:
            self.show_sidebar()
        else:
            self.hide_sidebar()

    def show_sidebar(self):
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        self.geometry(f"300x{screen_height}+{screen_width - 300}+0")
        self.lift()
        self.attributes("-topmost", True)
        
        for i in range(101):
            alpha = i / 100
            self.attributes("-alpha", alpha)
            self.update()
            time.sleep(0.005)
            
        self.is_hidden = False

    def hide_sidebar(self):
        for i in range(101):
            alpha = (100 - i) / 100
            self.attributes("-alpha", alpha)
            self.update()
            time.sleep(0.005)

        screen_width = self.winfo_screenwidth()
        self.geometry(f"300x600+{screen_width}+0")
        self.is_hidden = True

if __name__ == "__main__":
    app = Sidebar()
    app.mainloop()
