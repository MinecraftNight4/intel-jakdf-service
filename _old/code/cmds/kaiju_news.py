import discord
from discord import app_commands, ui
from discord.ext import commands
import json
import os
from utils.kaiju_helpers import get_emoji, get_info_text

private_guild = discord.Object(id=1332085001013039194)


class KaijuNewsView(ui.LayoutView):
    def __init__(self, news_storage: dict):
        super().__init__()
        container = ui.Container(accent_colour=0x00ffaa)
        container_txt = ui.TextDisplay("## [`🔗`](https://info.kj8-thegame.com/news?language=en) __**KAIJU NO. 8 THE GAME**__ | __IN-GAME NEWS__")
        container.add_item(container_txt)
        
        container_img = ui.MediaGallery()
        container_img.add_item(media="https://asset.kj8-thegame.com/info/production/content/1002470/991d2535abd79a29d2728805fb2b9189.avif?Expires=1780937182&Signature=Lk0Y-fV3bfbnMj3-Jx5WV0DVbjL2fBfx7A070E~5ETFBdd42WutYa9aBz9woRBs7eHUpo8nC2gMrfccrQMB6fyYMcLBiLNuhKmJvkenx4RZIlBL5SeQ4V9X-yevOxGGY5tC8a1s02jgQY0Lo87w2EC62abO5ZE~IIOhE4h7SDmFoZ5UBZNMWd-Vto-64gr~W7lkcOYcbvpj4cH~C9NcipuxwvdCJFHDAA1GEszIVP3EqYwWKAp6QV-7xbTFnJPsZvVbIoKNaHUB5cFgy~mDzdJ1rOxFEtYikfRd9I-1XeO5oaSPRKpPdY330BkbAkYJuOAK8GPSRJ3D7k79LpsDsbQ__&Key-Pair-Id=K22LOBLWI3HWJQ")
        container.add_item(container_img)
        
        
        
        self.add_item(container)


class KaijuNewsCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.news_storage = {}

    def load_news(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            news_file = os.path.join(base_dir, "storage", "news.json")

            if os.path.exists(news_file):
                with open(news_file, 'r', encoding='utf-8') as f:
                    self.news_storage = json.load(f)
                print(f"✅ {len(self.news_storage)} noticias cargadas")
                return True
            else:
                print("❌ No se encontró storage/news.json")
                return False
        except Exception as e:
            print(f"❌ Error al cargar JSON: {e}")
            return False

    @app_commands.guilds(private_guild)
    @app_commands.command(name="news", description="News Index - Kaiju No.8 The Game")
    async def news_index(self, interaction: discord.Interaction):
        await interaction.response.defer()

        if not self.load_news() or not self.news_storage:
            return await interaction.followup.send("No se encontró `storage/news.json`")
        view = KaijuNewsView(self.news_storage)
        await interaction.followup.send(view=view)


async def setup(bot):
    await bot.add_cog(KaijuNewsCog(bot))