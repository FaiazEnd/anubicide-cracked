# Anubicide - Reverse Engineering Analysis & Clean Reconstruction

A reverse-engineered analysis and clean implementation of **Anubicide**, a specialized computer vision and OCR automation tool for *Poke Nexus*.

---

## 1. Reverse Engineering Evidence & Findings

### 1.1 Binary Packaging & Target Architecture
- **Target File:** `Anubicide.exe` (~155 MB)
- **Format:** Windows PE 64-bit (`MZ` / `PE\0\0`)
- **Packer:** **PyInstaller 2.1+ / 6.x** CArchive format
- **Bundled Python Runtime:** **CPython 3.13.x (AMD64)** (`python313.dll`, magic bytes `0xf3 0x0d 0x0d 0x0a`)
- **Archive Contents:**
  - `CArchive`: 3,148 extracted binary dependencies, runtime DLLs, and direct assets.
  - `PYZ Archive`: 2,499 marshalled compiled Python bytecode modules (`PYZ.pyz`).
  - Core proprietary modules identified:
    1. `bot_gui.pyc` (Main application entry point, CustomTkinter interface, Supabase authentication & updater)
    2. `bot_core.pyc` (Game automation, Win32 window management, OCR, movement, combat engine, template matching)
    3. `discord_notifier.pyc` (Discord bot client with async thread loop for alert DMs)
    4. `timeout_manager.pyc` (Encounter stagnation detection & automated recovery)

---

### 1.2 Core Automation Engine & Coordinate System
The bot targets a fixed client window resolution of **1024x768**, dynamically moving and anchoring it to the selected monitor with Win32 API (`user32.SetWindowPos` with flags `SWP_NOZORDER | SWP_NOACTIVATE = 68` and `user32.GetWindowRect`).

#### Key Screen Bounding Boxes & Detection Coordinates (Relative to Window Top-Left):
| Component | Box Coordinates `(x1, y1, x2, y2)` | Purpose |
| :--- | :--- | :--- |
| **Play Area** | `(7, 29, 1010, 758)` | Active gameplay area for grass scanning |
| **Character Center** | `(510, 429)` | Origin point for character movement vectors |
| **Encounter Trigger** | `(630, 134, 670, 170)` | Battle start indicator (`encounter_start.png`, thr: 0.85) |
| **Pokemon Name Area** | `(300, 196, 520, 215)` | Crop area for Tesseract OCR recognition |
| **Shiny Symbol** | `(325, 193, 356, 217)` | Shiny star symbol (`shiny.png`, thr: 0.85) |
| **Elite Tag** | `(326, 193, 437, 216)` | Elite Pokémon tag (`elite.png`, thr: 0.72) |
| **Connect Button** | `(429, 539, 661, 620)` | Main menu reconnect button (`connect_button.png`, thr: 0.75) |
| **Disconnect Box** | `(289, 471, 719, 514)` | Network error screen (`disconnect_screen.png`, thr: 0.80) |
| **Bicycle Icon** | `(495, 415, 535, 465)` | Riding status icon (`cycle.png`, thr: 0.70) |
| **Popup Close (X)** | `(682, 289, 716, 328)` | Game notice popup (`popup_x.png`, thr: 0.75) |
| **Request Decline (X)**| `(612, 303, 690, 349)` | Trade/Battle request (`request_x.png`, thr: 0.75) |
| **Learn Move Box** | `(356, 246, 458, 281)` | Move learn prompt (`learn_move.png`, thr: 0.80) |
| **Forget Move Position**| `(592, 389)` | Clicks to overwrite 2nd move slot |
| **Evolution Yes Box** | `(328, 622, 481, 652)` | Evolution prompt (`evolve_yes.png`, thr: 0.80) |
| **Evolution Yes Click**| `(404, 637)` | Auto-clicks YES to accept evolution |
| **Anubisius Search** | `(815, 451, 993, 494)` | Scans dragged player list for admin name (`Anubisius.png`) |
| **Player List Click**| `(56, 723)` | Bottom-left UI button to open online roster |
| **Player List Drag** | `(1000, 1000)` | Drag destination to pull player window into scan area |

