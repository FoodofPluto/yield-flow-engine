
from PIL import Image, ImageDraw, ImageFont
import textwrap
from pathlib import Path


def _load_font(candidates, size):
    for path in candidates:
        try:
            if path and Path(path).exists():
                return ImageFont.truetype(str(path), size)
        except Exception:
            pass
    try:
        return ImageFont.truetype("arial.ttf", size)
    except Exception:
        return ImageFont.load_default()


def _font_paths():
    windows_font_dir = Path("C:/Windows/Fonts")
    linux_font_dir = Path("/usr/share/fonts/truetype/dejavu")
    return windows_font_dir, linux_font_dir


def _fonts(scale: float = 1.0):
    windows_font_dir, linux_font_dir = _font_paths()

    def sz(value: int) -> int:
        return max(12, int(round(value * scale)))

    return {
        "xs": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            sz(30),
        ),
        "sm": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            sz(40),
        ),
        "sm_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(42),
        ),
        "md": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            sz(52),
        ),
        "md_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(56),
        ),
        "lg_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(86),
        ),
        "xl_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(220),
        ),
    }




def _font_candidates(bold: bool = False):
    windows_font_dir, linux_font_dir = _font_paths()
    if bold:
        return [
            windows_font_dir / "arialbd.ttf",
            windows_font_dir / "segoeuib.ttf",
            linux_font_dir / "DejaVuSans-Bold.ttf",
        ]
    return [
        windows_font_dir / "arial.ttf",
        windows_font_dir / "segoeui.ttf",
        linux_font_dir / "DejaVuSans.ttf",
    ]


def _measure_text(draw, text, font, spacing=4):
    bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _wrap_by_pixels(draw, text, font, max_width):
    words = str(text).split()
    if not words:
        return ""
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        w = draw.textbbox((0, 0), trial, font=font)[2]
        if w <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return "\n".join(lines)


def _fit_text_block(draw, text, box, max_size, min_size=18, bold=False, spacing=4, max_lines=None):
    x1, y1, x2, y2 = box
    max_width = max(20, x2 - x1)
    max_height = max(20, y2 - y1)
    candidates = _font_candidates(bold=bold)

    for size in range(int(max_size), int(min_size) - 1, -2):
        font = _load_font(candidates, size)
        wrapped = _wrap_by_pixels(draw, text, font, max_width)
        if max_lines is not None and wrapped.count("\n") + 1 > max_lines:
            continue
        tw, th = _measure_text(draw, wrapped, font, spacing=spacing)
        if tw <= max_width and th <= max_height:
            return wrapped, font
    font = _load_font(candidates, min_size)
    wrapped = _wrap_by_pixels(draw, text, font, max_width)
    if max_lines is not None:
        lines = wrapped.split("\n")[:max_lines]
        if lines:
            last = lines[-1]
            while draw.textbbox((0, 0), last + "…", font=font)[2] > max_width and len(last) > 1:
                last = last[:-1]
            lines[-1] = last + "…"
        wrapped = "\n".join(lines)
    return wrapped, font

