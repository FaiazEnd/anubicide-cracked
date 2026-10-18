"""
Anubicide - Automated Poke Nexus Automation Suite
Reconstructed with full feature fidelity:
- CustomTkinter Monochrome Dark UI
- Multi-Monitor DPI awareness and automatic 1024x768 window positioning
- Three Movement Modes: Grass Detection (Computer Vision Grid), Left/Right, Up/Down
- OCR Pokémon Name Recognition & Fuzzy Matching with Tesseract
- Automated Battle Actions: Custom Move selection (1-4), Catch, Run, Shiny detection
- Anti-Admin Protection: Anubisius staff presence detection & Discord notification/pause
- Auto-recovery: Reconnect handling, crash restart, bicycle re-equipping
"""

import sys
import customtkinter as ctk
import bot_gui


def main():
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    # If --login flag is passed, launch Supabase login window first, otherwise launch main GUI
    if "--login" in sys.argv:
        app = bot_gui.LoginWindow()
    else:
        app = bot_gui.PokeBotGUI()

    app.mainloop()


if __name__ == "__main__":
    main()
