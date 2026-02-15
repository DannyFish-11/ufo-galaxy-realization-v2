import keyboard
import threading

class KeyListener(threading.Thread):
    def __init__(self, toggle_callback):
        super().__init__()
        self.toggle_callback = toggle_callback
        self.daemon = True

    def run(self):
        # 监听所有按键，找到 Fn 键的 scan code
        # 注意：Fn 键通常没有标准的 keycode，需要通过 scan code 捕获
        # 这里我们用 F12 作为替代，因为 Fn 键很难直接捕获
        keyboard.add_hotkey('f12', self.toggle_callback)
        print("Press F12 to toggle the sidebar.")
        keyboard.wait()

if __name__ == '__main__':
    def test_toggle():
        print("Sidebar toggled!")

    listener = KeyListener(test_toggle)
    listener.start()
    listener.join() # Keep the main thread alive
