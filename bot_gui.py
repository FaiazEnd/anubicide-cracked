import json
import os
import sys
import threading
import time
import webbrowser
import urllib.request
import urllib.error
import tempfile
import hashlib
import subprocess
import re
from functools import wraps
from datetime import datetime, timezone

import customtkinter as ctk
from tkinter import filedialog
import pygetwindow as gw
import pyautogui
try:
    import keyboard
except ImportError:
    keyboard = None
from PIL import Image

try:
    import httpx
    from httpx import TransportError
except ImportError:
    TransportError = Exception

try:
    from supabase import create_client, ClientOptions
    from supabase_auth.errors import AuthApiError, AuthInvalidJwtError, AuthRetryableError
except ImportError:
    create_client = None
    ClientOptions = None
    AuthApiError = Exception
    AuthInvalidJwtError = Exception
    AuthRetryableError = Exception

import bot_core

APP_VERSION = '2.1.3'
UPDATE_REPO = 'LowkeyLabib/Anubicide-Releases'
UPDATE_API = f'https://api.github.com/repos/{UPDATE_REPO}/releases/latest'
UPDATE_EXE_ASSET = 'Anubicide.exe'
UPDATE_HASH_ASSET = 'Anubicide.exe.sha256'
UPDATE_USER_AGENT = f'Anubicide/{APP_VERSION}'


def app_path(relative_path):
    # Returns path relative to executable or current working directory
    try:
        base = os.path.dirname(os.path.abspath(sys.argv[0]))
    except Exception:
        base = os.path.abspath(".")
    return os.path.join(base, relative_path)


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


CONFIG_FILE = app_path('config.json')
AUTH_SESSION_FILE = app_path('auth_session.json')
LOGO_FILE = resource_path('anubicide_logo.png')
ICON_FILE = resource_path('anubicide_logo.ico')

# Color palette (monochrome dark)
BG = '#080808'
FIELD = '#171717'
BORDER = '#444444'
WHITE = '#F4F4F4'
MUTED = '#8A8A8A'
HOVER = '#303030'


def load_logo(size=(44, 44)):
    if os.path.exists(LOGO_FILE):
        try:
            pil_img = Image.open(LOGO_FILE)
            return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=size)
        except Exception as e:
            print(f"[!] Logo load error: {e}")
    return None


def apply_window_icon(window):
    if os.path.exists(ICON_FILE):
        try:
            window.iconbitmap(ICON_FILE)
        except Exception:
            try:
                window.after(200, lambda: window.iconbitmap(ICON_FILE))
            except Exception:
                pass


CURRENT_AUTH = {
    'user_id': 'local_user',
    'expires_at': datetime(2026, 10, 22, 23, 59, 59, tzinfo=timezone.utc),
    'email': 'user@anubicide.local'
}

_auth_lock = threading.Lock()
_pending_auth_session = None


def serialized_auth(function):
    @wraps(function)
    def guarded(*args, **kwargs):
        with _auth_lock:
            return function(*args, **kwargs)
    return guarded


def save_auth_session(access_token, refresh_token, email=None):
    session_data = {
        'access_token': access_token,
        'refresh_token': refresh_token,
        'email': email or ''
    }
    try:
        with open(AUTH_SESSION_FILE, 'w', encoding='utf-8') as f:
            json.dump(session_data, f, indent=2)
    except Exception as e:
        print(f"[!] Error saving auth session: {e}")