def _rr(draw, box, radius, fill, outline=None, width=1):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def _draw_centered_text(draw, box, text, font, fill):
    x1, y1, x2, y2 = box
    bbox = draw.textbbox((0, 0), text, font=font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    tx = x1 + (x2 - x1 - tw) / 2
    ty = y1 + (y2 - y1 - th) / 2 - 2
    draw.text((tx, ty), text, font=font, fill=fill)


def _risk_colors(risk):
    r = str(risk).lower()
    if "low" in r:
        return ("#10301F", "#1E6B43", "#D8F8E8")
    if "mod" in r:
        return ("#36280C", "#A66B00", "#FFF0C2")
    return ("#3A1414", "#B63A3A", "#FFE0E0")


def _signal_colors(signal):
    s = str(signal).lower()
    if "strong" in s:
        return ("#102A20", "#1BAA6F", "#D8F8E8")
    if "steady" in s:
        return ("#12253A", "#3F83F8", "#DCEBFF")
    return ("#2B2B2B", "#6F7C8B", "#E7EDF5")


def _chain_colors(chain):
    c = str(chain).lower()
    if "eth" in c:
        return ("#1A1433", "#8B7CFF", "Ξ")
    if "base" in c:
        return ("#102543", "#3B82F6", "B")
    if "arb" in c:
        return ("#142434", "#7AA2FF", "A")
    return ("#1B2430", "#6F7C8B", "•")


def _token_colors(pool_name):
    p = str(pool_name).lower()
    if "merkl" in p:
        return ("#18251A", "#35C76F", "M")
    if "uniswap" in p:
        return ("#351228", "#FF5CA8", "U")
    if "aerodrome" in p:
        return ("#16241A", "#59D28C", "A")
    return ("#1B2430", "#AAB4C0", "T")


def _draw_badge(draw, x, y, size, fill, outline, glyph, glyph_fill, fonts, radius):
    _rr(draw, (x, y, x + size, y + size), radius, fill, outline=outline, width=max(1, size // 28))
    _draw_centered_text(draw, (x, y, x + size, y + size), glyph, fonts["sm_b"], glyph_fill)


def _draw_pill(draw, x, y, text, fill, outline, txt, fonts, pad_x, h, radius, outline_w):
    bbox = draw.textbbox((0, 0), text, font=fonts["xs"])
    w = (bbox[2] - bbox[0]) + pad_x * 2
    _rr(draw, (x, y, x + w, y + h), radius, fill, outline=outline, width=outline_w)
    text_y = y + max(1, int((h - (bbox[3] - bbox[1])) / 2)) - 2
    draw.text((x + pad_x, text_y), text, font=fonts["xs"], fill=txt)
    return w


def _draw_metric(draw, x, y, w, h, label, value, fonts, value_fill="#F4F7FB", pad_x=24, pad_y=20):
    _rr(draw, (x, y, x + w, y + h), max(14, int(h * 0.2)), "#10161D", outline="#202A35", width=max(1, int(h * 0.02)))
    draw.text((x + pad_x, y + pad_y), label.upper(), font=fonts["xs"], fill="#8D99A8")
    draw.text((x + pad_x, y + pad_y + max(28, int(h * 0.28))), value, font=fonts["sm_b"], fill=value_fill)


def _draw_sparkline(draw, box, values, line_color="#7AA2FF", fill_color="#12253A", grid_color="#17202A"):
    x1, y1, x2, y2 = box
    panel_h = y2 - y1
    _rr(draw, box, max(14, int(panel_h * 0.1)), "#10161D", outline="#202A35", width=max(1, int(panel_h * 0.01)))
    inset = max(14, int(panel_h * 0.08))
    gx1, gy1, gx2, gy2 = x1 + inset, y1 + inset, x2 - inset, y2 - inset
    for i in range(4):
        yy = gy1 + i * (gy2 - gy1) / 3
        draw.line((gx1, yy, gx2, yy), fill=grid_color, width=1)
    mn, mx = min(values), max(values)
    span = mx - mn if mx != mn else 1
    pts = []
    for i, v in enumerate(values):
        px = gx1 + i * (gx2 - gx1) / (len(values) - 1)
        py = gy2 - ((v - mn) / span) * (gy2 - gy1)
        pts.append((px, py))
    poly = [(pts[0][0], gy2)] + pts + [(pts[-1][0], gy2)]
    draw.polygon(poly, fill=fill_color)
    line_w = max(2, int(panel_h * 0.016))
    for i in range(len(pts) - 1):
        draw.line((pts[i], pts[i + 1]), fill=line_color, width=line_w)
    px, py = pts[-1]
    dot_r = max(4, int(panel_h * 0.025))
    draw.ellipse((px - dot_r, py - dot_r, px + dot_r, py + dot_r), fill=line_color)


def _mode_config(mode: str):
    mode = str(mode).lower()
    if mode == "preview":
        return {
            "canvas": (1800, 1013),
            "font_scale": 1.18,
            "wrap_width": 40,
            "compact": True,
            "safe_right": 1680,
        }
    return {
        "canvas": (2400, 1350),
        "font_scale": 1.34,
        "wrap_width": 54,
        "compact": False,
        "safe_right": 2240,
    }


def build_signal_card(
    pool_name="MERKL — HOLD",
    chain="ETHEREUM",
    apy="27.32%",
    tvl="$10.2M",
    strength="63/100",
    risk="Moderate",
    signal="Steady",
    why_text="Steady yield with healthy liquidity. More attractive for consistency than flashy short-lived spikes.",
    cta="Hold or rotate?",
    sparkline_values=None,
    out_path="signal_card_v3_square.png",
    mode="export",
):
    config = _mode_config(mode)
    W, H = config["canvas"]
    is_preview = config["compact"]
    SAFE_RIGHT = config["safe_right"]
    geometry_scale = W / 1600.0
    fonts = _fonts(scale=config["font_scale"])

    if sparkline_values is None:
        sparkline_values = [19, 22, 21, 24, 23, 26, 25, 27]

    img = Image.new("RGB", (W, H), "#090C10")
    draw = ImageDraw.Draw(img)

    grid_step = max(42, int(96 * geometry_scale))
    for y in range(0, H, grid_step):
        draw.line((0, y, W, y), fill="#0E1319", width=1)
    for x in range(0, W, grid_step):
        draw.line((x, 0, x, H), fill="#0C1117", width=1)

    outer_m = int(52 * geometry_scale)
    outer_r = max(18, int(36 * geometry_scale))
    _rr(draw, (outer_m, outer_m, W - outer_m, H - outer_m), outer_r, "#0D1117", outline="#1A2330", width=max(1, int(2 * geometry_scale)))

    badge_x1 = int(96 * geometry_scale)
    badge_y1 = int(96 * geometry_scale)
    badge_x2 = int(420 * geometry_scale)
    badge_y2 = int(170 * geometry_scale)
    _rr(draw, (badge_x1, badge_y1, badge_x2, badge_y2), max(12, int(20 * geometry_scale)), "#10161D", outline="#202A35", width=max(1, int(2 * geometry_scale)))
    draw.text((int(122 * geometry_scale), int(113 * geometry_scale)), "FuruFlow Alert", font=fonts["xs"], fill="#DCE5EF")

    token_fill, token_outline, token_glyph = _token_colors(pool_name)
    chain_fill, chain_outline, chain_glyph = _chain_colors(chain)
    icon_size = int(72 * geometry_scale)
    icon_y = int(92 * geometry_scale)
    badge_gap = int(18 * geometry_scale)
    badge2_x = SAFE_RIGHT - icon_size
    badge1_x = badge2_x - icon_size - badge_gap
    _draw_badge(draw, badge1_x, icon_y, icon_size, token_fill, token_outline, token_glyph, "#F4F7FB", fonts, max(12, icon_size // 2))
    _draw_badge(draw, badge2_x, icon_y, icon_size, chain_fill, chain_outline, chain_glyph, "#F4F7FB", fonts, max(12, icon_size // 2))

    title_box = (
        int(96 * geometry_scale),
        int(214 * geometry_scale),
        int((badge1_x - int(40 * geometry_scale))),
        int(292 * geometry_scale),
    )
    title_text, title_font = _fit_text_block(
        draw,
        pool_name,
        title_box,
        max_size=int(78 * config["font_scale"]),
        min_size=int(34 * config["font_scale"]),
        bold=True,
        spacing=max(4, int(8 * geometry_scale)),
        max_lines=2,
    )
    draw.multiline_text(
        (title_box[0], title_box[1]),
        title_text,
        font=title_font,
        fill="#F4F7FB",
        spacing=max(4, int(8 * geometry_scale)),
    )

    apy_box = (int(96 * geometry_scale), int(300 * geometry_scale), int(844 * geometry_scale), int(596 * geometry_scale))
    _rr(draw, apy_box, max(16, int(30 * geometry_scale)), "#10161D", outline="#202A35", width=max(1, int(2 * geometry_scale)))
    apy_text, apy_font = _fit_text_block(
        draw,
        apy,
        (apy_box[0] + int(26 * geometry_scale), apy_box[1] + int(12 * geometry_scale), apy_box[2] - int(26 * geometry_scale), apy_box[1] + int(176 * geometry_scale)),
        max_size=int(178 * config["font_scale"]),
        min_size=int(72 * config["font_scale"]),
        bold=True,
        max_lines=1,
    )
    draw.text((apy_box[0] + int(26 * geometry_scale), apy_box[1] + int(20 * geometry_scale)), apy_text, font=apy_font, fill="#F7FAFD")
    sub_text, sub_font = _fit_text_block(
        draw,
        "Annual percentage yield",
        (apy_box[0] + int(34 * geometry_scale), apy_box[1] + int(170 * geometry_scale), apy_box[2] - int(34 * geometry_scale), apy_box[2]),
        max_size=int(34 * config["font_scale"]),
        min_size=int(20 * config["font_scale"]),
        bold=False,
        max_lines=1,
    )
    draw.text((apy_box[0] + int(34 * geometry_scale), apy_box[1] + int(176 * geometry_scale)), sub_text, font=sub_font, fill="#8D99A8")

    rf, ro, rt = _risk_colors(risk)
    sf, so, st = _signal_colors(signal)
    pill_y = int(628 * geometry_scale)
    pill_h = max(38, int(48 * geometry_scale))
    pill_pad_x = max(14, int(18 * geometry_scale))
    pill_outline = max(1, int(2 * geometry_scale))
    pill_r = max(12, int(21 * geometry_scale))

    if is_preview:
        _draw_pill(draw, int(96 * geometry_scale), pill_y, f"Risk: {risk}", rf, ro, rt, fonts, pill_pad_x, pill_h, pill_r, pill_outline)
        _draw_pill(draw, int(96 * geometry_scale), pill_y + pill_h + int(14 * geometry_scale), f"Signal: {signal}", sf, so, st, fonts, pill_pad_x, pill_h, pill_r, pill_outline)
    else:
        w1 = _draw_pill(draw, int(96 * geometry_scale), pill_y, f"Risk: {risk}", rf, ro, rt, fonts, pill_pad_x, pill_h, pill_r, pill_outline)
        _draw_pill(draw, int(112 * geometry_scale) + w1, pill_y, f"Signal: {signal}", sf, so, st, fonts, pill_pad_x, pill_h, pill_r, pill_outline)

    if is_preview:
        metric_x = int(920 * geometry_scale)
        metric_w = int(640 * geometry_scale)
        metric_h = int(138 * geometry_scale)
        _draw_metric(draw, metric_x, int(214 * geometry_scale), metric_w, metric_h, "TVL", tvl, fonts, pad_x=max(16, int(24 * geometry_scale)), pad_y=max(14, int(20 * geometry_scale)))
        _draw_metric(draw, metric_x, int(374 * geometry_scale), metric_w, metric_h, "Strength", strength, fonts, pad_x=max(16, int(24 * geometry_scale)), pad_y=max(14, int(20 * geometry_scale)))
        spark_box = (metric_x, int(540 * geometry_scale), SAFE_RIGHT, int(820 * geometry_scale))
        summary_box = (int(96 * geometry_scale), int(760 * geometry_scale), int(860 * geometry_scale), int(930 * geometry_scale))
        summary_title_y = summary_box[1] + int(22 * geometry_scale)
        summary_text_y = summary_box[1] + int(70 * geometry_scale)
        footer_y = int(920 * geometry_scale)
    else:
        _draw_metric(draw, int(920 * geometry_scale), int(214 * geometry_scale), int(760 * geometry_scale), int(150 * geometry_scale), "TVL", tvl, fonts, pad_x=max(16, int(24 * geometry_scale)), pad_y=max(14, int(20 * geometry_scale)))
        _draw_metric(draw, int(920 * geometry_scale), int(392 * geometry_scale), int(760 * geometry_scale), int(150 * geometry_scale), "Strength", strength, fonts, pad_x=max(16, int(24 * geometry_scale)), pad_y=max(14, int(20 * geometry_scale)))
        spark_box = (int(920 * geometry_scale), int(580 * geometry_scale), SAFE_RIGHT, int(980 * geometry_scale))
        summary_box = (int(96 * geometry_scale), int(1030 * geometry_scale), int(1560 * geometry_scale), int(1280 * geometry_scale))
        summary_title_y = summary_box[1] + int(34 * geometry_scale)
        summary_text_y = summary_box[1] + int(98 * geometry_scale)
        footer_y = int(1265 * geometry_scale)

    _draw_sparkline(draw, spark_box, sparkline_values, line_color="#78A6FF", fill_color="#10233F")
    trend_label_box = (
        spark_box[0] + int(30 * geometry_scale),
        spark_box[1] + int(24 * geometry_scale),
        spark_box[2] - int(30 * geometry_scale),
        spark_box[1] + int(68 * geometry_scale),
    )
    trend_label_text, trend_label_font = _fit_text_block(
        draw, "Trend", trend_label_box,
        max_size=int(30 * config["font_scale"]),
        min_size=int(18 * config["font_scale"]),
        bold=False, max_lines=1
    )
    draw.text((trend_label_box[0], trend_label_box[1]), trend_label_text, font=trend_label_font, fill="#8D99A8")
    trend_title_box = (
        spark_box[0] + int(30 * geometry_scale),
        spark_box[1] + int(68 * geometry_scale),
        spark_box[2] - int(30 * geometry_scale),
        spark_box[1] + int(150 * geometry_scale),
    )
    trend_title_text, trend_title_font = _fit_text_block(
        draw, "APY / TVL sparkline", trend_title_box,
        max_size=int(46 * config["font_scale"]),
        min_size=int(22 * config["font_scale"]),
        bold=True, max_lines=2,
        spacing=max(2, int(6 * geometry_scale))
    )
    draw.multiline_text(
        (trend_title_box[0], trend_title_box[1]),
        trend_title_text,
        font=trend_title_font,
        fill="#EAF0F7",
        spacing=max(2, int(6 * geometry_scale)),
    )

    _rr(draw, summary_box, max(16, int(30 * geometry_scale)), "#10161D", outline="#202A35", width=max(1, int(2 * geometry_scale)))
    summary_title_box = (
        summary_box[0] + int(32 * geometry_scale),
        summary_box[1] + int(18 * geometry_scale),
        summary_box[2] - int(32 * geometry_scale),
        summary_box[1] + int(72 * geometry_scale),
    )
    summary_title_text, summary_title_font = _fit_text_block(
        draw, "Summary", summary_title_box,
        max_size=int(44 * config["font_scale"]),
        min_size=int(24 * config["font_scale"]),
        bold=True, max_lines=1
    )
    draw.text((summary_title_box[0], summary_title_box[1]), summary_title_text, font=summary_title_font, fill="#F1F5FA")
    summary_text_box = (
        summary_box[0] + int(32 * geometry_scale),
        summary_box[1] + int(76 * geometry_scale),
        summary_box[2] - int(32 * geometry_scale),
        summary_box[3] - int(20 * geometry_scale),
    )
    summary_text, summary_font = _fit_text_block(
        draw,
        why_text,
        summary_text_box,
        max_size=int(34 * config["font_scale"]),
        min_size=int(18 * config["font_scale"]),
        bold=False,
        max_lines=3 if is_preview else 4,
        spacing=max(4, int(8 * geometry_scale)),
    )
    draw.multiline_text(
        (summary_text_box[0], summary_text_box[1]),
        summary_text,
        font=summary_font,
        fill="#B6C0CC",
        spacing=max(4, int(8 * geometry_scale)),
    )

    footer_text_y = footer_y + int(18 * geometry_scale)
    draw.line((int(96 * geometry_scale), footer_y, SAFE_RIGHT, footer_y), fill="#1B2430", width=max(1, int(2 * geometry_scale)))
    cta_box = (int(96 * geometry_scale), footer_text_y, SAFE_RIGHT - int(220 * geometry_scale), footer_text_y + int(54 * geometry_scale))
    cta_text, cta_font = _fit_text_block(
        draw, cta, cta_box,
        max_size=int(40 * config["font_scale"]),
        min_size=int(22 * config["font_scale"]),
        bold=True, max_lines=1
    )
    draw.text((cta_box[0], cta_box[1]), cta_text, font=cta_font, fill="#F4F7FB")
    brand_text = "furuflow"
    brand_bbox = draw.textbbox((0, 0), brand_text, font=fonts["md_b"])
    brand_w = brand_bbox[2] - brand_bbox[0]
    brand_x = SAFE_RIGHT - brand_w
    draw.text((brand_x, footer_text_y), brand_text, font=fonts["md_b"], fill="#6F7C8B")

    img.save(out_path, format="PNG")


if __name__ == "__main__":
    build_signal_card(mode="preview", out_path="signal_card_preview.png")
    build_signal_card(mode="export", out_path="signal_card_export.png")
