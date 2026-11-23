# cogs/profile/bulk.py
"""/profile edit: panel (Components V2) para editar muchos personajes sin escribir comandos."""
import discord
from discord import ui

from .format import STATUS_OPTIONS
from .store import LOCKED, ProfileStore

MAX_INDEX = 25        # opciones maximas de un menu desplegable
ACCENT = 0x43D7D7


class BulkView(ui.LayoutView):
    def __init__(self, store: ProfileStore, user_id: int, page: int = 0):
        super().__init__(timeout=900)
        self.store, self.user_id = store, user_id
        store.roster.reload_if_changed()
        roster = store.roster
        self.pages = max(1, len(roster.pages))
        self.page = min(max(page, 0), self.pages - 1)
        owned = store.owned(user_id)

        box = ui.Container(accent_colour=ACCENT)
        box.add_item(ui.TextDisplay(
            "## ✏️ __EDIT PROFILE__\n"
            f"-# Page {self.page + 1}/{self.pages} · Pick a state for each character, changes are saved instantly"
        ))
        box.add_item(ui.Separator())

        page_uuids = roster.pages[self.page] if roster.pages else []
        for char in (roster.by_uuid[u] for u in page_uuids):
            current = owned.get(char["uuid"], LOCKED)
            select = ui.Select(
                placeholder="Choose a state",
                options=[discord.SelectOption(label=label, value=str(value), default=value == current)
                         for value, label in STATUS_OPTIONS],
            )
            select.callback = self._on_status(select, char["uuid"])
            row = ui.ActionRow()
            row.add_item(select)
            box.add_item(ui.TextDisplay(f"## {char['icon']} {char['full_name']} {char['prev_name']}"))
            box.add_item(row)

        if not roster.items:
            box.add_item(ui.TextDisplay("*The character list is empty.*"))

        if self.pages > 1:
            box.add_item(ui.Separator())
            box.add_item(self._nav_row())
            box.add_item(self._index_row())
        self.add_item(box)

    # ---------------- piezas ----------------
    def _nav_row(self) -> ui.ActionRow:
        prev = ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        nxt = ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self.pages - 1)
        prev.callback = lambda i: self._go(i, -1)
        nxt.callback = lambda i: self._go(i, +1)
        row = ui.ActionRow()
        row.add_item(prev)
        row.add_item(ui.Button(label=f"PAGE {self.page + 1} OF {self.pages}",
                               style=discord.ButtonStyle.success, disabled=True))
        row.add_item(nxt)
        return row

    def _index_row(self) -> ui.ActionRow:
        """Menu de salto bajo los botones: 'Page N' + nombres base de sus personajes."""
        roster = self.store.roster
        if self.pages <= MAX_INDEX:
            shown, first, last = list(range(1, self.pages + 1)), False, False
        else:                                      # ventana de 23 paginas alrededor de la actual
            end = min(self.pages, max(1, self.page + 1 - 11) + 22 - 1)
            start = max(1, end - 22 + 1)
            shown, first, last = list(range(start, end + 1)), start > 1, end < self.pages

        options = []
        if first:
            options.append(discord.SelectOption(label="JUMP TO PAGE 1", value="0", emoji="🏚️"))
        for number in shown:
            names = roster.names[number - 1] if number <= len(roster.names) else []
            options.append(discord.SelectOption(
                label=f"Page {number}", value=str(number - 1),
                emoji="📍" if number - 1 == self.page else "⏩",
                description=", ".join(names)[:100] or None))
        if last:
            options.append(discord.SelectOption(label=f"JUMP TO PAGE {self.pages}", value=str(self.pages - 1), emoji="🚪"))

        select = ui.Select(placeholder=f"Jump to page… (now {self.page + 1}/{self.pages})", options=options[:MAX_INDEX])

        async def jump(interaction: discord.Interaction):
            await interaction.response.edit_message(view=BulkView(self.store, self.user_id, int(select.values[0])))

        select.callback = jump
        row = ui.ActionRow()
        row.add_item(select)
        return row

    # ---------------- acciones ----------------
    def _on_status(self, select: ui.Select, uuid: int):
        async def callback(interaction: discord.Interaction):
            self.store.set_status(self.user_id, uuid, int(select.values[0]))
            await interaction.response.edit_message(view=BulkView(self.store, self.user_id, self.page))
        return callback

    async def _go(self, interaction: discord.Interaction, step: int):
        await interaction.response.edit_message(view=BulkView(self.store, self.user_id, self.page + step))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.user_id
