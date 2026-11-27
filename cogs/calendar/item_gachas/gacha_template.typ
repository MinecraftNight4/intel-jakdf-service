// Plantilla de la imagen de gachas. Python solo manda los datos (sys.inputs.data).
// 1pt = 1px cuando el PNG se exporta a 72 ppi; Python usa 144 ppi (imagen nitida a 2x).
#let d = json(bytes(sys.inputs.data))
#let cw = 340pt
#let panel = rgb("#4f4848")      // fondo de chips (armas, personajes, timers)
#let card-bg = rgb("#323033")
#let page-bg = rgb("#040406")

#set page(width: d.width * 1pt, height: auto, margin: 0pt, fill: page-bg)
#set text(font: ("Bungee", "DejaVu Sans"), size: 10pt, fill: white)
#set par(leading: 0.4em)

#let chip(accent, border, body) = block(
  width: 100%, fill: panel, stroke: 1.5pt + border, radius: 6pt,
  inset: (x: 6pt, y: 5pt),
  align(center, text(fill: accent, body)),
)

#let timer(t) = chip(rgb(t.color), rgb("#6e7396"), text(size: 9pt)[
  #t.label: #text(fill: if t.expired { rgb("#ff3737") } else { rgb(t.color) })[#t.value]
])

#let item-list(label, color, items) = stack(
  dir: ttb, spacing: 5pt,
  align(center, text(size: 8pt, fill: rgb(color))[#label]),
  ..items,
)

#let card(b) = {
  let logo = if b.logo != none {
    image(b.logo, width: 100%, height: 100%, fit: "contain")
  } else {
    align(center + horizon, text(size: 9pt, fill: rgb("#78788c"))[NO IMAGE])
  }
  let weapons = b.weapons.map(w => chip(rgb("#d2d7e6"), rgb("#6e738c"), text(size: 8pt)[#w]))
  let chars = b.chars.map(c => chip(rgb(c.color), rgb(c.color), {
    if c.prefix != none { text(size: 7pt)[#c.prefix]; linebreak() }
    text(size: 8pt)[#c.name]
  }))

  block(width: cw, fill: card-bg, radius: 10pt, inset: 12pt, {
    block(width: 100%, height: 100pt, radius: 8pt, clip: true, fill: rgb("#373246"), logo)
    v(8pt)
    align(center, {
      box(fill: rgb(b.badge), radius: 7pt, inset: (x: 10pt, y: 4pt), text(size: 13pt)[#b.kind])
      h(10pt)
      text(size: 16pt, fill: rgb("#ffc8ff"))[#b.name]
    })
    v(8pt)
    grid(columns: (1fr,) * b.timers.len(), column-gutter: 8pt, ..b.timers.map(timer))
    v(8pt)
    grid(
      columns: (1fr, 1fr), column-gutter: 16pt,
      item-list("FEATURED WEAPONS", "#96ffb4", weapons),
      item-list("FEATURED CHARACTERS", "#ffdc82", chars),
    )
  })
}

#block(width: d.width * 1pt, fill: rgb("#43d7d7"), inset: 12pt,
  align(center, text(size: 16pt, fill: rgb("#f3feff"))[KAIJU NO. 8  •  ACTIVE GACHAS]))
#block(width: d.width * 1pt, inset: 12pt,
  grid(columns: (cw,) * d.cols, gutter: 10pt, ..d.banners.map(card)))
#block(width: d.width * 1pt, fill: rgb("#0a3535"), inset: 10pt,
  align(center, text(size: 8pt, fill: rgb("#9bfffd"))[#d.disclaimer]))
