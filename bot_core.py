import ctypes
from ctypes import wintypes
import os
import sys
import time
import random
import difflib
import subprocess
import re
import threading

import numpy as np
import cv2
import pyautogui
import pytesseract
from PIL import ImageGrab

from discord_notifier import notifier
from timeout_manager import TimeoutManager
import pygetwindow as gw


def enable_monitor_dpi_awareness():
    try:
        if ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return
    except Exception:
        pass
    try:
        if ctypes.windll.shcore.SetProcessDpiAwareness(2) == 0:
            return
    except Exception:
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass


enable_monitor_dpi_awareness()


class MonitorInfo(ctypes.Structure):
    _fields_ = [
        ('cbSize', wintypes.DWORD),
        ('rcMonitor', wintypes.RECT),
        ('rcWork', wintypes.RECT),
        ('dwFlags', wintypes.DWORD),
        ('szDevice', wintypes.WCHAR * 32),
    ]


class DEVMODEW(ctypes.Structure):
    _fields_ = [
        ('dmDeviceName', wintypes.WCHAR * 32),
        ('dmSpecVersion', wintypes.WORD),
        ('dmDriverVersion', wintypes.WORD),
        ('dmSize', wintypes.WORD),
        ('dmDriverExtra', wintypes.WORD),
        ('dmFields', wintypes.DWORD),
        ('dmPositionX', ctypes.c_long),
        ('dmPositionY', ctypes.c_long),
        ('dmDisplayOrientation', wintypes.DWORD),
        ('dmDisplayFixedOutput', wintypes.DWORD),
        ('dmColor', ctypes.c_short),
        ('dmDuplex', ctypes.c_short),
        ('dmYResolution', ctypes.c_short),
        ('dmTTOption', ctypes.c_short),
        ('dmCollate', ctypes.c_short),
        ('dmFormName', wintypes.WCHAR * 32),
        ('dmLogPixels', wintypes.WORD),
        ('dmBitsPerPel', wintypes.DWORD),
        ('dmPelsWidth', wintypes.DWORD),
        ('dmPelsHeight', wintypes.DWORD),
        ('dmDisplayFlags', wintypes.DWORD),
        ('dmDisplayFrequency', wintypes.DWORD),
        ('dmICMMethod', wintypes.DWORD),
        ('dmICMIntent', wintypes.DWORD),
        ('dmMediaType', wintypes.DWORD),
        ('dmDitherType', wintypes.DWORD),
        ('dmReserved1', wintypes.DWORD),
        ('dmReserved2', wintypes.DWORD),
        ('dmPanningWidth', wintypes.DWORD),
        ('dmPanningHeight', wintypes.DWORD),
    ]


def get_native_resolution(device_name):
    try:
        dm = DEVMODEW()
        dm.dmSize = ctypes.sizeof(dm)
        if ctypes.windll.user32.EnumDisplaySettingsW(device_name, -1, ctypes.byref(dm)):
            if dm.dmPelsWidth > 0 and dm.dmPelsHeight > 0:
                return int(dm.dmPelsWidth), int(dm.dmPelsHeight)
    except Exception:
        pass
    return None


def get_monitors():
    monitors = []
    try:
        api = ctypes.WinDLL('user32', use_last_error=True)
        callback_type = ctypes.WINFUNCTYPE(
            wintypes.BOOL,
            wintypes.HMONITOR,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM
        )
        api.GetMonitorInfoW.argtypes = [wintypes.HMONITOR, ctypes.POINTER(MonitorInfo)]
        api.GetMonitorInfoW.restype = wintypes.BOOL
        api.EnumDisplayMonitors.argtypes = [
            wintypes.HDC,
            ctypes.c_void_p,
            callback_type,
            wintypes.LPARAM
        ]
        api.EnumDisplayMonitors.restype = wintypes.BOOL

        def collect(handle, _dc, _rect, _data):
            info = MonitorInfo()
            info.cbSize = ctypes.sizeof(info)
            if api.GetMonitorInfoW(handle, ctypes.byref(info)):
                rect = info.rcMonitor
                is_primary = bool(info.dwFlags & 1)
                device = str(info.szDevice)
                monitors.append({
                    'handle': handle,
                    'device': device,
                    'left': rect.left,
                    'top': rect.top,
                    'right': rect.right,
                    'bottom': rect.bottom,
                    'width': rect.right - rect.left,
                    'height': rect.bottom - rect.top,
                    'is_primary': is_primary,
                })
            return True

        if not api.EnumDisplayMonitors(None, None, callback_type(collect), 0):
            pass
    except Exception as e:
        print(f"[!] Error enumerating monitors: {e}")

    if not monitors:
        # Fallback to single primary screen
        monitors.append({
            'handle': None,
            'device': r'\\.\DISPLAY1',
            'left': 0,
            'top': 0,
            'right': 1920,
            'bottom': 1080,
            'width': 1920,
            'height': 1080,
            'is_primary': True,
        })

    monitors.sort(key=lambda m: (not m['is_primary'], m['left'], m['top']))
    for idx, m in enumerate(monitors, start=1):
        m['index'] = idx
        nr = get_native_resolution(m['device'])
        disp_w, disp_h = nr if nr else (m['width'], m['height'])
        m['native_width'] = disp_w
        m['native_height'] = disp_h
        primary_str = " (Primary)" if m['is_primary'] else ""
        m['label'] = f"Monitor {idx}{primary_str} - {disp_w}x{disp_h} [{m['device']}]"

    return monitors