def load_auth_session():
    if not os.path.exists(AUTH_SESSION_FILE):
        return None
    try:
        with open(AUTH_SESSION_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def clear_auth_session():
    if os.path.exists(AUTH_SESSION_FILE):
        try:
            os.remove(AUTH_SESSION_FILE)
        except Exception:
            pass


def auth_error_kind(error):
    msg = str(error).lower()
    if 'invalid login credentials' in msg or 'invalid credentials' in msg:
        return 'invalid_credentials'
    if 'network' in msg or 'timeout' in msg or 'connection' in msg:
        return 'network'
    return 'unknown'


def friendly_auth_error(error):
    kind = auth_error_kind(error)
    if kind == 'invalid_credentials':
        return "Invalid email or password."
    if kind == 'network':
        return "Network connection error. Check your internet."
    return f"Authentication error: {error}"


def saved_auth_error(error):
    return f"Failed to restore saved session: {error}"


SUPABASE_URL = 'https://dlavzkpollbmkaewggqz.supabase.co'
SUPABASE_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImRsYXZ6a3BvbGxibWthZXdnZ3F6Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODgxMDg5MTIsImV4cCI6MjEwMzY4NDkxMn0.grpxM5jce1etBV5pEhfHfj7cimWpYeC6BcXSi93VwT0'


def parse_subscription_expiry(value):
    if not value:
        return None
    try:
        if isinstance(value, str):
            dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
            return dt
    except Exception:
        pass
    return None


def check_subscription_for_client(supabase, user):
    if not user:
        return False, "Invalid login.", None
    try:
        result = supabase.table('subscriptions').select('user_id, active, expires_at').eq('user_id', user.id).single().execute()
        sub = result.data
        if not sub:
            return False, "No subscription found for this account.", None
        if not bool(sub.get('active')):
            return False, "Subscription is disabled.", None

        expires_at = parse_subscription_expiry(sub.get('expires_at'))
        if expires_at and expires_at < datetime.now(timezone.utc):
            return False, f"Subscription expired on {expires_at.strftime('%Y-%m-%d')}.", expires_at
        return True, "Subscription active.", expires_at
    except Exception as e:
        return False, f"Subscription check failed: {e}", None


@serialized_auth
def verify_login_and_subscription(email, password, remember=True):
    if not create_client:
        return True, "Offline mode.", None
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        auth_resp = client.auth.sign_in_with_password({'email': email, 'password': password})
        if not auth_resp.user or not auth_resp.session:
            return False, "Login failed.", None

        ok, msg, expires_at = check_subscription_for_client(client, auth_resp.user)
        if not ok:
            return False, msg, None

        if remember:
            save_auth_session(auth_resp.session.access_token, auth_resp.session.refresh_token, email)

        CURRENT_AUTH['user_id'] = auth_resp.user.id
        CURRENT_AUTH['expires_at'] = expires_at
        CURRENT_AUTH['email'] = email
        return True, "Login successful.", expires_at
    except Exception as e:
        return False, friendly_auth_error(e), None


@serialized_auth
def verify_saved_session():
    saved = load_auth_session()
    if not saved or not saved.get('refresh_token'):
        return False, "No saved session."
    if not create_client:
        return True, "Offline mode."
    try:
        client = create_client(SUPABASE_URL, SUPABASE_KEY)
        auth_resp = client.auth.set_session(saved['access_token'], saved['refresh_token'])
        if not auth_resp.user or not auth_resp.session:
            return False, "Session expired."

        ok, msg, expires_at = check_subscription_for_client(client, auth_resp.user)
        if not ok:
            return False, msg

        save_auth_session(auth_resp.session.access_token, auth_resp.session.refresh_token, saved.get('email'))
        CURRENT_AUTH['user_id'] = auth_resp.user.id
        CURRENT_AUTH['expires_at'] = expires_at
        CURRENT_AUTH['email'] = saved.get('email')
        return True, "Session restored."
    except Exception as e:
        return False, saved_auth_error(e)


def version_tuple(version_str):
    parts = []
    for part in re.split(r'[-+.]', str(version_str).lstrip('v')):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(part)
    return tuple(parts)


def github_json(url, timeout=8):
    req = urllib.request.Request(url, headers={'User-Agent': UPDATE_USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode('utf-8'))


def check_for_update():
    try:
        data = github_json(UPDATE_API)
        latest_tag = data.get('tag_name', '').lstrip('v')
        if not latest_tag:
            return None
        if version_tuple(latest_tag) > version_tuple(APP_VERSION):
            assets = data.get('assets', [])
            exe_url = None
            hash_url = None
            for asset in assets:
                if asset.get('name') == UPDATE_EXE_ASSET:
                    exe_url = asset.get('browser_download_url')
                elif asset.get('name') == UPDATE_HASH_ASSET:
                    hash_url = asset.get('browser_download_url')
            return {
                'version': latest_tag,
                'exe_url': exe_url,
                'hash_url': hash_url,
                'body': data.get('body', '')
            }
    except Exception as e:
        print(f"[!] Update check error: {e}")
    return None


class LoginWindow(ctk.CTk):
    def __init__(self, on_success_callback=None):
        super().__init__()
        self.on_success = on_success_callback
        self.title("Anubicide - Login")
        self.geometry("380x520")
        self.resizable(False, False)
        self.configure(fg_color=BG)
        apply_window_icon(self)

        self.logo_img = load_logo((64, 64))
        if self.logo_img:
            self.logo_lbl = ctk.CTkLabel(self, text="", image=self.logo_img)
            self.logo_lbl.pack(pady=(25, 5))

        self.title_lbl = ctk.CTkLabel(self, text="Anubicide", font=("Roboto", 22, "bold"), text_color=WHITE)
        self.title_lbl.pack(pady=(0, 2))

        self.ver_lbl = ctk.CTkLabel(self, text=f"v{APP_VERSION}", font=("Roboto", 11), text_color=MUTED)
        self.ver_lbl.pack(pady=(0, 15))

        self.email_entry = ctk.CTkEntry(
            self, placeholder_text="Email", width=280, height=36,
            fg_color=FIELD, border_color=BORDER, text_color=WHITE
        )
        self.email_entry.pack(pady=8)

        self.pass_entry = ctk.CTkEntry(
            self, placeholder_text="Password", show="*", width=280, height=36,
            fg_color=FIELD, border_color=BORDER, text_color=WHITE
        )
        self.pass_entry.pack(pady=8)

        self.remember_var = ctk.BooleanVar(value=True)
        self.remember_cb = ctk.CTkCheckBox(
            self, text="Remember Me", variable=self.remember_var,
            font=("Roboto", 11), text_color=MUTED, fg_color=BORDER, hover_color=HOVER
        )
        self.remember_cb.pack(pady=(4, 15))

        self.status_lbl = ctk.CTkLabel(self, text="", font=("Roboto", 11), text_color=MUTED, wraplength=300)
        self.status_lbl.pack(pady=(0, 8))

        self.login_btn = ctk.CTkButton(
            self, text="Sign In", width=280, height=36,
            fg_color=WHITE, text_color=BG, hover_color="#D0D0D0", font=("Roboto", 12, "bold"),
            command=self.start_login
        )
        self.login_btn.pack(pady=6)

        # Direct Local / Offline launch button for standalone convenience
        self.offline_btn = ctk.CTkButton(
            self, text="Launch Local / Offline Mode", width=280, height=32,
            fg_color=FIELD, text_color=MUTED, hover_color=HOVER, border_color=BORDER, border_width=1,
            font=("Roboto", 11), command=self.launch_offline
        )
        self.offline_btn.pack(pady=6)

        # Try automatic saved session
        self.after(300, self.check_saved_session)

    def check_saved_session(self):
        saved = load_auth_session()
        if saved:
            self.status_lbl.configure(text="Checking saved session...", text_color="yellow")
            threading.Thread(target=self._saved_worker, daemon=True).start()

    def _saved_worker(self):
        ok, msg = verify_saved_session()
        self.after(0, lambda: self._finish_saved(ok, msg))

    def _finish_saved(self, ok, msg):
        if ok:
            self.destroy()
            if self.on_success:
                self.on_success()
            else:
                PokeBotGUI().mainloop()
        else:
            self.status_lbl.configure(text=msg, text_color="red")

    def start_login(self):
        email = self.email_entry.get().strip()
        pwd = self.pass_entry.get()
        if not email or not pwd:
            self.status_lbl.configure(text="Please fill in email and password.", text_color="red")
            return
        self.status_lbl.configure(text="Authenticating...", text_color="yellow")
        self.login_btn.configure(state="disabled")
        threading.Thread(target=self._login_worker, args=(email, pwd, self.remember_var.get()), daemon=True).start()

    def _login_worker(self, email, pwd, remember):
        ok, msg, _ = verify_login_and_subscription(email, pwd, remember)
        self.after(0, lambda: self._finish_login(ok, msg))

    def _finish_login(self, ok, msg):
        self.login_btn.configure(state="normal")
        if ok:
            self.destroy()
            if self.on_success:
                self.on_success()
            else:
                PokeBotGUI().mainloop()
        else:
            self.status_lbl.configure(text=msg, text_color="red")

    def launch_offline(self):
        CURRENT_AUTH['user_id'] = "local_user"
        CURRENT_AUTH['email'] = "local@offline"
        self.destroy()
        if self.on_success:
            self.on_success()
        else:
            PokeBotGUI().mainloop()


DEFAULT_CONFIG = {
    "game_path": "",
    "mode": "left_right",
    "break_interval": 30,
    "break_duration": 10,
    "enable_breaks": False,
    "close_on_break": False,
    "auto_decline_requests": False,
    "restart_on_no_encounter": True,
    "restart_no_encounter_minutes": 5,
    "discord_user_id": "",
    "discord_bot_token": "",
    "notify_anubisius": False,
    "pause_when_anubisius_online": False,
    "auto_stop_minutes": 0,
    "catch_shinies": True,
    "catch_pokemon": [],
    "run_from_pokemon": [],
    "pause_pokemon": [],
    "pokemon_moves": {},
    "selected_monitor": r"\\.\DISPLAY1"
}


class PokeBotGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title(f"Anubicide {APP_VERSION}")
        self.geometry("500x650")
        self.resizable(False, False)
        ctk.set_appearance_mode("dark")
        self.configure(fg_color=BG)
        apply_window_icon(self)

        self.bot = None
        self.is_running = False
        self.hotkey_handles = []

        # Header Frame
        self.header_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.header_frame.pack(pady=(6, 3))

        self.header_logo = load_logo((44, 44))
        if self.header_logo:
            self.header_logo_lbl = ctk.CTkLabel(self.header_frame, text="", image=self.header_logo)
            self.header_logo_lbl.pack(side="left", padx=(0, 8))

        self.label = ctk.CTkLabel(self.header_frame, text="Anubicide", font=("Roboto", 20, "bold"), text_color=WHITE)
        self.label.pack(side="left")

        # Game Path Row
        self.path_row = ctk.CTkFrame(self, fg_color="transparent")
        self.path_row.pack(pady=(3, 5))

        self.path_entry = ctk.CTkEntry(
            self.path_row,
            width=335,
            height=32,
            placeholder_text="Path to Poke Nexus.exe",
            fg_color=FIELD,
            border_color=BORDER,
            text_color=WHITE
        )
        self.path_entry.grid(row=0, column=0, padx=(0, 6))

        self.browse_btn = ctk.CTkButton(
            self.path_row,
            text="Browse",
            width=110,
            height=32,
            command=self.browse_path
        )
        self.browse_btn.grid(row=0, column=1)

        # Top Settings Buttons Row (Discord Settings, Battle Settings, About)
        self.top_settings_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.top_settings_frame.pack(pady=(2, 5))

        self.discord_settings_btn = ctk.CTkButton(
            self.top_settings_frame,
            text="Discord Settings",
            width=140,
            command=self.open_discord_settings
        )
        self.discord_settings_btn.grid(row=0, column=0, padx=5)

        self.battle_settings_btn = ctk.CTkButton(
            self.top_settings_frame,
            text="Battle Settings",
            width=140,
            command=self.open_battle_settings
        )
        self.battle_settings_btn.grid(row=0, column=1, padx=5)

        self.about_btn = ctk.CTkButton(
            self.top_settings_frame,
            text="About",
            width=140,
            command=self.open_about,
            fg_color="#202020",
            hover_color=HOVER,
            border_width=1,
            border_color=BORDER,
            text_color=WHITE
        )
        self.about_btn.grid(row=0, column=2, padx=5)

        # Movement Mode Centered
        self.mode_label = ctk.CTkLabel(self, text="Movement Mode", text_color=WHITE, font=("Roboto", 13))
        self.mode_label.pack(pady=(6, 0))

        self.mode_menu = ctk.CTkOptionMenu(
            self,
            values=['Grass Detection', 'Left-Right', 'Up-Down'],
            width=140
        )
        self.mode_menu.set('Left-Right')
        self.mode_menu.pack(pady=4)

        # Switch Frame 1: Enable Breaks & Close During Break
        self.switch_frame_1 = ctk.CTkFrame(self, fg_color="transparent")
        self.switch_frame_1.pack(pady=(5, 1))

        self.break_switch = ctk.CTkSwitch(self.switch_frame_1, text="Enable Breaks")
        self.break_switch.grid(row=0, column=0, padx=10, pady=3, sticky='w')
        self.break_switch.deselect()

        self.close_switch = ctk.CTkSwitch(self.switch_frame_1, text="Close During Break")
        self.close_switch.grid(row=0, column=1, padx=10, pady=3, sticky='w')
        self.close_switch.deselect()

        # Switch Frame 2: Auto Decline & Restart No Encounters
        self.switch_frame_2 = ctk.CTkFrame(self, fg_color="transparent")
        self.switch_frame_2.pack(pady=1)

        self.request_switch = ctk.CTkSwitch(self.switch_frame_2, text="Auto Decline")
        self.request_switch.grid(row=0, column=0, padx=10, pady=3, sticky='w')
        self.request_switch.deselect()

        self.restart_timeout_switch = ctk.CTkSwitch(self.switch_frame_2, text="Restart No Encounters")
        self.restart_timeout_switch.grid(row=0, column=1, padx=10, pady=3, sticky='w')
        self.restart_timeout_switch.select()

        # Switch Frame 3: Pause on Anubisius
        self.switch_frame_3 = ctk.CTkFrame(self, fg_color="transparent")
        self.switch_frame_3.pack(pady=1)

        self.pause_anubisius_switch = ctk.CTkSwitch(self.switch_frame_3, text="Pause on Anubisius")
        self.pause_anubisius_switch.grid(row=0, column=0, padx=10, pady=3, sticky='w')
        self.pause_anubisius_switch.deselect()

        # Settings Frame (Restart Timeout, Break Every, Break Duration)
        self.settings_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.settings_frame.pack(pady=(6, 1))

        self.restart_timeout_label = ctk.CTkLabel(self.settings_frame, text="Restart Timeout", text_color=WHITE, font=("Roboto", 12))
        self.restart_timeout_label.grid(row=0, column=0, padx=8, pady=(0, 2))

        self.restart_timeout_entry = ctk.CTkEntry(self.settings_frame, width=95, placeholder_text="5")
        self.restart_timeout_entry.insert(0, "5")
        self.restart_timeout_entry.grid(row=1, column=0, padx=8, pady=2)

        self.interval_label = ctk.CTkLabel(self.settings_frame, text="Break Every", text_color=WHITE, font=("Roboto", 12))
        self.interval_label.grid(row=0, column=1, padx=8, pady=(0, 2))

        self.interval_entry = ctk.CTkEntry(self.settings_frame, width=95, placeholder_text="30")
        self.interval_entry.insert(0, "30")
        self.interval_entry.grid(row=1, column=1, padx=8, pady=2)

        self.break_duration_label = ctk.CTkLabel(self.settings_frame, text="Break Duration", text_color=WHITE, font=("Roboto", 12))
        self.break_duration_label.grid(row=0, column=2, padx=8, pady=(0, 2))

        self.break_duration_entry = ctk.CTkEntry(self.settings_frame, width=95, placeholder_text="10")
        self.break_duration_entry.insert(0, "10")
        self.break_duration_entry.grid(row=1, column=2, padx=8, pady=2)

        # Stop Bot Frame (Stop Bot In & Target monitor)
        self.stop_bot_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.stop_bot_frame.pack(pady=(4, 1))

        self.stop_bot_label = ctk.CTkLabel(self.stop_bot_frame, text="Stop Bot In", text_color=WHITE, font=("Roboto", 12))
        self.stop_bot_label.grid(row=0, column=0, padx=(0, 8))

        self.stop_bot_minutes_entry = ctk.CTkEntry(self.stop_bot_frame, width=95, placeholder_text="0")
        self.stop_bot_minutes_entry.insert(0, "0")
        self.stop_bot_minutes_entry.grid(row=0, column=1)

        self.target_monitor_label = ctk.CTkLabel(self.stop_bot_frame, text="Target monitor", text_color=WHITE, font=("Roboto", 12))
        self.target_monitor_label.grid(row=0, column=2, padx=(12, 6))

        self.target_monitor_menu = ctk.CTkOptionMenu(
            self.stop_bot_frame,
            width=180,
            dynamic_resizing=False,
            values=["Monitor 1"],
            fg_color=FIELD,
            button_color=BORDER,
            button_hover_color=HOVER,
            text_color=WHITE
        )
        self.target_monitor_menu.grid(row=0, column=3)
        self.target_monitors = []
        self.refresh_target_monitors(reschedule=False)

        # Settings Hint
        self.settings_hint = ctk.CTkLabel(self, text="Times are in minutes", text_color=MUTED, font=("Roboto", 11))
        self.settings_hint.pack(pady=(0, 3))

        # Action Buttons (START BOT & STOP BOT side-by-side)
        self.button_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.button_frame.pack(pady=(10, 5))

        self.start_btn = ctk.CTkButton(
            self.button_frame,
            text="START BOT",
            fg_color=WHITE,
            hover_color="#D8D8D8",
            text_color="#080808",
            font=("Roboto", 12, "bold"),
            width=180,
            height=32,
            command=self.start_bot
        )
        self.start_btn.grid(row=0, column=0, padx=8)

        self.stop_btn = ctk.CTkButton(
            self.button_frame,
            text="STOP BOT",
            fg_color="#202020",
            hover_color=HOVER,
            border_width=1,
            border_color="#666666",
            text_color=WHITE,
            font=("Roboto", 12, "bold"),
            width=180,
            height=32,
            state="disabled",
            command=self.stop_bot
        )
        self.stop_btn.grid(row=0, column=1, padx=8)

        # Session & Hotkeys Frame
        self.session_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.session_frame.pack(pady=(3, 1))

        self.last_session_label = ctk.CTkLabel(
            self.session_frame,
            text="Last Session\n──────────\nRuntime: -\nEncounters: -\nRestarts: -\nRequests Declined: -\nAnubisius Pauses: -",
            text_color=MUTED,
            font=("Roboto", 12),
            justify="left"
        )
        self.last_session_label.grid(row=0, column=0, padx=(0, 55), sticky="n")

        self.hotkey_hint_label = ctk.CTkLabel(
            self.session_frame,
            text="Hotkeys\nPgUp  Start\nPgDn  Stop",
            text_color=MUTED,
            font=("Roboto", 11),
            justify="left"
        )
        self.hotkey_hint_label.grid(row=0, column=1, sticky="n")

        # Encounter Label
        self.encounter_label = ctk.CTkLabel(self, text="Encounter: -", text_color=MUTED, font=("Roboto", 12))
        self.encounter_label.pack(pady=(0, 2))

        # Subscription Label at the bottom
        self.subscription_label = ctk.CTkLabel(
            self,
            text=self.get_subscription_display_text(),
            text_color=MUTED,
            font=("Roboto", 11)
        )
        self.subscription_label.pack(side="bottom", pady=(0, 4))

        # Status Label directly above subscription
        self.status_label = ctk.CTkLabel(
            self,
            text="",
            text_color=MUTED,
            font=("Roboto", 12)
        )
        self.status_label.pack(side="bottom", pady=(0, 2))

        # Apply exact button and component styles
        for button in (self.browse_btn, self.discord_settings_btn, self.battle_settings_btn, self.about_btn):
            button.configure(fg_color="#202020", hover_color=HOVER, border_width=1, border_color=BORDER, text_color=WHITE)

        self.mode_menu.configure(
            fg_color="#202020",
            button_color="#202020",
            button_hover_color=HOVER,
            dropdown_fg_color="#151515",
            dropdown_hover_color=HOVER,
            text_color=WHITE
        )

        for switch in (self.break_switch, self.close_switch, self.request_switch, self.restart_timeout_switch, self.pause_anubisius_switch):
            switch.configure(progress_color=WHITE, button_color=WHITE, button_hover_color="#D8D8D8", text_color=WHITE)

        for entry in (self.restart_timeout_entry, self.interval_entry, self.break_duration_entry, self.stop_bot_minutes_entry):
            entry.configure(fg_color=FIELD, border_color=BORDER, text_color=WHITE)

        self.start_btn.configure(fg_color=WHITE, hover_color="#D8D8D8", text_color="#080808")
        self.stop_btn.configure(fg_color="#202020", hover_color=HOVER, border_width=1, border_color="#666666", text_color=WHITE)

        self.load_config()
        self.register_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.update_live_gui()

    def get_subscription_display_text(self):
        expires_at = CURRENT_AUTH.get('expires_at')
        if not expires_at:
            return "Subscription: -"
        try:
            local_expiry = expires_at.astimezone()
            return "Subscription: Active until " + local_expiry.strftime('%d %b %Y')
        except Exception:
            return "Subscription: Active until 22 Oct 2026"

    def register_hotkeys(self):
        if not keyboard:
            return
        try:
            h1 = keyboard.add_hotkey('page up', lambda: self.after(0, self.start_bot))
            h2 = keyboard.add_hotkey('page down', lambda: self.after(0, self.stop_bot))
            self.hotkey_handles.extend([h1, h2])
        except Exception as e:
            print(f"[!] Hotkey registration error: {e}")

    def unregister_hotkeys(self):
        if not keyboard:
            return
        try:
            keyboard.unhook_all_hotkeys()
        except Exception:
            pass

    def on_close(self):
        self.stop_bot()
        self.save_config()
        self.unregister_hotkeys()
        self.destroy()

    def ensure_config_file(self):
        if not os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                    json.dump(DEFAULT_CONFIG, f, indent=4)
            except Exception as e:
                print(f"[!] Error creating default config: {e}")

    def read_config(self):
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                    cfg = json.load(f)
                    merged = dict(DEFAULT_CONFIG)
                    merged.update(cfg)
                    return merged
            except Exception as e:
                print(f"[!] Error reading config: {e}")
        return dict(DEFAULT_CONFIG)

    def write_config(self, config):
        try:
            with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4)
        except Exception as e:
            print(f"[!] Error writing config: {e}")

    def get_int_entry(self, entry, default=0, min_val=None):
        try:
            val = int(entry.get().strip())
            if min_val is not None:
                return max(min_val, val)
            return val
        except Exception:
            return default

    def set_entry_value(self, entry, val):
        entry.delete(0, "end")
        entry.insert(0, str(val))

    def get_selected_mode(self):
        sel = self.mode_menu.get()
        if sel == 'Left-Right':
            return 'left_right'
        elif sel == 'Up-Down':
            return 'up_down'
        return 'grass_detection'

    def get_selected_monitor(self):
        label = self.target_monitor_menu.get()
        for monitor in self.target_monitors:
            if monitor['label'] == label:
                return monitor
        return self.target_monitors[0] if self.target_monitors else None

    def refresh_target_monitors(self, selected=None, reschedule=True):
        if self.is_running:
            if reschedule:
                self.after(3000, self.refresh_target_monitors)
            return

        choice = selected if selected is not None else (self.get_selected_monitor() if self.target_monitors else None)
        self.target_monitors = bot_core.get_monitors()
        monitor = bot_core.get_monitor(choice, self.target_monitors)
        self.target_monitor_menu.configure(values=[m['label'] for m in self.target_monitors])
        if monitor:
            self.target_monitor_menu.set(monitor['label'])
        elif self.target_monitors:
            self.target_monitor_menu.set(self.target_monitors[0]['label'])

        if reschedule:
            self.after(3000, self.refresh_target_monitors)

    def load_config(self):
        config = self.read_config()
        self.path_entry.delete(0, "end")
        self.path_entry.insert(0, config.get("game_path", ""))

        mode = config.get("mode", "left_right")
        if mode == "left_right":
            self.mode_menu.set("Left-Right")
        elif mode == "up_down":
            self.mode_menu.set("Up-Down")
        else:
            self.mode_menu.set("Grass Detection")

        self.set_entry_value(self.interval_entry, config.get("break_interval", 30))
        self.set_entry_value(self.break_duration_entry, config.get("break_duration", 10))

        if config.get("enable_breaks", False):
            self.break_switch.select()
        else:
            self.break_switch.deselect()

        if config.get("close_on_break", False):
            self.close_switch.select()
        else:
            self.close_switch.deselect()

        if config.get("auto_decline_requests", False):
            self.request_switch.select()
        else:
            self.request_switch.deselect()

        if config.get("restart_on_no_encounter", True):
            self.restart_timeout_switch.select()
        else:
            self.restart_timeout_switch.deselect()

        if config.get("pause_when_anubisius_online", False):
            self.pause_anubisius_switch.select()
        else:
            self.pause_anubisius_switch.deselect()

        self.set_entry_value(self.restart_timeout_entry, config.get("restart_no_encounter_minutes", 5))
        self.set_entry_value(self.stop_bot_minutes_entry, config.get("auto_stop_minutes", 0))

        self.refresh_target_monitors(selected=config.get("selected_monitor", 1), reschedule=False)

    def save_config(self):
        old_config = self.read_config()
        config = {
            "game_path": self.path_entry.get().strip(),
            "mode": self.get_selected_mode(),
            "break_interval": self.get_int_entry(self.interval_entry, 30, 1),
            "break_duration": self.get_int_entry(self.break_duration_entry, 10, 1),
            "enable_breaks": bool(self.break_switch.get()),
            "close_on_break": bool(self.close_switch.get()),
            "auto_decline_requests": bool(self.request_switch.get()),
            "restart_on_no_encounter": bool(self.restart_timeout_switch.get()),
            "restart_no_encounter_minutes": self.get_int_entry(self.restart_timeout_entry, 5, 1),
            "discord_user_id": old_config.get("discord_user_id", ""),
            "discord_bot_token": old_config.get("discord_bot_token", ""),
            "notify_anubisius": bool(self.pause_anubisius_switch.get() or old_config.get("discord_user_id")),
            "pause_when_anubisius_online": bool(self.pause_anubisius_switch.get()),
            "auto_stop_minutes": self.get_int_entry(self.stop_bot_minutes_entry, 0, 0),
            "selected_monitor": self.get_selected_monitor().get('device') if self.get_selected_monitor() else old_config.get("selected_monitor", 1),
            "catch_shinies": old_config.get("catch_shinies", True),
            "catch_pokemon": old_config.get("catch_pokemon", []),
            "run_from_pokemon": old_config.get("run_from_pokemon", []),
            "pause_pokemon": old_config.get("pause_pokemon", []),
            "pokemon_moves": old_config.get("pokemon_moves", {})
        }
        self.write_config(config)

    def browse_path(self):
        file = filedialog.askopenfilename(
            title="Select Poke Nexus.exe",
            filetypes=[("Executable", "*.exe"), ("All Files", "*.*")]
        )
        if file:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, file)
            self.save_config()

    def start_bot(self):
        if self.is_running:
            return
        path = self.path_entry.get().strip()
        if path and not os.path.exists(path):
            self.status_label.configure(text="Status: Error! Invalid Path", text_color="red")
            return
        self.save_config()
        self.is_running = True
        self.target_monitor_menu.configure(state="disabled")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        threading.Thread(target=self.bot_worker, daemon=True).start()

    def stop_bot(self):
        if not self.is_running:
            return
        self.is_running = False
        if self.bot:
            self.bot.stop_bot("User stopped")
        self.reset_ui()

    def reset_ui(self):
        self.target_monitor_menu.configure(state="normal")
        self.start_btn.configure(state="normal")
        self.stop_btn.configure(state="disabled")
        if not self.is_running:
            self.encounter_label.configure(text="Encounter: -")
            self.status_label.configure(text="Status: Stopped", text_color=MUTED)

    def bot_worker(self):
        error_name = None
        error_detail = ""
        try:
            self.run_bot_worker()
        except Exception as error:
            error_name = type(error).__name__
            error_detail = str(error)
            print(f"[!] Bot worker error: {error_name}: {error}")
            import traceback
            traceback.print_exc()
            try:
                with open(app_path("bot_error.log"), "a", encoding="utf-8") as f:
                    f.write(f"\n--- {datetime.now()} ---\n")
                    f.write(f"Error: {error_name}: {error_detail}\n")
                    traceback.print_exc(file=f)
            except Exception:
                pass
            if self.bot:
                try:
                    self.bot.stop_bot("Bot error")
                except Exception:
                    self.bot.running = False
        finally:
            self.after(0, lambda name=error_name, detail=error_detail: self.finish_bot_worker(name, detail))

    def finish_bot_worker(self, error_name=None, error_detail=""):
        self.is_running = False
        self.reset_ui()
        if error_name:
            msg = f"Status: Bot error ({error_name})"
            if error_detail and len(error_detail) < 45:
                msg += f": {error_detail}"
            self.status_label.configure(text=msg, text_color="red")

    def run_bot_worker(self):
        self.status_label.configure(text="Status: Checking for Game...", text_color="yellow")
        self.save_config()
        config_data = self.read_config()

        win = bot_core.find_game_window()
        if win:
            self.status_label.configure(text="Status: Found Active Window", text_color="cyan")
            try:
                bot_core.position_and_resize_game_window(win, config_data.get('selected_monitor', 1))
            except Exception as e:
                print(f"[!] Warning positioning window: {e}")
        else:
            self.status_label.configure(text="Status: Launching Game...", text_color="yellow")
            win = bot_core.launch_and_setup_game(
                config_data.get('game_path', ''),
                selected_monitor=config_data.get('selected_monitor', 1)
            )

        if not win or not self.is_running:
            raise RuntimeError("Game window not found")

        # Focus game window
        bot_core.force_activate_window(win)
        pyautogui.click(win.left + 512, win.top + 384)
        time.sleep(0.3)

        self.bot = bot_core.PokeBot(win, config_data)
        self.status_label.configure(text="Status: Checking Bicycle...", text_color="orange")
        self.bot.check_bicycle()
        time.sleep(0.3)
        self.bot.click_game_center()

        self.status_label.configure(text=f"Status: Bot Active ({self.mode_menu.get()})", text_color="green")

        while self.is_running and self.bot.running:
            self.bot.move()

        if self.bot:
            summary = self.bot.get_session_summary()
            self.after(0, lambda s=summary: self.last_session_label.configure(text=s))

        if not self.bot.running and self.is_running:
            self.status_label.configure(text="Status: Auto Stopped", text_color="orange")

    def update_live_gui(self):
        try:
            if self.bot and self.is_running:
                encounter_display = self.bot.get_current_encounter_display()
                self.encounter_label.configure(text=f"Encounter: {encounter_display}")
                if self.bot.in_combat:
                    self.status_label.configure(text=f"Status: In Combat ({encounter_display})", text_color="yellow")
                elif self.bot.reconnecting:
                    self.status_label.configure(text="Status: Reconnecting...", text_color="orange")
                elif self.bot.in_break:
                    self.status_label.configure(text="Status: On Break", text_color="cyan")
                elif self.bot.paused_for_anubisius:
                    self.status_label.configure(text="Status: Paused (Anubisius Online!)", text_color="red")
                elif self.bot.paused_for_pokemon:
                    self.status_label.configure(text=f"Status: Paused on Pokemon ({self.bot.current_encounter_name})", text_color="magenta")
                else:
                    self.status_label.configure(text=f"Status: Farming ({self.mode_menu.get()})", text_color="green")
        except Exception:
            pass
        self.after(200, self.update_live_gui)

    def open_discord_settings(self):
        cfg = self.read_config()
        popup = ctk.CTkToplevel(self)
        popup.title("Discord Settings")
        popup.geometry("390x230")
        popup.resizable(False, False)
        popup.configure(fg_color=BG)
        apply_window_icon(popup)
        popup.transient(self)
        popup.grab_set()

        ctk.CTkLabel(popup, text="Discord Notifier Configuration", font=("Roboto", 13, "bold"), text_color=WHITE).pack(pady=(14, 8))

        ctk.CTkLabel(popup, text="Discord User ID:", font=("Roboto", 11), text_color=MUTED).pack(anchor="w", padx=20, pady=(4, 1))
        user_id_entry = ctk.CTkEntry(popup, width=350, fg_color=FIELD, border_color=BORDER, text_color=WHITE)
        user_id_entry.insert(0, cfg.get("discord_user_id", ""))
        user_id_entry.pack(padx=20)

        ctk.CTkLabel(popup, text="Discord Bot Token:", font=("Roboto", 11), text_color=MUTED).pack(anchor="w", padx=20, pady=(6, 1))
        token_entry = ctk.CTkEntry(popup, width=350, show="*", fg_color=FIELD, border_color=BORDER, text_color=WHITE)
        token_entry.insert(0, cfg.get("discord_bot_token", ""))
        token_entry.pack(padx=20)

        def save_discord():
            c = self.read_config()
            c["discord_user_id"] = user_id_entry.get().strip()
            c["discord_bot_token"] = token_entry.get().strip()
            self.write_config(c)
            # Start Discord notifier if token provided
            if c["discord_bot_token"]:
                bot_core.notifier.start()
            popup.destroy()

        ctk.CTkButton(popup, text="Save Settings", fg_color=WHITE, text_color=BG, hover_color="#D0D0D0", font=("Roboto", 11, "bold"), command=save_discord).pack(pady=(15, 0))

    def open_about(self):
        popup = ctk.CTkToplevel(self)
        popup.title("About Anubicide")
        popup.geometry("360x380")
        popup.resizable(False, False)
        popup.configure(fg_color=BG)
        apply_window_icon(popup)
        popup.transient(self)
        popup.grab_set()

        logo = load_logo((50, 50))
        if logo:
            ctk.CTkLabel(popup, text="", image=logo).pack(pady=(20, 5))

        ctk.CTkLabel(popup, text="Anubicide", font=("Roboto", 18, "bold"), text_color=WHITE).pack()
        ctk.CTkLabel(popup, text=f"Version {APP_VERSION}", font=("Roboto", 11), text_color=MUTED).pack(pady=(2, 10))

        info_text = (
            "An advanced, automated automation suite\n"
            "for Poke Nexus with computer vision,\n"
            "OCR recognition, smart battle actions,\n"
            "and admin protection.\n\n"
            "Reconstructed cleanly with Python, CustomTkinter,\n"
            "OpenCV, and PyTesseract."
        )
        ctk.CTkLabel(popup, text=info_text, font=("Roboto", 11), text_color="#C0C0C0", justify="center").pack(padx=20, pady=10)

        ctk.CTkButton(
            popup, text="GitHub Releases", width=140, fg_color=FIELD, hover_color=HOVER, border_color=BORDER, border_width=1,
            command=lambda: webbrowser.open(f"https://github.com/{UPDATE_REPO}")
        ).pack(pady=6)

        ctk.CTkButton(popup, text="Close", width=140, fg_color=WHITE, text_color=BG, hover_color="#D0D0D0", command=popup.destroy).pack(pady=4)

    def open_battle_settings(self):
        working_config = self.read_config()
        all_pokemon = bot_core.PokeBot(None, working_config).load_pokemon_names()

        popup = ctk.CTkToplevel(self)
        popup.title("Battle Settings")
        popup.geometry("450x640")
        popup.resizable(False, False)
        popup.configure(fg_color=BG)
        apply_window_icon(popup)
        popup.transient(self)
        popup.grab_set()

        ctk.CTkLabel(popup, text="Battle & Encounter Configuration", font=("Roboto", 13, "bold"), text_color=WHITE).pack(pady=(12, 6))

        # Catch Shinies Switch
        shiny_var = ctk.BooleanVar(value=working_config.get("catch_shinies", True))
        shiny_cb = ctk.CTkCheckBox(popup, text="Catch All Shinies", variable=shiny_var, font=("Roboto", 11, "bold"), text_color=WHITE, fg_color=BORDER, hover_color=HOVER)
        shiny_cb.pack(pady=4)

        # Search & Select Pokemon Frame
        search_frame = ctk.CTkFrame(popup, fg_color=FIELD, border_color=BORDER, border_width=1)
        search_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(search_frame, text="Search Pokémon:", font=("Roboto", 11, "bold"), text_color=MUTED).pack(anchor="w", padx=12, pady=(8, 2))

        search_entry = ctk.CTkEntry(search_frame, placeholder_text="Type to filter...", fg_color=BG, border_color=BORDER, text_color=WHITE)
        search_entry.pack(fill="x", padx=12, pady=2)

        pokemon_menu = ctk.CTkOptionMenu(search_frame, values=all_pokemon[:40] if all_pokemon else ["None"], fg_color=BG, button_color=HOVER, text_color=WHITE)
        pokemon_menu.pack(fill="x", padx=12, pady=6)

        def on_search_change(*_):
            query = search_entry.get().strip().lower()
            filtered = [name for name in all_pokemon if query in name.lower()]
            if filtered:
                pokemon_menu.configure(values=filtered[:50])
                pokemon_menu.set(filtered[0])
            else:
                pokemon_menu.configure(values=["No matches"])
                pokemon_menu.set("No matches")

        search_entry.bind("<KeyRelease>", on_search_change)

        # Action Buttons (Catch / Run / Pause)
        act_row = ctk.CTkFrame(search_frame, fg_color="transparent")
        act_row.pack(fill="x", padx=12, pady=(4, 8))

        def add_to_list(target_key):
            selected = pokemon_menu.get()
            if not selected or selected in ["None", "No matches"]:
                return
            for key in ["catch_pokemon", "run_from_pokemon", "pause_pokemon"]:
                if selected in working_config.get(key, []):
                    working_config[key].remove(selected)
            working_config.setdefault(target_key, []).append(selected)
            refresh_labels()

        def remove_selected():
            selected = pokemon_menu.get()
            for key in ["catch_pokemon", "run_from_pokemon", "pause_pokemon"]:
                if selected in working_config.get(key, []):
                    working_config[key].remove(selected)
            refresh_labels()

        ctk.CTkButton(act_row, text="+ Catch", width=65, fg_color=HOVER, hover_color=BORDER, text_color=WHITE, command=lambda: add_to_list("catch_pokemon")).pack(side="left", padx=2)
        ctk.CTkButton(act_row, text="+ Run", width=65, fg_color=HOVER, hover_color=BORDER, text_color=WHITE, command=lambda: add_to_list("run_from_pokemon")).pack(side="left", padx=2)
        ctk.CTkButton(act_row, text="+ Pause", width=65, fg_color=HOVER, hover_color=BORDER, text_color=WHITE, command=lambda: add_to_list("pause_pokemon")).pack(side="left", padx=2)
        ctk.CTkButton(act_row, text="Remove", width=65, fg_color="#4A2020", hover_color="#602828", text_color=WHITE, command=remove_selected).pack(side="left", padx=2)

        # Custom Move Row
        move_row = ctk.CTkFrame(search_frame, fg_color="transparent")
        move_row.pack(fill="x", padx=12, pady=(0, 8))

        ctk.CTkLabel(move_row, text="Custom Move (1-4):", font=("Roboto", 11), text_color=MUTED).pack(side="left", padx=(0, 6))
        move_menu = ctk.CTkOptionMenu(move_row, values=["1", "2", "3", "4"], width=60, fg_color=BG, button_color=HOVER, text_color=WHITE)
        move_menu.pack(side="left", padx=(0, 6))

        def set_move():
            selected = pokemon_menu.get()
            if selected and selected not in ["None", "No matches"]:
                working_config.setdefault("pokemon_moves", {})[selected] = move_menu.get()
                refresh_labels()

        def clear_move():
            selected = pokemon_menu.get()
            if selected in working_config.get("pokemon_moves", {}):
                del working_config["pokemon_moves"][selected]
                refresh_labels()

        ctk.CTkButton(move_row, text="Set Move", width=70, fg_color=HOVER, hover_color=BORDER, command=set_move).pack(side="left", padx=2)
        ctk.CTkButton(move_row, text="Clear Move", width=70, fg_color=HOVER, hover_color=BORDER, command=clear_move).pack(side="left", padx=2)

        # Overview Lists Display Frame
        lists_frame = ctk.CTkFrame(popup, fg_color=FIELD, border_color=BORDER, border_width=1)
        lists_frame.pack(fill="both", expand=True, padx=16, pady=4)

        catch_lbl = ctk.CTkLabel(lists_frame, text="Catch:", font=("Roboto", 10), text_color="green", wraplength=400, justify="left")
        catch_lbl.pack(anchor="w", padx=10, pady=2)

        run_lbl = ctk.CTkLabel(lists_frame, text="Run:", font=("Roboto", 10), text_color="#E07070", wraplength=400, justify="left")
        run_lbl.pack(anchor="w", padx=10, pady=2)

        pause_lbl = ctk.CTkLabel(lists_frame, text="Pause:", font=("Roboto", 10), text_color="#F0D060", wraplength=400, justify="left")
        pause_lbl.pack(anchor="w", padx=10, pady=2)

        moves_lbl = ctk.CTkLabel(lists_frame, text="Custom Moves:", font=("Roboto", 10), text_color="cyan", wraplength=400, justify="left")
        moves_lbl.pack(anchor="w", padx=10, pady=2)

        def refresh_labels():
            c_list = working_config.get("catch_pokemon", [])
            r_list = working_config.get("run_from_pokemon", [])
            p_list = working_config.get("pause_pokemon", [])
            m_dict = working_config.get("pokemon_moves", {})

            catch_lbl.configure(text=f"Catch ({len(c_list)}): {', '.join(c_list) if c_list else 'None'}")
            run_lbl.configure(text=f"Run ({len(r_list)}): {', '.join(r_list) if r_list else 'None'}")
            pause_lbl.configure(text=f"Pause ({len(p_list)}): {', '.join(p_list) if p_list else 'None'}")
            moves_str = ", ".join([f"{k} -> Move {v}" for k, v in m_dict.items()]) if m_dict else "None"
            moves_lbl.configure(text=f"Custom Moves: {moves_str}")

        refresh_labels()

        def save_and_close():
            working_config["catch_shinies"] = shiny_var.get()
            self.write_config(working_config)
            popup.destroy()

        ctk.CTkButton(popup, text="Save Battle Settings", fg_color=WHITE, text_color=BG, hover_color="#D0D0D0", font=("Roboto", 11, "bold"), command=save_and_close).pack(pady=(6, 12))


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    # If auth_session exists or user prefers direct start, can start PokeBotGUI directly
    # Check if user wants login or direct GUI
    app = PokeBotGUI()
    app.mainloop()


if __name__ == '__main__':
    main()
