import json
import os
import traceback
import discord
from discord import app_commands
from discord.ext import commands

NEWS_FILE = "app_read/read_news.json"

class News(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.news_data = {}
        self.load_news()

    def load_news(self):
        try:
            if os.path.exists(NEWS_FILE):
                with open(NEWS_FILE, "r", encoding="utf-8") as f:
                    self.news_data = json.load(f)
                print(f"✅ Noticias cargadas: {len(self.news_data)} keys")
                print(f"Keys: {list(self.news_data.keys())}")
            else:
                print(f"⚠️ No se encontró {NEWS_FILE}")
        except Exception as e:
            print(f"❌ Error cargando noticias: {e}")

    @app_commands.command(name="gamenews", description="Muestra una noticia (Components V2)")
    @app_commands.describe(
        article_id="ID del artículo (ejemplo: 1000030)",
        page="Número de página"
    )
    async def gamenews(
        self,
        interaction: discord.Interaction,
        article_id: str = "1000030",
        page: app_commands.Range[int, 1, 30] = 1
    ):
        key = f"gamenews_{article_id}_{page}"
        print(f"🔍 Intentando enviar key: {key}")

        if key not in self.news_data:
            available = list(self.news_data.keys())
            await interaction.response.send_message(
                f"❌ No existe la key `{key}`\n\nKeys disponibles:\n" + "\n".join(f"`{k}`" for k in available),
                ephemeral=True
            )
            return

        payload = self.news_data[key]

        try:
            # Enviamos el payload Components V2
            await interaction.response.send_message(**payload)
            print(f"✅ Mensaje enviado correctamente: {key}")
        except Exception as e:
            error_msg = f"❌ Error al enviar el mensaje:\n```{traceback.format_exc()}```"
            print(error_msg)
            try:
                await interaction.response.send_message(error_msg, ephemeral=True)
            except:
                await interaction.followup.send(error_msg, ephemeral=True)

    @app_commands.command(name="reload_news", description="Recarga el JSON de noticias")
    @app_commands.default_permissions(administrator=True)
    async def reload_news(self, interaction: discord.Interaction):
        self.load_news()
        await interaction.response.send_message(
            f"✅ Recargado. Total keys: `{len(self.news_data)}`",
            ephemeral=True
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(News(bot))