def get_monitor(choice=1, monitors=None):
    if monitors is None:
        monitors = get_monitors()

    for monitor in monitors:
        if choice in (monitor['device'], monitor['label'], monitor['index']):
            return monitor

    try:
        idx = int(choice)
        for monitor in monitors:
            if monitor['index'] == idx:
                return monitor
    except (ValueError, TypeError):
        pass

    return monitors[0] if monitors else None


def force_activate_window(win):
    if not win:
        return
    hwnd = getattr(win, '_hWnd', None)
    if hwnd:
        try:
            user32 = ctypes.windll.user32
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)
            else:
                user32.ShowWindow(hwnd, 5)
            user32.SetForegroundWindow(hwnd)
        except Exception:
            pass
    try:
        win.activate()
    except Exception:
        pass


def position_and_resize_game_window(win, selected_monitor=1):
    if not win:
        return False
    monitor = get_monitor(selected_monitor)
    x = monitor['left'] - 7
    y = monitor['top']

    force_activate_window(win)
    time.sleep(0.15)

    hwnd = getattr(win, '_hWnd', None)
    if hwnd:
        try:
            api = ctypes.WinDLL('user32', use_last_error=True)
            api.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT
            ]
            api.SetWindowPos.restype = wintypes.BOOL
            api.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
            api.GetWindowRect.restype = wintypes.BOOL

            for attempt in range(3):
                # SWP_NOZORDER (4) | SWP_NOACTIVATE (64) = 68
                api.SetWindowPos(hwnd, None, x, y, 1024, 768, 68)
                time.sleep(0.15)
                rect = wintypes.RECT()
                if api.GetWindowRect(hwnd, ctypes.byref(rect)):
                    if abs(rect.left - x) <= 15 and abs(rect.top - y) <= 15:
                        return True
        except Exception as e:
            print(f"[!] Warning SetWindowPos: {e}")

    try:
        win.moveTo(x, y)
        win.resizeTo(1024, 768)
        time.sleep(0.15)
    except Exception as e:
        print(f"[!] Warning resize: {e}")

    return True


class MonitorTimeoutManager(TimeoutManager):
    def handle_restart_no_encounter(self):
        timeout_minutes = self.bot.config.get('restart_no_encounter_minutes', 5)
        print(f"[!] No encounters for {timeout_minutes} minutes. Restarting.")
        self.bot.stop_moving()
        self.bot.reconnecting = True
        self.bot.loading_after_restart = True
        self.bot.in_combat = False
        self.bot.last_restart_time = time.time()
        self.bot.record_restart()
        self.bot.win = launch_and_setup_game(
            self.bot.config['game_path'],
            force_restart=True,
            selected_monitor=self.bot.config.get('selected_monitor')
        )
        if self.bot.win:
            self.bot.check_bicycle()
        self.bot.last_encounter_time = time.time()
        self.bot.last_connect_click = 0
        self.bot.last_connect_check = 0
        self.bot.last_disconnect_check = time.time()
        self.bot.disconnect_confirm_count = 0
        self.bot.bike_checked_after_reconnect = False
        self.bot.last_bike_check_after_reconnect = time.time()


def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    candidate = os.path.join(base_path, relative_path)
    if not os.path.exists(candidate):
        assets_candidate = os.path.join(base_path, "assets", relative_path)
        if os.path.exists(assets_candidate):
            return assets_candidate
    return candidate


# Assets and Templates
TEMPLATE_FILE = resource_path('fight_template.png')
ENCOUNTER_TEMPLATE = resource_path('encounter_start.png')
BIKE_TEMPLATE = resource_path('cycle.png')
GRASS_TEMPLATE = resource_path('middle.png')
ELITE_TEMPLATE = resource_path('elite.png')
CONNECT_TEMPLATE = resource_path('connect_button.png')
DISCONNECT_TEMPLATE = resource_path('disconnect_screen.png')
POPUP_X_TEMPLATE = resource_path('popup_x.png')
REQUEST_X_TEMPLATE = resource_path('request_x.png')
LEARN_MOVE_TEMPLATE = resource_path('learn_move.png')
EVOLVE_YES_TEMPLATE = resource_path('evolve_yes.png')
ONLINE_TEMPLATE = resource_path('online.png')
ANUBISIUS_TEMPLATE = resource_path('Anubisius.png')
SHINY_TEMPLATE = resource_path('shiny.png')

TARGET_WINDOW_TITLE = 'Poke Nexus'
pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False


def find_game_window():
    try:
        wins = gw.getWindowsWithTitle(TARGET_WINDOW_TITLE)
        if wins:
            return wins[0]
        for w in gw.getAllWindows():
            if w.title and ('poke nexus' in w.title.lower() or w.title.strip() == TARGET_WINDOW_TITLE):
                return w
        for w in gw.getAllWindows():
            if w.title and 'pokenexus' in w.title.lower():
                return w
    except Exception:
        pass
    return None


# Coordinate Definitions (Relative to 1024x768 game window)
PLAY_AREA = (7, 29, 1010, 758)
CHAR_CENTER = (510, 429)

ENCOUNTER_BOX = (630, 134, 670, 170)
ELITE_BOX = (326, 193, 437, 216)

CONNECT_BUTTON_BOX = (429, 539, 661, 620)
DISCONNECT_BOX = (275, 465, 745, 520)


