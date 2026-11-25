// Imagen de /squad share. Python solo manda los datos (sys.inputs.data).
// 1pt = 1px a 72 ppi; Python usa 144 ppi (imagen nitida a 2x).
#let d = json(bytes(sys.inputs.data))
#let page-bg = rgb("#040406")
#let card-bg = rgb("#323033")
#let panel = rgb("#4f4848")
#let cell-w = 150pt
#let sep-w = 52pt
#let gap = 10pt
#let duo-size = 47.6pt     // 28pt + 70%
#let amp-size = 33.6pt     // 28pt + 20%
#let pad = 12pt
#let total-w = pad * 2 + cell-w * 4 + sep-w * 3

#set page(width: total-w, height: auto, margin: 0pt, fill: page-bg)
#set text(font: (d.fonts.body, "DejaVu Sans"), size: 10pt, fill: white)
#set par(leading: 0.4em)

// Tarjeta (esquinas curvas) con el icono y el cuadro de nombre, estos dos con esquinas rectas.
#let cell(c) = block(width: cell-w, fill: card-bg, radius: 10pt, inset: 8pt, {
  block(width: 100%, height: cell-w - 16pt, clip: true, fill: rgb("#373246"), {
    if c.image != none {
      image(c.image, width: 100%, height: 100%, fit: "cover")
    } else {
      align(center + horizon, text(size: 28pt, fill: rgb("#78788c"))[?])
    }
    place(top + left, dx: 5pt, dy: 5pt,
      box(fill: rgb("#040406"), inset: (x: 5pt, y: 2pt), text(size: 9pt)[#c.slot]))
  })
  v(6pt)
  block(width: 100%, height: 46pt, fill: panel, stroke: 1.5pt + rgb("#6e7396"),
    inset: (x: 5pt, y: 4pt),
    align(center + horizon, {
      if c.prefix != "" { text(size: 9.5pt, fill: rgb(c.color))[#c.prefix]; linebreak() }
      text(size: 12pt)[#c.name]
    }))
})

// Icono entre dos tarjetas de la misma fila, centrado con el icono del personaje.
#let sep(path, size, fallback) = block(width: sep-w, height: cell-w,
  align(center + horizon, if path != none {
    image(path, width: size)
  } else {
    text(size: 16pt, font: (d.fonts.title, "DejaVu Sans"))[#fallback]
  }))

// Fila de 4: 1 ∞ 2 & 3 ∞ 4
#let row-of(cs) = (
  cell(cs.at(0)), sep(d.sep.duo, duo-size, "~"),
  cell(cs.at(1)), sep(d.sep.amp, amp-size, "&"),
  cell(cs.at(2)), sep(d.sep.duo, duo-size, "~"),
  cell(cs.at(3)),
)

#block(width: total-w, fill: rgb("#43d7d7"), inset: 12pt,
  align(center, text(font: (d.fonts.title, "DejaVu Sans"), size: 15pt, fill: rgb("#f3feff"))[#d.title]))
#if d.description != none {
  block(width: total-w, fill: rgb("#0a3535"), inset: 12pt,
    align(center, text(size: 12pt, fill: rgb("#9bfffd"))[#d.description.split("\n").join(linebreak())]))
}
#block(width: total-w, inset: pad,
  grid(
    columns: (cell-w, sep-w, cell-w, sep-w, cell-w, sep-w, cell-w),
    column-gutter: 0pt, row-gutter: gap,
    ..range(0, d.cells.len(), step: 4).map(i => row-of(d.cells.slice(i, i + 4))).flatten(),
  ))
