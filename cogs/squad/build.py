# cogs/squad/build.py
"""Paneles (Components V2) del constructor de builds: principal y selector de unidad."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import discord
from discord import ui

from . import codec, render

ACCENT = 0x43D7D7
MAX_OPTIONS = 25            # opciones maximas de un menu desplegable
UNITS_WITH_JUMPS = MAX_OPTIONS - 2      # si hay mas de 25 unidades: 2 huecos para saltar de pagina
SEARCH_LIMIT = 25
DEFAULT_URL = "https://discord.com/channels/@me"
NO_RESULTS = "none"         # valor de la opcion "relleno" del menu de busqueda


@dataclass
class State:
    owner_id: int                               # quien arma la build (creador del codigo)
    count: int                                  # 4 o 16 casillas
    pool: List[dict]                            # unidades elegibles, ya ordenadas
    account_id: Optional[int] = None            # cuenta de referencia (None = todo el roster)
    slots: List[int] = field(default_factory=list)
    description: str = ""
    url: str = DEFAULT_URL                      # enlace del titulo (el canal donde se abrio el editor)

    def __post_init__(self):
        if not self.slots:
            self.slots = [0] * self.count
        self.by_uuid: Dict[int, dict] = {c["uuid"]: c for c in self.pool}

    @property
    def complete(self) -> bool:
        return all(self.slots)

    def assign(self, slot: int, uuid: int) -> None:
        """Pone ``uuid`` en la casilla; si estaba en otra casilla, esa queda vacia (sin repetidos)."""
        for i, current in enumerate(self.slots):
            if current == uuid:
                self.slots[i] = 0
        self.slots[slot] = uuid

    def title_link(self) -> str:
        """Enlace escondido en el titulo. Solo lleva ``?squadcode=`` si ya estan todas las casillas."""
        return f"{self.url}?squadcode={self.code()}" if self.complete else self.url

    def code(self) -> str:
        return codec.encode(self.owner_id, self.slots, self.account_id, self.description)


class _OwnerView(ui.LayoutView):
    def __init__(self, state: State):
        super().__init__(timeout=900)
        self.state = state

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.state.owner_id:
            return True
        await interaction.response.send_message("This panel belongs to someone else. Run `/squad` to make your own.", ephemeral=True)
        return False


# ======================================================================
#  Panel principal
# ======================================================================
class BuilderView(_OwnerView):
    def __init__(self, state: State):
        super().__init__(state)
        title = f"## [SQUAD BUILDER](<{state.title_link()}>)"
        if state.account_id:
            title += f" - <@{state.account_id}>"

        box = ui.Container(accent_colour=ACCENT)
        box.add_item(ui.TextDisplay(title))
        box.add_item(ui.Separator())
        box.add_item(ui.TextDisplay(render.icons(state.slots, state.by_uuid)))
        box.add_item(ui.TextDisplay(render.slot_list(state.slots, state.by_uuid)))

        box.add_item(self._swap_row())
        for start in range(0, state.count, 4):
            row = ui.ActionRow()
            for slot in range(start, start + 4):
                button = ui.Button(label=str(slot + 1), style=discord.ButtonStyle.primary)
                button.callback = self._open_picker(slot)
                row.add_item(button)
            box.add_item(row)

        box.add_item(self._note_text())
        box.add_item(self._actions_row())
        self.add_item(box)

    def _note_text(self) -> ui.TextDisplay:
        note = self.state.description
        return ui.TextDisplay(f"**Note**\n{note}" if note
                              else "**Note**\n-# No note yet. It will be shown with the shared build.")

    def _actions_row(self) -> ui.ActionRow:
        """[Edit note] [Share build]; "Share build" va roja y apagada hasta completar todas las casillas."""
        state, ready = self.state, self.state.complete
        note = ui.Button(label="Edit note", style=discord.ButtonStyle.secondary)
        share = ui.Button(label="Share build", disabled=not ready,
                          style=discord.ButtonStyle.success if ready else discord.ButtonStyle.danger)

        async def show_codes(interaction: discord.Interaction):
            await interaction.response.send_modal(CodesModal(state.code()))

        note.callback = self._ask_description
        share.callback = show_codes
        row = ui.ActionRow()
        row.add_item(note)
        row.add_item(share)
        return row

    def _swap_row(self) -> ui.ActionRow:
        state = self.state
        options = []
        for slot, uuid in enumerate(state.slots):
            char = state.by_uuid.get(uuid)
            options.append(discord.SelectOption(
                label=f"Slot {slot + 1}", value=str(slot),
                description=render.unit_name(char, uuid)[:100]))
        select = ui.Select(placeholder="Swap Placement (pick 2 slots)", min_values=2, max_values=2, options=options)

        async def swap(interaction: discord.Interaction):
            a, b = (int(v) for v in select.values)
            state.slots[a], state.slots[b] = state.slots[b], state.slots[a]
            await interaction.response.edit_message(view=BuilderView(state))

        select.callback = swap
        row = ui.ActionRow()
        row.add_item(select)
        return row

    def _open_picker(self, slot: int):
        async def callback(interaction: discord.Interaction):
            await interaction.response.edit_message(view=PickerView(self.state, slot))
        return callback

    async def _ask_description(self, interaction: discord.Interaction):
        await interaction.response.send_modal(DescriptionModal(self.state))


class CodesModal(ui.Modal, title="Share build"):
    """Comandos para compartir y editar la build, y el codigo suelto. Se copian y se pegan donde haga falta."""

    def __init__(self, code: str):
        super().__init__()
        for label, text in (("Share command", f"/squad share squadcode:{code} private:"),
                            ("Edit command", f"/squad editor squadcode:{code}"),
                            ("Squad code", code)):
            self.add_item(ui.TextInput(label=label, style=discord.TextStyle.paragraph,
                                       required=False, max_length=4000, default=text))

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer()


class DescriptionModal(ui.Modal, title="Build note"):
    def __init__(self, state: State):
        super().__init__()
        self.state = state
        self.text = ui.TextInput(
            label=f"Note (max {codec.MAX_DESCRIPTION} characters)", style=discord.TextStyle.paragraph,
            required=False, max_length=codec.MAX_DESCRIPTION, default=state.description or None)
        self.add_item(self.text)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.text.value or ""
        if codec.count_newlines(value) > codec.MAX_NEWLINES:
            await interaction.response.send_message(
                f"❌ The note can only have {codec.MAX_NEWLINES} line breaks. Press **Add a note** again and shorten it.",
                ephemeral=True)
            return
        self.state.description = codec.fit_description(value)
        await interaction.response.edit_message(view=BuilderView(self.state))


# ======================================================================
#  Selector de unidad
# ======================================================================
class SearchModal(ui.Modal, title="Search unit"):
    def __init__(self, state: State, slot: int, page: int, query: Optional[str]):
        super().__init__()
        self.state, self.slot, self.page = state, slot, page
        self.term = ui.TextInput(label="Unit name", placeholder="e.g. Akari", required=True,
                                 max_length=50, default=query)
        self.add_item(self.term)

    async def on_submit(self, interaction: discord.Interaction):
        query = (self.term.value or "").strip() or None
        await interaction.response.edit_message(view=PickerView(self.state, self.slot, self.page, query))


class PickerView(_OwnerView):
    """Elegir la unidad de una casilla: lista paginada + busqueda por nombre."""

    def __init__(self, state: State, slot: int, page: Optional[int] = None, query: Optional[str] = None):
        super().__init__(state)
        self.slot, self.query = slot, query
        pool = state.pool
        self.per_page = MAX_OPTIONS if len(pool) <= MAX_OPTIONS else UNITS_WITH_JUMPS
        self.pages = max(1, -(-len(pool) // self.per_page))
        if page is None:                                   # abre en la pagina de la unidad actual
            current = state.slots[slot]
            index = next((i for i, c in enumerate(pool) if c["uuid"] == current), 0)
            page = index // self.per_page
        self.page = min(max(page, 0), self.pages - 1)

        box = ui.Container(accent_colour=ACCENT)
        box.add_item(ui.TextDisplay(f"## SQUAD BUILDER - SELECT UNIT FOR SLOT {slot + 1}"))
        box.add_item(ui.Separator())
        box.add_item(self._list_row())
        box.add_item(self._buttons_row())
        box.add_item(self._search_row())
        self.add_item(box)

    # ---------------- piezas ----------------
    def _option(self, char: dict) -> discord.SelectOption:
        state, uuid = self.state, char["uuid"]
        other = next((i for i, u in enumerate(state.slots) if u == uuid and i != self.slot), None)
        return discord.SelectOption(
            label=render.unit_name(char, uuid)[:100], value=str(uuid), emoji=char["icon"] or None,
            default=state.slots[self.slot] == uuid,
            description=f"Used in slot {other + 1}: it will move here" if other is not None else None)

    def _list_row(self) -> ui.ActionRow:
        pool = self.state.pool
        chunk = pool[self.page * self.per_page:(self.page + 1) * self.per_page]
        options = []
        if self.pages > 1 and self.page > 0:
            options.append(discord.SelectOption(label="JUMP TO PAGE 1", value="jump:0", emoji="🏚️"))
        options += [self._option(c) for c in chunk]
        if self.pages > 1 and self.page < self.pages - 1:
            options.append(discord.SelectOption(label=f"JUMP TO PAGE {self.pages}", value=f"jump:{self.pages - 1}", emoji="🚪"))

        placeholder = f"{chunk[0]['full_name']} - {chunk[-1]['full_name']}"
        if self.pages > 1:
            placeholder += f"  ({self.page + 1}/{self.pages})"
        select = ui.Select(placeholder=placeholder[:150], options=options)

        async def picked(interaction: discord.Interaction):
            value = select.values[0]
            if value.startswith("jump:"):
                await interaction.response.edit_message(
                    view=PickerView(self.state, self.slot, int(value[5:]), self.query))
            else:
                await self._choose(interaction, int(value))

        select.callback = picked
        row = ui.ActionRow()
        row.add_item(select)
        return row

    def _buttons_row(self) -> ui.ActionRow:
        cancel = ui.Button(label="✖", style=discord.ButtonStyle.danger)
        prev = ui.Button(label="◀", style=discord.ButtonStyle.secondary, disabled=self.page == 0)
        search = ui.Button(label="Search", emoji="🔍", style=discord.ButtonStyle.success)
        nxt = ui.Button(label="▶", style=discord.ButtonStyle.secondary, disabled=self.page >= self.pages - 1)

        async def back(interaction: discord.Interaction):
            await interaction.response.edit_message(view=BuilderView(self.state))

        async def ask(interaction: discord.Interaction):
            await interaction.response.send_modal(SearchModal(self.state, self.slot, self.page, self.query))

        async def step(interaction: discord.Interaction, delta: int):
            await interaction.response.edit_message(
                view=PickerView(self.state, self.slot, self.page + delta, self.query))

        cancel.callback = back
        search.callback = ask
        prev.callback = lambda i: step(i, -1)
        nxt.callback = lambda i: step(i, +1)
        row = ui.ActionRow()
        for item in (cancel, prev, search, nxt):
            row.add_item(item)
        return row

    def _matches(self) -> List[dict]:
        if not self.query:
            return []
        words = self.query.lower().split()
        found = [c for c in self.state.pool
                 if all(w in f"{c['full_name']} {c['prev_name']}".lower() for w in words)]
        return found[:SEARCH_LIMIT]

    def _search_row(self) -> ui.ActionRow:
        matches = self._matches()
        if matches:
            options = [self._option(c) for c in matches]
        else:                                               # un menu necesita al menos una opcion
            options = [discord.SelectOption(label="Oops, a Kaiju ate the list...", value=NO_RESULTS,
                                            description="Use the 'search' button to filter by name!")]
        placeholder = self.query[:150] if self.query else "Use 'Search' to filter by name"
        select = ui.Select(placeholder=placeholder, options=options)

        async def picked(interaction: discord.Interaction):
            value = select.values[0]
            if value == NO_RESULTS:                         # no hace nada: se redibuja igual
                await interaction.response.edit_message(view=PickerView(self.state, self.slot, self.page, self.query))
            else:
                await self._choose(interaction, int(value))

        select.callback = picked
        row = ui.ActionRow()
        row.add_item(select)
        return row

    async def _choose(self, interaction: discord.Interaction, uuid: int):
        self.state.assign(self.slot, uuid)
        await interaction.response.edit_message(view=BuilderView(self.state))
