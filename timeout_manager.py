import time


class TimeoutManager:
    def __init__(self, bot):
        self.bot = bot

    def should_restart_no_encounter(self):
        if not self.bot.config.get("restart_on_no_encounter", False):
            return False
        if self.bot.should_skip_no_encounter_timeout():
            return False
        timeout_minutes = self.bot.config.get("restart_no_encounter_minutes", 5)
        timeout_seconds = timeout_minutes * 60
        if (time.time() - self.bot.last_encounter_time) >= timeout_seconds:
            return True
        return False

    def handle_restart_no_encounter(self):
        timeout_minutes = self.bot.config.get("restart_no_encounter_minutes", 5)
        print(f"[!] No encounters for {timeout_minutes} minutes. Restarting.")
        self.bot.stop_moving()
        self.bot.reconnecting = True
        self.bot.loading_after_restart = True
        self.bot.in_combat = False
        self.bot.last_restart_time = time.time()
        if hasattr(self.bot, "record_restart"):
            self.bot.record_restart()
        from bot_core import launch_and_setup_game
        self.bot.win = launch_and_setup_game(self.bot.config["game_path"], force_restart=True)
        if self.bot.win:
            self.bot.check_bicycle()
        self.bot.last_encounter_time = time.time()
        self.bot.last_connect_click = 0
        self.bot.last_connect_check = 0
        self.bot.last_disconnect_check = time.time()
        self.bot.disconnect_confirm_count = 0
        self.bot.bike_checked_after_reconnect = False
        self.bot.last_bike_check_after_reconnect = time.time()