---

### 1.3 Computer Vision & OCR Logic
1. **Name Preprocessing:** Grayscale conversion -> 4x Bicubic upscaling -> Otsu automatic binary thresholding.
2. **OCR Configuration:** Tesseract PSM 7 (Single Text Line) with character whitelist:
   `ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789[]-:.??'? `
3. **Fuzzy Normalization:** Normalizes unicode gender glyphs (`♀`, `♂`), apostrophes, dashes, and runs `difflib.get_close_matches` against 809 Pokémon names from `pokemons.txt` with a `cutoff=0.6`.
4. **Combat Actions:**
   - **Custom Moves:** Move 1-4 selection per Pokémon (`pokemon_moves` in config).
   - **Catch Routine:** Presses `'2'` (Bag), sleeps, presses `'3'` (Pokéball), monitors for conclusion with a 70s watchdog.
   - **Run Routine:** Presses `'4'` (Run).
   - **Shiny Protection:** Alerts via Discord DM and auto-catches if configured.
   - **Elite Handling:** Auto-runs when elite detected.

---

### 1.4 Anti-Admin Protection: "Anubisius" Detection
- Opens online player roster via UI coordinate `(56, 723)`.
- Drags the list down into the right viewport.
- Periodically scans `ANUBISIUS_SEARCH_BOX` `(815, 451, 993, 494)` for staff/admin user `Anubisius`.
- Upon detection:
  - Dispatches high-priority alert via Discord DM (`[Alert] Anubisius is online!`).
  - Optionally halts bot movement (`pause_when_anubisius_online = True`) until the staff member logs off.

---

### 1.5 Crash & Disconnection Recovery
- Detects network disconnect screens with a two-strike confirmation check.
- Terminates dead game processes using `taskkill /f /im "Poke Nexus.exe"`.
- Relaunches game via `subprocess.Popen`, re-acquires window, re-aligns to 1024x768 on the designated monitor.
- Automatically equips bicycle by pressing `'b'` if not detected.
- Resumes movement and schedules roster reopening.

---

## 2. Reconstructed Project Structure

```
Anubicide/
├── assets/                     # 17 Extracted game templates & resources
│   ├── anubicide_logo.ico      # Window icon
│   ├── anubicide_logo.png      # Application header banner
│   ├── Anubisius.png           # Admin nameplate template
│   ├── connect_button.png      # Login/Connect button template
│   ├── cycle.png               # Bicycle icon template
│   ├── disconnect_screen.png   # Disconnect modal template
│   ├── elite.png               # Elite battle tag template
│   ├── encounter_start.png     # Combat trigger template
│   ├── evolve_yes.png          # Evolution button template
│   ├── fight_template.png      # Fight menu template
│   ├── learn_move.png          # Learn move header template
│   ├── middle.png              # Grass tile template
│   ├── online.png              # Online player roster header
│   ├── popup_x.png             # Dialog close button
│   ├── request_x.png           # Battle request decline button
│   ├── shiny.png               # Shiny star badge template
│   └── pokemons.txt            # Complete roster of 809 Pokémon names
├── bot_core.py                 # Core automation, CV, OCR, win32 & movement engine
├── bot_gui.py                  # CustomTkinter GUI interface & dialogs
├── discord_notifier.py         # Discord async notification client
├── timeout_manager.py          # Stagnation monitoring & restart handler
├── config.json                 # Persistent configuration file
├── main.py                     # Entry point
└── README.md                   # Complete documentation
```

---

## 3. Running the Reconstructed Project

### Prerequisites
- Python 3.10+ (tested on Python 3.13 and 3.14)
- Tesseract OCR installed at `C:\Program Files\Tesseract-OCR\tesseract.exe` (or in PATH)
- Dependencies:
  ```bash
  pip install customtkinter opencv-python pillow pyautogui pygetwindow keyboard pytesseract numpy discord.py
  ```

### Launch
To launch the application:
```bash
python main.py
```
Or with optional Supabase subscription login dialog:
```bash
python main.py --login
```

### Hotkeys
- **Page Up:** Start Bot
- **Page Down:** Stop Bot