def match_template_safe(img, template, method=cv2.TM_CCOEFF_NORMED):
    if img is None or template is None:
        return 0.0, (0, 0)
    ih, iw = img.shape[:2]
    th, tw = template.shape[:2]
    if iw < tw or ih < th:
        return 0.0, (0, 0)
    try:
        res = cv2.matchTemplate(img, template, method)
        _, max_val, _, max_loc = cv2.minMaxLoc(res)
        return float(max_val), max_loc
    except Exception:
        return 0.0, (0, 0)


POPUP_X_SEARCH_BOX = (682, 289, 716, 328)
REQUEST_X_BOX = (612, 303, 690, 349)

LEARN_MOVE_BOX = (356, 246, 458, 281)
FORGET_MOVE_2_POS = (592, 389)

EVOLVE_YES_BOX = (328, 622, 481, 652)
EVOLVE_YES_POS = (404, 637)

BIKE_BOX = (495, 415, 535, 465)

ANUBISIUS_SEARCH_BOX = (815, 451, 993, 494)
PLAYER_LIST_CLICK_POS = (56, 723)
PLAYER_LIST_DRAG_END = (1000, 1000)
ANUBISIUS_CHECK_INTERVAL = 30
ANUBISIUS_REOPEN_DELAY_AFTER_RESTART = 10

POKEMON_NAME_BOX = (300, 196, 520, 215)
SHINY_BOX = (325, 193, 356, 217)

POKEMON_LIST_FILE = resource_path('pokemons.txt')
TESSERACT_PATH = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
if os.path.exists(TESSERACT_PATH):
    pytesseract.pytesseract.tesseract_cmd = TESSERACT_PATH


