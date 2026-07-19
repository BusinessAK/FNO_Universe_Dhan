import plotly.graph_objects as go
from collections import defaultdict
from vanguard.config.settings import C

def apply_axes(fig: go.Figure, axes_config: dict):
    """Standard helper to configure axis properties in modular charts."""
    fig.update_layout(**axes_config)


# Same-side label proximity threshold (pixel-density derived, chart height=580, ±12% range):
# Each font-size-10 label occupies ~0.91% of spot on the y-axis.
# 1.2% gives a clean one-label-height safety margin.
# Cross-side levels (e.g. Put Wall LEFT vs Spot RIGHT) NEVER conflict visually
# and are therefore NEVER merged — they always get their own full label.
_SAME_SIDE_MERGE_PCT = 0.012


# ── Styling constants ────────────────────────────────────────────────────────
_STYLE_RANK  = {"solid": 0, "dash": 1, "dot": 2}
_PRIORITY    = {"Call Wall": 0, "Spot": 1, "Put Wall": 2, "Gamma Flip": 3}
_DEFAULT_POS = {
    "Spot":       "top right",
    "Call Wall":  "bottom right",
    "Gamma Flip": "top left",
    "Put Wall":   "bottom left",
}
_SIDE_OF = {
    "Spot":       "right",
    "Call Wall":  "right",
    "Gamma Flip": "left",
    "Put Wall":   "left",
}


def _make_label(names: list, price: float) -> str:
    """De-duplicate and join names, append formatted price."""
    seen, unique = set(), []
    for n in names:
        if n not in seen:
            seen.add(n)
            unique.append(n)
    return " & ".join(unique) + f": ₹{price:,.0f}"


def add_hlines(
    fig: go.Figure,
    cmp_val: float,
    gf_val: float,
    cw_val: float,
    pw_val: float,
    rows_cols=None,
):
    """
    Draw key structural level hlines on Plotly figures with zero annotation overlap.

    Algorithm — 3 passes:
    ─────────────────────
    Pass 1  Build the raw 4-level list (Spot, Gamma Flip, Call Wall, Put Wall).

    Pass 2  Global exact-price dedup: if any two levels share the same price,
            merge them into ONE line with ONE combined label.
            Priority order: Call Wall > Spot > Put Wall > Gamma Flip.
            The merged entry inherits the dominant side (right > left).

    Pass 3  Same-side proximity suppression: within each annotation side
            (left / right) independently, if two remaining levels are within
            _SAME_SIDE_MERGE_PCT of each other the LOWER level's label is
            suppressed. Its accumulated name list is chain-propagated (not
            just original names) to the upper level's combined label.
            Cross-side levels are NEVER merged — Put Wall (left) and
            Spot/Call Wall (right) occupy opposite sides and can never
            visually overlap, so both always keep their full labels.
    """
    if not rows_cols:
        rows_cols = [(1, 1)]

    # ── Pass 1: raw levels ───────────────────────────────────────────────────
    raw = []
    if cmp_val and float(cmp_val) > 0:
        raw.append({"name": "Spot",       "price": float(cmp_val)})
    if gf_val  and float(gf_val)  > 0:
        raw.append({"name": "Gamma Flip", "price": float(gf_val)})
    if cw_val  and float(cw_val)  > 0:
        raw.append({"name": "Call Wall",  "price": float(cw_val)})
    if pw_val  and float(pw_val)  > 0:
        raw.append({"name": "Put Wall",   "price": float(pw_val)})
    if not raw:
        return

    # ── Pass 2: global exact-price dedup ────────────────────────────────────
    price_map: dict[float, list] = defaultdict(list)
    for lv in raw:
        price_map[lv["price"]].append(lv["name"])

    levels: list[dict] = []
    for price in sorted(price_map.keys()):
        names_at_price = sorted(price_map[price], key=lambda n: _PRIORITY.get(n, 9))
        primary = names_at_price[0]

        # Build merged styling from all members at this price
        all_styles = [{"solid": "solid", "dash": "dash", "dot": "dot"}.get(
            "solid" if n in ("Call Wall", "Put Wall") else
            "dash"  if n == "Spot" else "dot", "dot"
        ) for n in names_at_price]
        style = min(all_styles, key=lambda s: _STYLE_RANK[s])

        color_map = {
            "Call Wall":  C.get("call", "#58a6ff"),
            "Spot":       C.get("cmp",  "#fbbf24"),
            "Put Wall":   C.get("put",  "#f85149"),
            "Gamma Flip": C.get("flip", "#a78bfa"),
        }
        color = color_map[primary]

        # Side: right wins over left when merging cross-side exact-price hits
        sides = [_SIDE_OF.get(n, "right") for n in names_at_price]
        side = "right" if "right" in sides else "left"

        levels.append({
            "price":      price,
            "names":      names_at_price,   # accumulated name list (grows in Pass 3)
            "color":      color,
            "style":      style,
            "side":       side,
            "show_label": True,
        })

    # ── Pass 3: same-side proximity label suppression ───────────────────────
    # Process each side independently so cross-side levels are never merged.
    for side in ("left", "right"):
        side_idx = [i for i, lv in enumerate(levels) if lv["side"] == side]
        # Already sorted by price (Pass 2 sorted by price ascending)
        for ii in range(len(side_idx)):
            i = side_idx[ii]
            if not levels[i]["show_label"]:
                continue
            pi = levels[i]["price"]
            for jj in range(ii + 1, len(side_idx)):
                j = side_idx[jj]
                pj = levels[j]["price"]
                rel_diff = (pj - pi) / max(pi, pj)
                if rel_diff >= _SAME_SIDE_MERGE_PCT:
                    break  # sorted → no further same-side pair can be closer
                # Suppress i (lower), chain-propagate its FULL accumulated names to j
                if levels[j]["show_label"]:
                    # prepend lower-level names, de-dup later in _make_label
                    levels[j]["names"] = levels[i]["names"] + levels[j]["names"]
                levels[i]["show_label"] = False

    # ── Assign annotation positions ──────────────────────────────────────────
    for lv in levels:
        primary = lv["names"][0]
        lv["ann_pos"] = _DEFAULT_POS.get(primary,
                        "top right" if lv["side"] == "right" else "top left")

    # ── Draw every level onto each subplot ───────────────────────────────────
    for r, c in rows_cols:
        for lv in levels:
            price = lv["price"]
            color = lv["color"]
            style = lv["style"]
            side  = lv["side"]

            # Build display text
            if lv["show_label"]:
                text = _make_label(lv["names"], price)
                display = f" {text}" if side == "right" else f" {text} "
            else:
                display = ""

            kwargs = dict(
                y=price,
                line_dash=style if style != "solid" else None,
                line_color=color,
                line_width=1.4,
                row=r, col=c,
            )
            if display:
                kwargs.update(
                    annotation_text=display,
                    annotation_position=lv["ann_pos"],
                    annotation_font_color=color,
                    annotation_font_size=10,
                    annotation_font_family="JetBrains Mono",
                    annotation_bgcolor="rgba(3,3,12,0.7)",
                )
            fig.add_hline(**kwargs)
