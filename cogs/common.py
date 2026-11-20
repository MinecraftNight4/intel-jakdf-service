import discord

from logger import log


async def respond_with_view(
    interaction: discord.Interaction,
    view: discord.ui.BaseView,
    *,
    force_private: bool = False,
    tag: str = "BOT",
) -> None:
    """
    Responde a una interacción de componente con una vista ya construida.

    - Por defecto edita el mensaje original (navegación dentro de /news, /store).
    - Con force_private=True nunca edita: manda un mensaje efímero nuevo
      (botones de mensajes de feeds públicos).
    - Si la interacción ya fue respondida, o la edición falla, cae a un followup.
    """
    try:
        if interaction.response.is_done():
            await interaction.followup.send(view=view, ephemeral=True)
        elif force_private:
            await interaction.response.send_message(view=view, ephemeral=True)
        else:
            await interaction.response.edit_message(view=view)

    except discord.errors.InteractionResponded:
        try:
            await interaction.followup.send(view=view, ephemeral=True)
        except Exception:
            pass

    except Exception as exc:
        # Mensaje muy viejo, vista inválida, etc.
        try:
            if interaction.response.is_done():
                await interaction.followup.send(view=view, ephemeral=True)
            else:
                await interaction.response.send_message(view=view, ephemeral=True)
        except Exception:
            log(f"[{tag}] respond_with_view failed completely: {exc}", tag.lower(), level="CRIT", show=False)