class PokeBot:
    def __init__(self, win, config):
        self.win = win
        self.config = config
        self.running = True
        self.last_direction = None
        self.last_encounter_time = time.time()
        self.start_time = time.time()
        self.stop_reason = 'Running'

        self.session_stats = {
            'encounters': 0,
            'restarts': 0,
            'requests_declined': 0,
            'anubisius_pauses': 0,
        }

        self.timeout_manager = MonitorTimeoutManager(self)
        self.in_break = False
        self.in_combat = False
        self.reconnecting = False
        self.loading_after_restart = False

        self.last_connect_click = 0
        self.last_connect_check = 0
        self.connect_check_interval = 3

        self.last_disconnect_check = 0
        self.disconnect_check_interval = 3
        self.disconnect_confirm_count = 0

        self.last_restart_time = 0
        self.restart_cooldown = 90

        self.last_bike_check_after_reconnect = 0
        self.next_bike_retry_time = 0
        self.bike_retry_count = 0
        self.max_bike_retries = 3
        self.bike_checked_after_reconnect = False

        self.last_anubisius_check = time.time() + 30
        self.anubisius_notified = False
        self.online_list_ready = False
        self.waiting_to_reopen_anubisius_list = False
        self.anubisius_reopen_time = 0
        self.paused_for_anubisius = False

        self.current_encounter_name = '-'
        self.current_encounter_shiny = False
        self.current_battle_action = 'normal'
        self.pokemon_ocr_running = False
        self.battle_paused = False
        self.paused_for_pokemon = False

        self.pokemon_names = self.load_pokemon_names()

        base_interval = self.config.get('break_interval', 30)
        self.next_break_time = time.time() + random.randint(
            max(1, base_interval - 5), base_interval + 5
        ) * 60

        # Load grayscale templates
        self.fight_tpl = cv2.imread(TEMPLATE_FILE, 0)
        self.enc_tpl = cv2.imread(ENCOUNTER_TEMPLATE, 0)
        self.bike_tpl = cv2.imread(BIKE_TEMPLATE, 0)
        self.grass_tpl = cv2.imread(GRASS_TEMPLATE, 0)
        self.elite_tpl = cv2.imread(ELITE_TEMPLATE, 0)
        self.connect_tpl = cv2.imread(CONNECT_TEMPLATE, 0)
        self.disconnect_tpl = cv2.imread(DISCONNECT_TEMPLATE, 0)
        self.popup_x_tpl = cv2.imread(POPUP_X_TEMPLATE, 0)
        self.request_x_tpl = cv2.imread(REQUEST_X_TEMPLATE, 0)
        self.learn_move_tpl = cv2.imread(LEARN_MOVE_TEMPLATE, 0)
        self.evolve_yes_tpl = cv2.imread(EVOLVE_YES_TEMPLATE, 0)
        self.online_tpl = cv2.imread(ONLINE_TEMPLATE, 0)
        self.anubisius_tpl = cv2.imread(ANUBISIUS_TEMPLATE, 0)
        self.shiny_tpl = cv2.imread(SHINY_TEMPLATE, 0)

    def load_pokemon_names(self):
        names = []
        if os.path.exists(POKEMON_LIST_FILE):
            try:
                with open(POKEMON_LIST_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        name = line.strip()
                        if name:
                            names.append(name)
            except Exception as e:
                print(f"[!] Error loading pokemon names: {e}")
        return names

    def normalize_pokemon_text(self, text):
        if not text:
            return ""
        text = text.lower()
        text = text.replace('♀', '')
        text = text.replace('♂', '')
        text = text.replace('’', '')
        text = text.replace("'", '')
        text = text.replace('.', '')
        text = text.replace(':', '')
        text = text.replace('-', '')
        text = re.sub(r'[^a-z0-9 ]', '', text)
        text = re.sub(r'\s+', ' ', text).strip()
        return text

    def preprocess_pokemon_name_image(self, img):
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        gray = cv2.resize(gray, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
        _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def read_raw_pokemon_name_ocr(self):
        try:
            bbox = (
                self.win.left + POKEMON_NAME_BOX[0],
                self.win.top + POKEMON_NAME_BOX[1],
                self.win.left + POKEMON_NAME_BOX[2],
                self.win.top + POKEMON_NAME_BOX[3]
            )
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            processed = self.preprocess_pokemon_name_image(img)
            config = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]-:.??'? "
            text = pytesseract.image_to_string(processed, config=config)
            return text.strip()
        except Exception as e:
            print("[OCR] Pokemon name read failed:", e)
            return ""

    def confirm_shiny_during_combat(self):
        if not self.in_combat or self.shiny_tpl is None:
            return False
        search = self.grab_gray(SHINY_BOX)
        max_val, _ = match_template_safe(search, self.shiny_tpl)
        return max_val > 0.85

    def clean_ocr_pokemon_name(self, raw_text):
        text = raw_text.strip()
        for item in ('[S]', '[s]', '[S', '[s', 'S]', 's]'):
            text = text.replace(item, '')
        return text.strip()

    def fuzzy_match_pokemon_name(self, text):
        if not text or not self.pokemon_names:
            return text.strip() if text else '-'
        cleaned = self.normalize_pokemon_text(text)
        normalized_map = {self.normalize_pokemon_text(name): name for name in self.pokemon_names}

        if cleaned in normalized_map:
            return normalized_map[cleaned]

        matches = difflib.get_close_matches(cleaned, list(normalized_map.keys()), n=1, cutoff=0.6)
        if matches:
            return normalized_map[matches[0]]

        words = cleaned.split()
        first_word = words[0] if words else ''
        if first_word:
            if first_word in normalized_map:
                return normalized_map[first_word]
            sub_matches = difflib.get_close_matches(first_word, list(normalized_map.keys()), n=1, cutoff=0.65)
            if sub_matches:
                return normalized_map[sub_matches[0]]

        return text.strip()

    def read_encounter_pokemon(self):
        raw_text = self.read_raw_pokemon_name_ocr()
        cleaned_name = self.clean_ocr_pokemon_name(raw_text)
        matched_name = self.fuzzy_match_pokemon_name(cleaned_name)
        self.current_encounter_name = matched_name
        self.current_encounter_shiny = False
        print(f"[OCR] Encounter: {matched_name} | Raw: {raw_text}")
        return matched_name, False, raw_text

    def clear_current_encounter(self):
        self.current_encounter_name = '-'
        self.current_encounter_shiny = False

    def get_current_encounter_display(self):
        if self.current_encounter_name == '-':
            return '-'
        shiny_tag = " [Shiny]" if self.current_encounter_shiny else ""
        return f"{self.current_encounter_name}{shiny_tag}"

    def normalize_config_pokemon_list(self, values):
        out = set()
        for v in values:
            norm = self.normalize_pokemon_text(v)
            if norm:
                out.add(norm)
        return out

    def get_battle_action_for_encounter(self, pokemon_name, is_shiny):
        normalized_name = self.normalize_pokemon_text(pokemon_name)
        catch_shinies = self.config.get('catch_shinies', False)
        pause_list = self.normalize_config_pokemon_list(self.config.get('pause_pokemon', []))
        catch_list = self.normalize_config_pokemon_list(self.config.get('catch_pokemon', []))
        run_list = self.normalize_config_pokemon_list(self.config.get('run_from_pokemon', []))

        if is_shiny and catch_shinies:
            return 'catch'
        if normalized_name in pause_list:
            return 'pause'
        if normalized_name in catch_list:
            return 'catch'
        if normalized_name in run_list:
            return 'run'
        return 'normal'

    def get_custom_move_for_encounter(self):
        moves = self.config.get('pokemon_moves', {})
        if self.current_encounter_name in moves:
            return str(moves[self.current_encounter_name])
        return '1'

    def read_encounter_pokemon_async(self):
        if self.pokemon_ocr_running:
            return
        self.pokemon_ocr_running = True

        def worker():
            try:
                name, is_shiny, _ = self.read_encounter_pokemon()
                self.current_battle_action = self.get_battle_action_for_encounter(name, is_shiny)
            except Exception as e:
                print(f"[OCR] Async OCR error: {e}")
            finally:
                self.pokemon_ocr_running = False

        threading.Thread(target=worker, daemon=True).start()

    def run_from_current_encounter(self):
        print("[Battle] Running from configured Pokemon.")
        self.stop_moving()
        time.sleep(random.uniform(0.15, 0.45))
        pyautogui.press('4')
        time.sleep(1.0)

    def catch_current_encounter(self):
        print("[Battle] Catching configured Pokemon.")
        self.stop_moving()
        start = time.time()
        while self.running and self.check_for_encounter():
            pyautogui.press('2')
            time.sleep(random.uniform(0.12, 0.35))
            pyautogui.press('3')
            time.sleep(5.0 + random.uniform(0.0, 0.35))
            if time.time() - start > 70:
                print("[!] Catch sequence timeout.")
                break

    def pause_on_current_encounter(self):
        print("[Battle] Paused on configured Pokemon.")
        self.stop_moving()
        self.battle_paused = True
        self.paused_for_pokemon = True
        self.last_encounter_time = time.time()
        user_id = self.config.get('discord_user_id')
        if user_id:
            notifier.send_dm(user_id, f"Paused on {self.current_encounter_name}.")

    def stop_moving(self):
        if self.last_direction:
            pyautogui.keyUp(self.last_direction)
            self.last_direction = None

    def stop_bot(self, reason):
        self.stop_moving()
        self.running = False
        self.stop_reason = reason

    def record_restart(self):
        self.session_stats['restarts'] += 1

    def format_runtime(self):
        elapsed = int(time.time() - self.start_time)
        hours = elapsed // 3600
        minutes = (elapsed % 3600) // 60
        seconds = elapsed % 60
        return f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    def get_session_summary(self):
        return (
            f"Last Session\n"
            f"━━━━━━━━━━\n"
            f"Runtime: {self.format_runtime()}\n"
            f"Encounters: {self.session_stats['encounters']}\n"
            f"Restarts: {self.session_stats['restarts']}\n"
            f"Requests Declined: {self.session_stats['requests_declined']}\n"
            f"Anubisius Pauses: {self.session_stats['anubisius_pauses']}"
        )

    def grab_gray(self, box):
        bbox = (
            self.win.left + box[0],
            self.win.top + box[1],
            self.win.left + box[2],
            self.win.top + box[3]
        )
        try:
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        except Exception:
            try:
                img = ImageGrab.grab(bbox=bbox)
                return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
            except Exception:
                w = max(1, box[2] - box[0])
                h = max(1, box[3] - box[1])
                return np.zeros((h, w), dtype=np.uint8)

    def check_auto_stop(self):
        limit = self.config.get('auto_stop_minutes', 0)
        if limit and limit > 0:
            if (time.time() - self.start_time) >= limit * 60:
                print(f"[!] Auto stop reached after {limit} minutes.")
                self.stop_bot(f"Auto-stop ({limit}m)")
                return True
        return False

    def should_skip_no_encounter_timeout(self):
        return self.in_break or self.in_combat or self.reconnecting or self.loading_after_restart or self.paused_for_anubisius or self.paused_for_pokemon

    def check_for_encounter(self):
        if self.enc_tpl is None:
            return False
        gray = self.grab_gray(ENCOUNTER_BOX)
        max_val, _ = match_template_safe(gray, self.enc_tpl)
        return max_val > 0.85

    def check_elite_fast(self):
        if self.elite_tpl is None:
            return False
        gray = self.grab_gray(ELITE_BOX)
        max_val, _ = match_template_safe(gray, self.elite_tpl)
        return max_val > 0.72

    def check_special_popup_fast(self):
        if self.popup_x_tpl is None:
            return False
        gray = self.grab_gray(POPUP_X_SEARCH_BOX)
        max_val, max_loc = match_template_safe(gray, self.popup_x_tpl)
        if max_val > 0.75:
            print("[!] Popup X detected. Closing popup.")
            click_x = self.win.left + POPUP_X_SEARCH_BOX[0] + max_loc[0] + self.popup_x_tpl.shape[1] // 2
            click_y = self.win.top + POPUP_X_SEARCH_BOX[1] + max_loc[1] + self.popup_x_tpl.shape[0] // 2
            pyautogui.click(click_x, click_y)
            time.sleep(0.3)
            return True
        return False

    def check_request_decline(self):
        if not self.config.get('auto_decline_requests', False):
            return False
        if self.request_x_tpl is None:
            return False
        gray = self.grab_gray(REQUEST_X_BOX)
        max_val, max_loc = match_template_safe(gray, self.request_x_tpl)
        if max_val > 0.75:
            print("[!] Request popup detected. Declining request.")
            click_x = self.win.left + REQUEST_X_BOX[0] + max_loc[0] + self.request_x_tpl.shape[1] // 2
            click_y = self.win.top + REQUEST_X_BOX[1] + max_loc[1] + self.request_x_tpl.shape[0] // 2
            pyautogui.click(click_x, click_y)
            self.session_stats['requests_declined'] += 1
            time.sleep(0.3)
            return True
        return False

    def check_learn_move(self):
        if self.learn_move_tpl is None:
            return False
        gray = self.grab_gray(LEARN_MOVE_BOX)
        max_val, _ = match_template_safe(gray, self.learn_move_tpl)
        if max_val > 0.8:
            print("[!] Learn move popup detected. Replacing 2nd move.")
            click_x = self.win.left + FORGET_MOVE_2_POS[0]
            click_y = self.win.top + FORGET_MOVE_2_POS[1]
            pyautogui.click(click_x, click_y)
            time.sleep(0.5)
            return True
        return False

    def check_evolution(self):
        if self.evolve_yes_tpl is None:
            return False
        gray = self.grab_gray(EVOLVE_YES_BOX)
        max_val, _ = match_template_safe(gray, self.evolve_yes_tpl)
        if max_val > 0.8:
            print("[!] Evolution popup detected. Clicking YES.")
            click_x = self.win.left + EVOLVE_YES_POS[0]
            click_y = self.win.top + EVOLVE_YES_POS[1]
            pyautogui.click(click_x, click_y)
            time.sleep(0.5)
            return True
        return False

    def click_game_center(self):
        if self.win:
            force_activate_window(self.win)
            pyautogui.click(self.win.left + 512, self.win.top + 384)

    def find_template_fullscreen_center(self, template, threshold=0.75):
        if template is None or not self.win:
            return None
        bbox = (self.win.left, self.win.top, self.win.left + 1024, self.win.top + 768)
        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
        max_val, max_loc = match_template_safe(gray, template)
        if max_val >= threshold:
            th, tw = template.shape[:2]
            return (self.win.left + max_loc[0] + tw // 2, self.win.top + max_loc[1] + th // 2)
        return None

    def open_and_drag_online_list(self):
        pause_enabled = self.config.get('pause_when_anubisius_online', False)
        discord_id = self.config.get('discord_user_id', '')
        if not pause_enabled and not (discord_id and self.config.get('notify_anubisius', False)):
            return False
        if self.online_tpl is None or not self.win:
            return False
        self.stop_moving()
        print("[*] Opening online player list.")
        pyautogui.click(self.win.left + 7 + PLAYER_LIST_CLICK_POS[0], self.win.top + PLAYER_LIST_CLICK_POS[1])
        time.sleep(0.8)

        found = self.find_template_fullscreen_center(self.online_tpl, threshold=0.75)
        if not found:
            print("[!] Online list title not found.")
            self.online_list_ready = False
            self.click_game_center()
            return False

        pyautogui.moveTo(found[0], found[1], duration=0.15)
        pyautogui.mouseDown()
        monitor = get_monitor(self.config.get('selected_monitor', 1))
        target_x = max(monitor['left'], min(monitor['right'] - 1, self.win.left + PLAYER_LIST_DRAG_END[0]))
        target_y = max(monitor['top'], min(monitor['bottom'] - 1, self.win.top + PLAYER_LIST_DRAG_END[1]))
        pyautogui.moveTo(target_x, target_y, duration=0.55)
        pyautogui.mouseUp()
        time.sleep(0.3)
        self.online_list_ready = True
        self.click_game_center()
        return True

    def detect_anubisius(self):
        if self.anubisius_tpl is None:
            return False
        gray = self.grab_gray(ANUBISIUS_SEARCH_BOX)
        max_val, _ = match_template_safe(gray, self.anubisius_tpl)
        return max_val > 0.72

    def check_anubisius_online(self):
        if self.reconnecting or self.loading_after_restart or self.in_combat or self.in_break:
            return self.paused_for_anubisius
        pause_enabled = self.config.get('pause_when_anubisius_online', False)
        discord_id = self.config.get('discord_user_id', '')
        if not pause_enabled and not (discord_id and self.config.get('notify_anubisius', False)):
            return False

        now = time.time()
        if self.waiting_to_reopen_anubisius_list:
            if now >= self.anubisius_reopen_time:
                self.waiting_to_reopen_anubisius_list = False
                self.open_and_drag_online_list()

        if now - self.last_anubisius_check < ANUBISIUS_CHECK_INTERVAL:
            return self.paused_for_anubisius

        self.last_anubisius_check = now
        if not self.online_list_ready:
            self.open_and_drag_online_list()

        is_online = self.detect_anubisius()
        if is_online:
            if not self.anubisius_notified:
                print("[!] ANUBISIUS DETECTED ONLINE!")
                user_id = self.config.get('discord_user_id')
                if user_id:
                    notifier.send_dm(user_id, "[Alert] Anubisius is online!")
                self.anubisius_notified = True

            if self.config.get('pause_when_anubisius_online', False):
                if not self.paused_for_anubisius:
                    print("[!] Pausing bot because Anubisius is online.")
                    self.stop_moving()
                    self.paused_for_anubisius = True
                    self.session_stats['anubisius_pauses'] += 1
        else:
            if self.anubisius_notified:
                print("[*] Anubisius is no longer detected.")
                self.anubisius_notified = False
            if self.paused_for_anubisius:
                print("[*] Resuming bot - Anubisius is offline.")
                self.paused_for_anubisius = False

        return self.paused_for_anubisius

    def schedule_anubisius_reopen_after_restart(self):
        self.waiting_to_reopen_anubisius_list = True
        self.anubisius_reopen_time = time.time() + ANUBISIUS_REOPEN_DELAY_AFTER_RESTART
        self.online_list_ready = False

    def check_connect_button(self):
        if self.connect_tpl is None:
            return False
        try:
            gray = self.grab_gray(CONNECT_BUTTON_BOX)
            max_val, _ = match_template_safe(gray, self.connect_tpl)
            return max_val > 0.75
        except Exception:
            return False

    def reconnect_if_needed(self):
        now = time.time()
        if now - self.last_connect_check < self.connect_check_interval:
            return self.reconnecting or self.loading_after_restart

        self.last_connect_check = now
        if self.check_connect_button():
            self.reconnecting = True
            self.loading_after_restart = False
            self.bike_checked_after_reconnect = False
            self.bike_retry_count = 0
            self.next_bike_retry_time = 0
            self.stop_moving()

            if now - self.last_connect_click >= 30:
                print("[!] Connect button detected. Clicking reconnect.")
                click_x = self.win.left + CONNECT_BUTTON_BOX[0] + (CONNECT_BUTTON_BOX[2] - CONNECT_BUTTON_BOX[0]) // 2
                click_y = self.win.top + CONNECT_BUTTON_BOX[1] + (CONNECT_BUTTON_BOX[3] - CONNECT_BUTTON_BOX[1]) // 2
                pyautogui.click(click_x, click_y)
                self.last_connect_click = now
            return True

        if self.reconnecting:
            time.sleep(2.0)
            if not self.check_connect_button():
                print("[*] Reconnect succeeded.")
                self.reconnecting = False
                self.check_bicycle()
                self.schedule_anubisius_reopen_after_restart()
                self.last_encounter_time = time.time()
            return True

        return False

    def check_disconnect_fast(self):
        now = time.time()
        if now - self.last_restart_time < self.restart_cooldown:
            return False
        if now - self.last_disconnect_check < self.disconnect_check_interval:
            return False
        self.last_disconnect_check = now
        if self.disconnect_tpl is None:
            return False

        gray = self.grab_gray(DISCONNECT_BOX)
        max_val, _ = match_template_safe(gray, self.disconnect_tpl)
        if max_val > 0.8:
            self.disconnect_confirm_count += 1
            if self.disconnect_confirm_count >= 2:
                return True
        else:
            self.disconnect_confirm_count = 0
        return False

    def restart_after_disconnect(self):
        self.record_restart()
        user_id = self.config.get('discord_user_id')
        if user_id:
            notifier.send_dm(user_id, "Bot has been restarted.")
        print("[!] Disconnect confirmed. Restarting game.")
        self.stop_moving()
        self.reconnecting = True
        self.loading_after_restart = True
        self.in_combat = False
        self.last_restart_time = time.time()

        self.win = launch_and_setup_game(
            self.config['game_path'],
            force_restart=True,
            selected_monitor=self.config.get('selected_monitor')
        )
        if self.win:
            self.check_bicycle()
            self.schedule_anubisius_reopen_after_restart()
        self.last_encounter_time = time.time()
        self.last_connect_click = 0
        self.last_connect_check = 0
        self.last_disconnect_check = time.time()
        self.disconnect_confirm_count = 0
        self.bike_checked_after_reconnect = False

    def combat_sequence(self):
        self.stop_moving()
        self.session_stats['encounters'] += 1
        self.current_battle_action = 'normal'
        self.battle_paused = False
        self.in_combat = True
        self.clear_current_encounter()
        print("\n[!] BATTLE START...", flush=True)

        time.sleep(2.0 + random.uniform(0.15, 0.45))
        print("[OCR] Initiating Synchronous Scan...", flush=True)
        pokemon_name, _, _ = self.read_encounter_pokemon()
        is_shiny = self.confirm_shiny_during_combat()
        self.current_encounter_shiny = is_shiny

        if is_shiny:
            print(f"[Shiny] CONFIRMED: {pokemon_name}", flush=True)

        self.current_battle_action = self.get_battle_action_for_encounter(pokemon_name, is_shiny)
        print(f"[OCR] Name detected: {pokemon_name} (Action: {self.current_battle_action})", flush=True)

        self.check_special_popup_fast()

        if self.current_battle_action == 'pause':
            self.pause_on_current_encounter()
            self.in_combat = False
            return

        if self.current_battle_action == 'catch':
            self.catch_current_encounter()
            self.in_combat = False
            return

        if self.current_battle_action == 'run':
            self.run_from_current_encounter()
            self.last_encounter_time = time.time()
            self.in_combat = False
            return

        if self.check_elite_fast():
            print("[!] Elite detected. Running.", flush=True)
            time.sleep(random.uniform(0.15, 0.45))
            pyautogui.press('4')
            time.sleep(1.0)
            self.last_encounter_time = time.time()
            self.in_combat = False
            return

        custom_move = self.get_custom_move_for_encounter()
        battle_start_time = time.time()
        attack_interval = 0.42

        while self.running:
            self.check_special_popup_fast()
            if not self.check_for_encounter():
                time.sleep(0.12)
                if not self.check_for_encounter():
                    break

            time.sleep(random.uniform(0.05, 0.25))

            if custom_move == '1':
                pyautogui.press('1')
                time.sleep(attack_interval + random.uniform(0.0, 0.2))
            else:
                pyautogui.press('1')
                time.sleep(random.uniform(0.65, 0.9))
                pyautogui.press(custom_move)
                time.sleep(attack_interval + random.uniform(0.05, 0.2))

            if time.time() - battle_start_time > 70:
                print("[!] Combat timeout reached.", flush=True)
                break

        self.last_encounter_time = time.time()
        self.in_combat = False
        print(">>> Battle finished.", flush=True)

    def scan_grass_grid(self):
        try:
            if self.grass_tpl is None or not self.win:
                return []

            bbox = (
                self.win.left + PLAY_AREA[0],
                self.win.top + PLAY_AREA[1],
                self.win.left + PLAY_AREA[2],
                self.win.top + PLAY_AREA[3]
            )

            screen = np.array(ImageGrab.grab(bbox=bbox, all_screens=True))
            gray_screen = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)

            th, tw = self.grass_tpl.shape[:2]
            gh, gw = gray_screen.shape[:2]
            if gw < tw or gh < th:
                return []

            res = cv2.matchTemplate(gray_screen, self.grass_tpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= 0.8)
            if len(loc[0]) == 0:
                loc = np.where(res >= 0.72)

            rel_char_x = CHAR_CENTER[0] - PLAY_AREA[0]
            rel_char_y = CHAR_CENTER[1] - PLAY_AREA[1]

            directions = {
                "w": 0,
                "s": 0,
                "a": 0,
                "d": 0
            }

            tile_size = self.grass_tpl.shape[0]

            for pt in zip(*loc[::-1]):
                if abs(pt[1] - rel_char_y) < tile_size:
                    if pt[0] > rel_char_x:
                        directions["d"] += 1
                    elif pt[0] < rel_char_x:
                        directions["a"] += 1

                if abs(pt[0] - rel_char_x) < tile_size:
                    if pt[1] > rel_char_y:
                        directions["s"] += 1
                    elif pt[1] < rel_char_y:
                        directions["w"] += 1

            return [
                k for k, v in directions.items()
                if v > 0
            ]

        except Exception:
            return []

    def move_left_right(self):
        new_dir = random.choice(['a', 'd'])
        if new_dir != self.last_direction:
            self.stop_moving()
            pyautogui.keyDown(new_dir)
            self.last_direction = new_dir
        time.sleep(random.uniform(0.12, 0.25))

    def move_up_down(self):
        new_dir = random.choice(['w', 's'])
        if new_dir != self.last_direction:
            self.stop_moving()
            pyautogui.keyDown(new_dir)
            self.last_direction = new_dir
        time.sleep(random.uniform(0.12, 0.25))

    def move_grass_detection(self):
        valid_moves = self.scan_grass_grid()
        new_dir = (
            random.choice(valid_moves)
            if valid_moves
            else random.choice(['w', 'a', 's', 'd'])
        )
        if new_dir != self.last_direction:
            self.stop_moving()
            pyautogui.keyDown(new_dir)
            self.last_direction = new_dir
        time.sleep(random.uniform(0.12, 0.17))

    def move(self):
        if not self.running:
            return

        if self.check_disconnect_fast():
            self.restart_after_disconnect()
            return

        if self.reconnect_if_needed():
            time.sleep(1)
            return

        if self.check_auto_stop():
            return

        self.check_request_decline()
        self.check_learn_move()
        self.check_evolution()
        self.check_anubisius_online()

        if self.timeout_manager.should_restart_no_encounter():
            self.timeout_manager.handle_restart_no_encounter()
            return

        if self.paused_for_anubisius or self.paused_for_pokemon:
            self.stop_moving()
            time.sleep(1)
            return

        now = time.time()
        if self.config.get('enable_breaks', False) and now >= self.next_break_time:
            self.in_break = True
            self.stop_moving()
            break_duration = self.config.get('break_duration', 10)
            print(f"[*] Taking break for {break_duration} minutes...")

            if self.config.get('close_on_break', False):
                exe_name = os.path.basename(self.config.get('game_path', ''))
                if exe_name:
                    os.system(f'taskkill /f /im "{exe_name}" >nul 2>&1')

            time.sleep(break_duration * 60)

            base_interval = self.config.get('break_interval', 30)
            self.next_break_time = time.time() + (random.randint(max(1, base_interval - 5), base_interval + 5) * 60)

            self.win = launch_and_setup_game(
                self.config['game_path'],
                force_restart=True,
                selected_monitor=self.config.get('selected_monitor', 1)
            )
            self.click_game_center()
            self.schedule_anubisius_reopen_after_restart()

            for bike_attempt in range(3):
                if self.check_bicycle():
                    break
                print(f"[Bike] Break-return retry {bike_attempt + 1}/3 failed.")
                time.sleep(random.uniform(3.0, 4.5))

            self.last_encounter_time = time.time()
            self.in_break = False
            return

        mode = self.config.get('mode', 'grass_detection')
        if mode == 'left_right':
            self.move_left_right()
        elif mode == 'up_down':
            self.move_up_down()
        else:
            self.move_grass_detection()

        if self.check_for_encounter():
            self.combat_sequence()
            return

    def is_bicycle_equipped(self):
        if self.bike_tpl is None:
            return False
        try:
            bbox = (
                self.win.left + BIKE_BOX[0],
                self.win.top + BIKE_BOX[1],
                self.win.left + BIKE_BOX[2],
                self.win.top + BIKE_BOX[3]
            )
            img = ImageGrab.grab(bbox=bbox, all_screens=True)
            gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)
            max_val, _ = match_template_safe(gray, self.bike_tpl)
            return max_val > 0.70
        except Exception:
            return False

    def check_bicycle(self):
        self.stop_moving()
        self.click_game_center()
        time.sleep(0.5)

        pyautogui.press('s')
        time.sleep(0.35)

        equipped = self.is_bicycle_equipped()
        if equipped:
            print("[Bike] Bicycle already equipped.")
            self.click_game_center()
            return True

        print("[Bike] Bicycle not detected. Pressing B.")
        pyautogui.press('b')
        time.sleep(0.9)
        equipped = self.is_bicycle_equipped()
        self.click_game_center()
        return equipped


def launch_and_setup_game(game_path, force_restart=False, selected_monitor=1):
    if not game_path or not os.path.exists(game_path):
        print(f"[!] Game executable not found at: {game_path}")
        return None

    if force_restart:
        exe_name = os.path.basename(game_path)
        os.system(f'taskkill /f /im "{exe_name}" >nul 2>&1')
        time.sleep(2 + random.uniform(0.0, 3.0))

    try:
        subprocess.Popen([game_path])
    except Exception as e:
        print(f"[!] Error launching game: {e}")
        return None

    win = None
    for _ in range(30):
        wins = gw.getWindowsWithTitle(TARGET_WINDOW_TITLE)
        if wins:
            win = wins[0]
            break
        time.sleep(1)

    if win:
        position_and_resize_game_window(win, selected_monitor)
        time.sleep(4)
        return win

    print(f"[!] Window '{TARGET_WINDOW_TITLE}' not found after launch.")
    return None
