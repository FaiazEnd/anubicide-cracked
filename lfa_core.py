from modules.discord_notifier import notifier
from modules.timeout_manager import TimeoutManager
from modules.monitor_manager import position_and_resize_window, get_monitor
import pygetwindow as gw
import pyautogui
import cv2
import pytesseract
import numpy as np
from PIL import ImageGrab
import time
import random
import difflib
import subprocess
import os
import sys
import re
import threading
import ctypes

try:
    ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
except Exception:
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass

def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

TEMPLATE_FILE = resource_path("assets/fight_template.png")
ENCOUNTER_TEMPLATE = resource_path("assets/encounter_start.png")
BIKE_TEMPLATE = resource_path("assets/cycle.png")
GRASS_TEMPLATE = resource_path("assets/middle.png")
ELITE_TEMPLATE = resource_path("assets/elite.png")
CONNECT_TEMPLATE = resource_path("assets/connect_button.png")
DISCONNECT_TEMPLATE = resource_path("assets/disconnect_screen.png")
POPUP_X_TEMPLATE = resource_path("assets/popup_x.png")
REQUEST_X_TEMPLATE = resource_path("assets/request_x.png")
LEARN_MOVE_TEMPLATE = resource_path("assets/learn_move.png")
EVOLVE_YES_TEMPLATE = resource_path("assets/evolve_yes.png")
ONLINE_TEMPLATE = resource_path("assets/online.png")
ANUBISIUS_TEMPLATE = resource_path("assets/Anubisius.png")

TARGET_WINDOW_TITLE = "Poke Nexus"

pyautogui.PAUSE = 0.0
pyautogui.FAILSAFE = False

PLAY_AREA = (7, 29, 1010, 758)
CHAR_CENTER = (510, 429)

ENCOUNTER_BOX = (630, 134, 670, 170)
ELITE_BOX = (326, 193, 437, 216)

