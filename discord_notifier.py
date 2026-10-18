import discord
import asyncio
import threading
import json
import os

CONFIG_FILE = "config.json"


def load_bot_token():
    if not os.path.exists(CONFIG_FILE):
        print("[Discord] config.json not found. Discord notifier disabled.")
        return ""
    try:
        with open(CONFIG_FILE, "r") as f:
            config = json.load(f)
        token = config.get("discord_bot_token", "").strip()
        if not token:
            print("[Discord] No discord_bot_token found in config.json. Discord notifier disabled.")
        return token
    except Exception as e:
        print("[Discord] Failed to load token from config.json:", e)
        return ""


class DiscordNotifier:
    def __init__(self):
        self.client = discord.Client(intents=discord.Intents.default())
        self.loop = asyncio.new_event_loop()
        self.ready = False
        self.started = False
        self.token = ""

        @self.client.event
        async def on_ready():
            self.ready = True
            print(f"[Discord] Logged in as {self.client.user}")

    def start(self):
        if self.started:
            return
        self.token = load_bot_token()
        if not self.token:
            return
        self.started = True

        def run():
            try:
                asyncio.set_event_loop(self.loop)
                self.loop.create_task(self.client.start(self.token))
                self.loop.run_forever()
            except Exception as e:
                print("[Discord] Failed to start notifier:", e)

        threading.Thread(target=run, daemon=True).start()

    def send_dm(self, user_id, message):
        if not user_id or not self.ready:
            return

        async def _send():
            try:
                user = await self.client.fetch_user(int(user_id))
                await user.send(message)
            except Exception as e:
                print("[Discord]", e)

        asyncio.run_coroutine_threadsafe(_send(), self.loop)


notifier = DiscordNotifier()