CONNECT_BUTTON_BOX = (429, 539, 661, 620)
DISCONNECT_BOX = (289, 471, 719, 514)

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
POKEMON_LIST_FILE = resource_path("data/pokemons.txt")
TESSERACT_PATH = r"C:\Program Files\Tesseract-OCR\tesseract.exe"
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
        self.stop_reason = "Running"
        self.session_stats = {
            "encounters": 0,
            "restarts": 0,
            "requests_declined": 0,
            "anubisius_pauses": 0
        }

        self.timeout_manager = TimeoutManager(self)

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

        self.last_anubisius_check = 0
        self.anubisius_notified = False
        self.online_list_ready = False
        self.waiting_to_reopen_anubisius_list = False
        self.anubisius_reopen_time = 0
        self.paused_for_anubisius = False

        self.current_encounter_name = "-"
        self.current_encounter_shiny = False
        self.current_battle_action = "normal"
        self.pokemon_ocr_running = False
        self.battle_paused = False
        self.paused_for_pokemon = False
        self.pokemon_names = self.load_pokemon_names()

        base_interval = self.config.get("break_interval", 30)
        self.next_break_time = time.time() + (
            random.randint(base_interval - 5, base_interval + 5) * 60
        )

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
        notifier.start()
        

    def load_pokemon_names(self):
        try:
            if not os.path.exists(POKEMON_LIST_FILE):
                print("[OCR] pokemons.txt not found.")
                return []

            with open(POKEMON_LIST_FILE, "r", encoding="utf-8") as f:
                return [line.strip() for line in f if line.strip()]

        except Exception as e:
            print("[OCR] Failed to load pokemons.txt:", e)
            return []

    def normalize_pokemon_text(self, text):
        text = text.lower()
        text = text.replace("♀", "")
        text = text.replace("♂", "")
        text = text.replace("’", "")
        text = text.replace("'", "")
        text = text.replace(".", "")
        text = text.replace(":", "")
        text = text.replace("-", "")
        text = re.sub(r"[^a-z0-9 ]", "", text)
        text = re.sub(r"\\s+", " ", text).strip()
        return text

    def preprocess_pokemon_name_image(self, img):
        gray = cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

        gray = cv2.resize(
            gray,
            None,
            fx=4,
            fy=4,
            interpolation=cv2.INTER_CUBIC
        )

        _, thresh = cv2.threshold(
            gray,
            0,
            255,
            cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )

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

            config = "--psm 7 -c tessedit_char_whitelist=ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]-:.♀♂'’ "

            text = pytesseract.image_to_string(
                processed,
                config=config
            )

            return text.strip()

        except Exception as e:
            print("[OCR] Pokemon name read failed:", e)
            return ""

    def detect_shiny_from_ocr(self, raw_text):
        upper_text = raw_text.upper().strip()

        return (
            "[S]" in upper_text
            or upper_text.startswith("[S")
            or upper_text.startswith("S]")
            or upper_text.startswith("S ")
        )

    def clean_ocr_pokemon_name(self, raw_text):
        text = raw_text.strip()

        for item in ["[S]", "[s]", "[S", "[s", "S]", "s]"]:
            text = text.replace(item, "")

        return text.strip()

    def fuzzy_match_pokemon_name(self, text):
        if not text or not self.pokemon_names:
            return text.strip() if text else "-"

        cleaned = self.normalize_pokemon_text(text)

        normalized_map = {
            self.normalize_pokemon_text(name): name
            for name in self.pokemon_names
        }

        if cleaned in normalized_map:
            return normalized_map[cleaned]

        matches = difflib.get_close_matches(
            cleaned,
            list(normalized_map.keys()),
            n=1,
            cutoff=0.60
        )

        if matches:
            return normalized_map[matches[0]]

        first_word = cleaned.split()[0] if cleaned.split() else ""

        if first_word:
            matches = difflib.get_close_matches(
                first_word,
                list(normalized_map.keys()),
                n=1,
                cutoff=0.70
            )

            if matches:
                return normalized_map[matches[0]]

        return text.strip() if text else "-"

    def read_encounter_pokemon(self):
        raw_text = self.read_raw_pokemon_name_ocr()
        is_shiny = self.detect_shiny_from_ocr(raw_text)
        cleaned_name = self.clean_ocr_pokemon_name(raw_text)
        matched_name = self.fuzzy_match_pokemon_name(cleaned_name)

        self.current_encounter_name = matched_name
        self.current_encounter_shiny = is_shiny

        if is_shiny:
            print(f"[OCR] Encounter: Shiny {matched_name} | Raw: {raw_text}")
        else:
            print(f"[OCR] Encounter: {matched_name} | Raw: {raw_text}")

        return matched_name, is_shiny, raw_text

    def clear_current_encounter(self):
        self.current_encounter_name = "-"
        self.current_encounter_shiny = False

    def get_current_encounter_display(self):
        if not self.current_encounter_name or self.current_encounter_name == "-":
            return "Encounter: -"

        if self.current_encounter_shiny:
            return f"Encounter: Shiny {self.current_encounter_name}"

        return f"Encounter: {self.current_encounter_name}"

    def normalize_config_pokemon_list(self, values):
        normalized = set()

        if not values:
            return normalized

        if isinstance(values, str):
            values = [
                item.strip()
                for item in values.split(",")
                if item.strip()
            ]

        for item in values:
            normalized.add(self.normalize_pokemon_text(str(item)))

        return normalized

    def get_battle_action_for_encounter(self, pokemon_name, is_shiny):
        normalized_name = self.normalize_pokemon_text(pokemon_name)

        catch_shinies = self.config.get("catch_shinies", False)
        pause_list = self.normalize_config_pokemon_list(
            self.config.get("pause_pokemon", [])
        )
        catch_list = self.normalize_config_pokemon_list(
            self.config.get("catch_pokemon", [])
        )
        run_list = self.normalize_config_pokemon_list(
            self.config.get("run_from_pokemon", [])
        )

        if is_shiny and catch_shinies:
            return "catch"

        if normalized_name in pause_list:
            return "pause"

        if normalized_name in catch_list:
            return "catch"

        if normalized_name in run_list:
            return "run"

        return "normal"

    def get_custom_move_for_encounter(self):
        if not self.current_encounter_name or self.current_encounter_name == "-":
            return "1"

        normalized_name = self.normalize_pokemon_text(self.current_encounter_name)
        moves_config = self.config.get("pokemon_moves", {})

        normalized_moves = {
            self.normalize_pokemon_text(str(k)): str(v)
            for k, v in moves_config.items()
        }

        if normalized_name in normalized_moves:
            selected_move = normalized_moves[normalized_name]
            return selected_move
        return "1"

    def read_encounter_pokemon_async(self):
        if self.pokemon_ocr_running:
            return

        self.pokemon_ocr_running = True

        def worker():
            try:
                pokemon_name, is_shiny, _ = self.read_encounter_pokemon()
                self.current_battle_action = self.get_battle_action_for_encounter(
                    pokemon_name,
                    is_shiny
                )

                print("[OCR] Battle action:", self.current_battle_action)

            finally:
                self.pokemon_ocr_running = False

        threading.Thread(target=worker, daemon=True).start()

    def run_from_current_encounter(self):
        print("[Battle] Running from configured Pokemon.")
        self.stop_moving()
        time.sleep(random.uniform(0.15, 0.45))
        pyautogui.press("4")
        time.sleep(1.0)

    def catch_current_encounter(self):
        print("[Battle] Catching configured Pokemon.")

        self.stop_moving()

        battle_start_time = time.time()

        while self.running and self.check_for_encounter():
            pyautogui.press("2")
            time.sleep(random.uniform(0.12, 0.35))

            pyautogui.press("3")
            time.sleep(5.0 + random.uniform(0.0, 0.35))

            if time.time() - battle_start_time > 120:
                print("[Battle] Catch timeout reached.")
                break

        self.last_encounter_time = time.time()

    def pause_on_current_encounter(self):
        print("[Battle] Paused on configured Pokemon.")
        self.stop_moving()
        self.battle_paused = True
        self.paused_for_pokemon = True
        self.last_encounter_time = time.time()
        notifier.send_dm(
            self.config.get("discord_user_id"),
            f"Paused on {self.current_encounter_name}."
        )

    def stop_moving(self):
        if self.last_direction:
            pyautogui.keyUp(self.last_direction)
            self.last_direction = None

    def stop_bot(self, reason="Stopped"):
        print(f"\n[!] {reason}")
        self.stop_reason = reason
        self.stop_moving()
        self.paused_for_pokemon = False
        self.running = False

    def record_restart(self):
        self.session_stats["restarts"] += 1

    def format_runtime(self):
        total_seconds = int(time.time() - self.start_time)
        hours = total_seconds // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if hours > 0:
            return f"{hours}h {minutes}m"

        if minutes > 0:
            return f"{minutes}m {seconds}s"

        return f"{seconds}s"

    def get_session_summary(self):
        return (
            "Last Session\n"
            "━━━━━━━━━━\n"
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

        img = ImageGrab.grab(bbox=bbox, all_screens=True)
        return cv2.cvtColor(np.array(img), cv2.COLOR_RGB2GRAY)

    def check_auto_stop(self):
        auto_stop_minutes = self.config.get("auto_stop_minutes", 0)

        if auto_stop_minutes and auto_stop_minutes > 0:
            if time.time() - self.start_time >= auto_stop_minutes * 60:
                self.stop_bot("Auto stop time reached.")
                return True

        return False

    def should_skip_no_encounter_timeout(self):
        return (
            self.in_break
            or self.in_combat
            or self.reconnecting
            or self.loading_after_restart
        )

    def check_for_encounter(self):
        try:
            if self.enc_tpl is None:
                return False

            gray = self.grab_gray(ENCOUNTER_BOX)
            res = cv2.matchTemplate(gray, self.enc_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            return max_val > 0.85

        except Exception:
            return False

    def check_elite_fast(self):
        try:
            if self.elite_tpl is None:
                return False

            gray = self.grab_gray(ELITE_BOX)
            res = cv2.matchTemplate(gray, self.elite_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            print("Elite match:", round(max_val, 3))

            return max_val > 0.72

        except Exception:
            return False

    def check_special_popup_fast(self):
        try:
            if self.popup_x_tpl is None:
                return False

            gray = self.grab_gray(POPUP_X_SEARCH_BOX)

            res = cv2.matchTemplate(
                gray,
                self.popup_x_tpl,
                cv2.TM_CCOEFF_NORMED
            )

            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > 0.75:
                print("[!] Popup X detected. Closing popup.")

                self.stop_moving()

                x = self.win.left + POPUP_X_SEARCH_BOX[0] + max_loc[0] + self.popup_x_tpl.shape[1] // 2
                y = self.win.top + POPUP_X_SEARCH_BOX[1] + max_loc[1] + self.popup_x_tpl.shape[0] // 2

                pyautogui.click(x, y)

                time.sleep(0.4)

                return True

            return False

        except Exception:
            return False

    def check_request_decline(self):
        try:
            if not self.config.get("auto_decline_requests", False):
                return False

            if self.request_x_tpl is None:
                return False

            gray = self.grab_gray(REQUEST_X_BOX)

            res = cv2.matchTemplate(
                gray,
                self.request_x_tpl,
                cv2.TM_CCOEFF_NORMED
            )

            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val > 0.75:
                print("[!] Request detected. Waiting before declining...")

                self.stop_moving()
                time.sleep(random.uniform(2, 5))

                x = self.win.left + REQUEST_X_BOX[0] + max_loc[0] + self.request_x_tpl.shape[1] // 2
                y = self.win.top + REQUEST_X_BOX[1] + max_loc[1] + self.request_x_tpl.shape[0] // 2

                pyautogui.click(x, y)

                notifier.send_dm(self.config.get("discord_user_id"), "Request detected.")
                self.session_stats["requests_declined"] += 1
                print("[*] Request declined.")
                return True

            return False

        except Exception:
            return False

    def check_learn_move(self):
        try:
            if self.learn_move_tpl is None:
                return False

            gray = self.grab_gray(LEARN_MOVE_BOX)

            res = cv2.matchTemplate(
                gray,
                self.learn_move_tpl,
                cv2.TM_CCOEFF_NORMED
            )

            _, max_val, _, _ = cv2.minMaxLoc(res)

            if max_val > 0.80:
                print("[!] Learn move popup detected. Replacing 2nd move.")

                self.stop_moving()

                time.sleep(random.uniform(1.0, 2.0))

                pyautogui.click(
                    self.win.left + FORGET_MOVE_2_POS[0],
                    self.win.top + FORGET_MOVE_2_POS[1]
                )

                time.sleep(1.0)

                return True

            return False

        except Exception:
            return False

    def check_evolution(self):
        try:
            if self.evolve_yes_tpl is None:
                return False

            gray = self.grab_gray(EVOLVE_YES_BOX)

            res = cv2.matchTemplate(
                gray,
                self.evolve_yes_tpl,
                cv2.TM_CCOEFF_NORMED
            )

            _, max_val, _, _ = cv2.minMaxLoc(res)

            if max_val > 0.80:
                print("[!] Evolution popup detected. Clicking YES.")

                self.stop_moving()

                time.sleep(random.uniform(1.0, 2.0))

                pyautogui.click(
                    self.win.left + EVOLVE_YES_POS[0],
                    self.win.top + EVOLVE_YES_POS[1]
                )

                time.sleep(1.0)

                return True

            return False

        except Exception:
            return False

    def click_game_center(self):
        try:
            pyautogui.click(
                self.win.left + 512,
                self.win.top + 384
            )

            time.sleep(0.3)

        except Exception:
            pass

    def find_template_fullscreen_center(self, template, threshold=0.75):
        try:
            if template is None:
                return None

            bbox = (
                self.win.left,
                self.win.top,
                self.win.left + 1024,
                self.win.top + 768
            )

            screenshot = ImageGrab.grab(bbox=bbox, all_screens=True)
            gray = cv2.cvtColor(
                np.array(screenshot),
                cv2.COLOR_RGB2GRAY
            )

            res = cv2.matchTemplate(
                gray,
                template,
                cv2.TM_CCOEFF_NORMED
            )

            _, max_val, _, max_loc = cv2.minMaxLoc(res)

            if max_val < threshold:
                return None

            h, w = template.shape

            return (
                self.win.left + max_loc[0] + w // 2,
                self.win.top + max_loc[1] + h // 2
            )

        except Exception:
            return None

    def open_and_drag_online_list(self):
        try:
            if not self.config.get("notify_anubisius", True):
                return False

            if self.online_tpl is None:
                return False

            self.stop_moving()

            print("[*] Opening online player list.")

            # Window-relative game-screen point
            pyautogui.click(
                self.win.left + PLAYER_LIST_CLICK_POS[0],
                self.win.top + PLAYER_LIST_CLICK_POS[1]
            )

            time.sleep(0.8)

            found = self.find_template_fullscreen_center(
                self.online_tpl,
                threshold=0.75
            )

            if not found:
                print("[!] Online list title not found.")
                self.online_list_ready = False
                return False

            pyautogui.moveTo(found[0], found[1], duration=0.15)
            pyautogui.mouseDown()

            # Window-relative top-right slam point
            pyautogui.moveTo(
                self.win.left + PLAYER_LIST_DRAG_END[0],
                self.win.top + PLAYER_LIST_DRAG_END[1],
                duration=0.55
            )

            pyautogui.mouseUp()

            time.sleep(0.5)

            self.online_list_ready = True
            self.last_anubisius_check = 0

            print("[*] Online player list ready.")

            return True

        except Exception as e:
            print("[!] Online list setup failed:", e)
            self.online_list_ready = False
            return False

    def detect_anubisius(self):
        try:
            if self.anubisius_tpl is None:
                return False

            gray = self.grab_gray(ANUBISIUS_SEARCH_BOX)

            res = cv2.matchTemplate(
                gray,
                self.anubisius_tpl,
                cv2.TM_CCOEFF_NORMED
            )

            _, max_val, _, _ = cv2.minMaxLoc(res)

            print("Anubisius match:", round(max_val, 3))

            return max_val > 0.75

        except Exception:
            return False

    def check_anubisius_online(self):
        try:
            if (
                self.reconnecting
                or self.loading_after_restart
                or self.in_combat
                or self.in_break
            ):
                return self.paused_for_anubisius

            if not self.config.get("notify_anubisius", True):
                return False

            now = time.time()

            if self.waiting_to_reopen_anubisius_list:
                if now < self.anubisius_reopen_time:
                    return self.paused_for_anubisius

                self.waiting_to_reopen_anubisius_list = False
                self.open_and_drag_online_list()
                return self.paused_for_anubisius

            if now - self.last_anubisius_check < ANUBISIUS_CHECK_INTERVAL:
                return self.paused_for_anubisius

            self.last_anubisius_check = now

            if not self.online_list_ready:
                self.open_and_drag_online_list()
                return self.paused_for_anubisius

            is_online = self.detect_anubisius()
            pause_enabled = self.config.get(
                "pause_when_anubisius_online",
                False
            )

            if is_online:
                if not self.anubisius_notified:
                    notifier.send_dm(
                        self.config.get("discord_user_id"),
                        "Anubisius is online."
                    )
                    self.anubisius_notified = True

                if pause_enabled:
                    if not self.paused_for_anubisius:
                        self.stop_moving()
                        self.session_stats["anubisius_pauses"] += 1
                        print("[!] Anubisius is online. Bot paused.")

                    self.paused_for_anubisius = True
                    self.last_encounter_time = time.time()
                    return True

                return False

            if self.paused_for_anubisius:
                print("[*] Anubisius is gone. Resuming bot.")

            self.paused_for_anubisius = False

            if self.find_template_fullscreen_center(self.online_tpl, threshold=0.75) is None:
                print("[!] Online list appears closed. Reopening.")
                self.online_list_ready = False
                self.open_and_drag_online_list()

            return False

        except Exception:
            return self.paused_for_anubisius

    def schedule_anubisius_reopen_after_restart(self):
        if self.config.get("notify_anubisius", True):
            self.online_list_ready = False
            self.waiting_to_reopen_anubisius_list = True
            self.anubisius_reopen_time = (
                time.time()
                + ANUBISIUS_REOPEN_DELAY_AFTER_RESTART
            )

    def check_connect_button(self):
        try:
            if self.connect_tpl is None:
                return False

            gray = self.grab_gray(CONNECT_BUTTON_BOX)
            res = cv2.matchTemplate(gray, self.connect_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

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

                center_x = self.win.left + (
                    CONNECT_BUTTON_BOX[0] + CONNECT_BUTTON_BOX[2]
                ) // 2
                center_y = self.win.top + (
                    CONNECT_BUTTON_BOX[1] + CONNECT_BUTTON_BOX[3]
                ) // 2

                pyautogui.click(center_x, center_y)

                self.last_connect_click = now

            self.last_encounter_time = time.time()
            return True

        if self.reconnecting:
            print("[*] Reconnect screen gone. Waiting before bicycle check.")

            self.reconnecting = False
            self.loading_after_restart = True
            self.bike_retry_count = 0
            self.bike_checked_after_reconnect = False
            self.last_bike_check_after_reconnect = time.time()
            self.next_bike_retry_time = time.time() + 7
            self.last_encounter_time = time.time()
            return True

        if self.loading_after_restart:
            if not self.bike_checked_after_reconnect:
                if now >= self.next_bike_retry_time:
                    self.bike_retry_count += 1

                    print(
                        f"[*] Checking bicycle after reconnect/loading "
                        f"({self.bike_retry_count}/{self.max_bike_retries})."
                    )

                    time.sleep(random.uniform(0.0, 1.0))

                    bike_ok = self.check_bicycle()
                    self.last_encounter_time = time.time()

                    if bike_ok:
                        self.bike_checked_after_reconnect = True
                        self.loading_after_restart = False
                        print("[Bike] Post-reconnect bicycle confirmed.")
                        return True

                    if self.bike_retry_count >= self.max_bike_retries:
                        self.bike_checked_after_reconnect = True
                        self.loading_after_restart = False
                        print("[Bike] Max bike retries reached. Continuing anyway.")
                        return True

                    self.next_bike_retry_time = time.time() + random.uniform(3.5, 5.5)

                return True

        return False

    def check_disconnect_fast(self):
        try:
            now = time.time()

            if now - self.last_restart_time < self.restart_cooldown:
                return False

            if now - self.last_disconnect_check < self.disconnect_check_interval:
                return False

            self.last_disconnect_check = now

            if self.disconnect_tpl is None:
                return False

            gray = self.grab_gray(DISCONNECT_BOX)
            res = cv2.matchTemplate(gray, self.disconnect_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            print("Disconnect match:", round(max_val, 3))

            if max_val > 0.75:
                self.disconnect_confirm_count += 1
            else:
                self.disconnect_confirm_count = 0

            if self.disconnect_confirm_count >= 2:
                self.disconnect_confirm_count = 0
                return True

            return False

        except Exception:
            return False

    def restart_after_disconnect(self):
        self.record_restart()
        notifier.send_dm(self.config.get("discord_user_id"), "Bot has been restarted.")
        print("[!] Disconnect confirmed. Restarting game.")

        self.stop_moving()

        self.reconnecting = True
        self.loading_after_restart = True
        self.in_combat = False

        self.last_restart_time = time.time()

        self.win = launch_and_setup_game(
            self.config["game_path"],
            force_restart=True,
            selected_monitor=self.config.get("selected_monitor", 1)
        )

        if not self.win:
            print("[!] Restart failed to find window. Retrying once.")
            time.sleep(3 + random.uniform(0.0, 3.0))

            self.win = launch_and_setup_game(
                self.config["game_path"],
                force_restart=True,
                selected_monitor=self.config.get("selected_monitor", 1)
            )

        self.click_game_center()

        self.schedule_anubisius_reopen_after_restart()

        self.last_encounter_time = time.time()
        self.last_connect_click = 0
        self.last_connect_check = 0
        self.last_disconnect_check = time.time()
        self.disconnect_confirm_count = 0
        self.bike_checked_after_reconnect = False
        self.bike_retry_count = 0
        self.last_bike_check_after_reconnect = time.time()
        self.next_bike_retry_time = time.time() + 7

    def combat_sequence(self):
        self.stop_moving()

        self.session_stats["encounters"] += 1
        self.current_battle_action = "normal"
        self.battle_paused = False
        self.in_combat = True
        self.clear_current_encounter()

        print("\n[!] BATTLE START...", flush=True)

        # Wait for the screen to stabilize before scanning
        time.sleep(2.0 + random.uniform(0.15, 0.45))

        # Perform synchronous OCR check
        print("[OCR] Initiating Synchronous Scan...", flush=True)
        pokemon_name, is_shiny, _ = self.read_encounter_pokemon()
        self.current_battle_action = self.get_battle_action_for_encounter(
            pokemon_name,
            is_shiny
        )
        print(f"[OCR] Name detected: {pokemon_name} (Action: {self.current_battle_action})", flush=True)

        self.check_special_popup_fast()

        if self.current_battle_action == "pause":
            self.pause_on_current_encounter()
            self.in_combat = False
            return

        if self.current_battle_action == "catch":
            self.catch_current_encounter()
            self.in_combat = False
            return

        if self.current_battle_action == "run":
            self.run_from_current_encounter()
            self.last_encounter_time = time.time()
            self.in_combat = False
            return

        if self.check_elite_fast():
            print("[!] Elite detected. Running.", flush=True)
            time.sleep(random.uniform(0.15, 0.45))
            pyautogui.press("4")
            time.sleep(1.0)
            self.last_encounter_time = time.time()
            self.in_combat = False
            return

        # Fetch configured custom move
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

            if custom_move == "1":
                pyautogui.press("1")
                time.sleep(attack_interval + random.uniform(0.0, 0.20))
            else:
                pyautogui.press("1")
                time.sleep(0.35 + random.uniform(0.05, 0.15))
                pyautogui.press(custom_move)
                time.sleep(attack_interval + random.uniform(0.05, 0.20))

            if time.time() - battle_start_time > 70:
                print("[!] Combat timeout reached.", flush=True)
                break

        self.last_encounter_time = time.time()
        self.in_combat = False
        print(">>> Battle finished.", flush=True)

    def scan_grass_grid(self):
        try:
            if self.grass_tpl is None:
                return []

            bbox = (
                self.win.left + PLAY_AREA[0],
                self.win.top + PLAY_AREA[1],
                self.win.left + PLAY_AREA[2],
                self.win.top + PLAY_AREA[3]
            )

            screen = np.array(ImageGrab.grab(bbox=bbox, all_screens=True))
            gray_screen = cv2.cvtColor(screen, cv2.COLOR_RGB2GRAY)

            res = cv2.matchTemplate(gray_screen, self.grass_tpl, cv2.TM_CCOEFF_NORMED)
            loc = np.where(res >= 0.8)

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
        new_dir = random.choice(["a", "d"])

        if new_dir != self.last_direction:
            self.stop_moving()

            pyautogui.keyDown(new_dir)

            self.last_direction = new_dir

        time.sleep(random.uniform(0.12, 0.25))

    def move_up_down(self):
        new_dir = random.choice(["w", "s"])

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
            else random.choice(["w", "a", "s", "d"])
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

        if (
            self.config.get("enable_breaks")
            and now >= self.next_break_time
        ):
            self.in_break = True

            self.stop_moving()

            if self.config.get("close_on_break"):
                os.system(
                    f'taskkill /f /im "{os.path.basename(self.config["game_path"])}" >nul 2>&1'
                )

            break_duration = self.config.get("break_duration", 10)

            print(f"[*] Taking break for {break_duration} minutes...")

            time.sleep(break_duration * 60)

            base_interval = self.config.get("break_interval", 30)

            self.next_break_time = (
                time.time()
                + (random.randint(base_interval - 5, base_interval + 5) * 60)
            )

            self.win = launch_and_setup_game(
                self.config["game_path"],
                force_restart=True,
                selected_monitor=self.config.get("selected_monitor", 1)
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

        mode = self.config.get("mode", "grass_detection")

        if mode == "left_right":
            self.move_left_right()

        elif mode == "up_down":
            self.move_up_down()

        else:
            self.move_grass_detection()

        if self.check_for_encounter():
            self.combat_sequence()

    def is_bicycle_equipped(self):
        try:
            if self.bike_tpl is None:
                return False

            bbox = (
                self.win.left + BIKE_BOX[0],
                self.win.top + BIKE_BOX[1],
                self.win.left + BIKE_BOX[2],
                self.win.top + BIKE_BOX[3]
            )

            cap = ImageGrab.grab(bbox=bbox, all_screens=True)
            gray = cv2.cvtColor(np.array(cap), cv2.COLOR_RGB2GRAY)

            res = cv2.matchTemplate(gray, self.bike_tpl, cv2.TM_CCOEFF_NORMED)
            _, max_val, _, _ = cv2.minMaxLoc(res)

            print("Bike match:", round(max_val, 3))

            return max_val >= 0.78

        except Exception as e:
            print("[Bike] Bike check failed:", e)
            return False

    def check_bicycle(self):
        self.stop_moving()
        self.click_game_center()

        time.sleep(0.5)

        try:
            pyautogui.press("s")
            time.sleep(0.35)

            if self.is_bicycle_equipped():
                print("[Bike] Bicycle already equipped.")
                return True

            print("[Bike] Bicycle not detected. Pressing B.")
            pyautogui.press("b")
            time.sleep(0.9)

            if self.is_bicycle_equipped():
                print("[Bike] Bicycle equipped successfully.")
                return True

            print("[Bike] Bicycle still not detected after B.")
            return False

        except Exception as e:
            print("[Bike] check_bicycle error:", e)
            return False

def position_and_resize_game_window(win, selected_monitor=1):
    return position_and_resize_window(win, selected_monitor, width=1024, height=768)

def launch_and_setup_game(game_path, force_restart=False, selected_monitor=1):
    if force_restart:
        os.system(
            f'taskkill /f /im "{os.path.basename(game_path)}" >nul 2>&1'
        )

        time.sleep(2 + random.uniform(0.0, 3.0))

    subprocess.Popen(game_path)

    win = None

    for _ in range(30):
        wins = gw.getWindowsWithTitle(TARGET_WINDOW_TITLE)

        if wins:
            win = wins[0]
            break

        time.sleep(1)

    if win:
        position_and_resize_game_window(win, selected_monitor)

        time.sleep(5 + random.uniform(0.0, 3.0))

        pyautogui.click(
            win.left + 550,
            win.top + 580
        )

        time.sleep(10 + random.uniform(0.0, 5.0))

        pyautogui.click(
            win.left + 512,
            win.top + 384
        )

        time.sleep(0.3)

    return win