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
            sz(22),
        ),
        "sm": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            sz(28),
        ),
        "sm_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(28),
        ),
        "md": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            sz(34),
        ),
        "md_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(36),
        ),
        "lg_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(56),
        ),
        "xl_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            sz(116),
        ),
    }


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
            "size": 720,
            "font_scale": 1.9,
            "wrap_width": 30,
        }
    return {
        "size": 1600,
        "font_scale": 1.0,
        "wrap_width": 56,
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
    W = H = config["size"]
    scale = W / 1600.0
    font_scale = config["font_scale"]
    fonts = _fonts(scale=font_scale)

    if sparkline_values is None:
        sparkline_values = [19, 22, 21, 24, 23, 26, 25, 27]

    img = Image.new("RGB", (W, H), "#090C10")
    draw = ImageDraw.Draw(img)

    grid_step = max(42, int(96 * scale))
    for y in range(0, H, grid_step):
        draw.line((0, y, W, y), fill="#0E1319", width=1)
    for x in range(0, W, grid_step):
        draw.line((x, 0, x, H), fill="#0C1117", width=1)

    outer_m = int(52 * scale)
    outer_r = max(18, int(36 * scale))
    _rr(draw, (outer_m, outer_m, W - outer_m, H - outer_m), outer_r, "#0D1117", outline="#1A2330", width=max(1, int(2 * scale)))

    badge_x1 = int(96 * scale)
    badge_y1 = int(96 * scale)
    badge_x2 = int(380 * scale)
    badge_y2 = int(156 * scale)
    _rr(draw, (badge_x1, badge_y1, badge_x2, badge_y2), max(12, int(20 * scale)), "#10161D", outline="#202A35", width=max(1, int(2 * scale)))
    draw.text((int(122 * scale), int(113 * scale)), "FuruFlow Alert", font=fonts["xs"], fill="#DCE5EF")

    token_fill, token_outline, token_glyph = _token_colors(pool_name)
    chain_fill, chain_outline, chain_glyph = _chain_colors(chain)
    icon_size = int(64 * scale)
    icon_y = int(92 * scale)
    _draw_badge(draw, int(1260 * scale), icon_y, icon_size, token_fill, token_outline, token_glyph, "#F4F7FB", fonts, max(12, icon_size // 2))
    _draw_badge(draw, int(1338 * scale), icon_y, icon_size, chain_fill, chain_outline, chain_glyph, "#F4F7FB", fonts, max(12, icon_size // 2))

    draw.text((int(96 * scale), int(214 * scale)), pool_name, font=fonts["lg_b"], fill="#F4F7FB")

    apy_box = (int(96 * scale), int(300 * scale), int(844 * scale), int(584 * scale))
    _rr(draw, apy_box, max(16, int(30 * scale)), "#10161D", outline="#202A35", width=max(1, int(2 * scale)))
    draw.text((int(132 * scale), int(340 * scale)), apy, font=fonts["xl_b"], fill="#F7FAFD")
    draw.text((int(138 * scale), int(478 * scale)), "Annual percentage yield", font=fonts["sm"], fill="#8D99A8")

    rf, ro, rt = _risk_colors(risk)
    sf, so, st = _signal_colors(signal)
    pill_y = int(618 * scale)
    pill_h = max(34, int(42 * scale))
    pill_pad_x = max(12, int(17 * scale))
    pill_outline = max(1, int(2 * scale))
    pill_r = max(12, int(21 * scale))
    w1 = _draw_pill(draw, int(96 * scale), pill_y, f"Risk: {risk}", rf, ro, rt, fonts, pill_pad_x, pill_h, pill_r, pill_outline)
    _draw_pill(draw, int(112 * scale) + w1, pill_y, f"Signal: {signal}", sf, so, st, fonts, pill_pad_x, pill_h, pill_r, pill_outline)

    _draw_metric(draw, int(884 * scale), int(214 * scale), int(620 * scale), int(130 * scale), "TVL", tvl, fonts, pad_x=max(16, int(24 * scale)), pad_y=max(14, int(20 * scale)))
    _draw_metric(draw, int(884 * scale), int(364 * scale), int(620 * scale), int(130 * scale), "Strength", strength, fonts, pad_x=max(16, int(24 * scale)), pad_y=max(14, int(20 * scale)))

    spark_box = (int(884 * scale), int(514 * scale), int(1504 * scale), int(760 * scale))
    _draw_sparkline(draw, spark_box, sparkline_values, line_color="#78A6FF", fill_color="#10233F")
    draw.text((int(914 * scale), int(544 * scale)), "Trend", font=fonts["xs"], fill="#8D99A8")
    draw.text((int(914 * scale), int(582 * scale)), "APY / TVL sparkline", font=fonts["sm_b"], fill="#EAF0F7")

    summary_box = (int(96 * scale), int(794 * scale), int(1400 * scale), int(1078 * scale))
    _rr(draw, summary_box, max(16, int(30 * scale)), "#10161D", outline="#202A35", width=max(1, int(2 * scale)))
    draw.text((int(128 * scale), int(830 * scale)), "Summary", font=fonts["md_b"], fill="#F1F5FA")

    wrapped = textwrap.fill(why_text, width=config["wrap_width"])
    draw.text((int(128 * scale), int(892 * scale)), wrapped, font=fonts["md"], fill="#B6C0CC", spacing=max(6, int(12 * scale)))

    footer_y = int(1160 * scale)
    draw.line((int(96 * scale), footer_y, int(1504 * scale), footer_y), fill="#1B2430", width=max(1, int(2 * scale)))
    draw.text((int(96 * scale), int(1198 * scale)), cta, font=fonts["md_b"], fill="#F4F7FB")
    draw.text((int(1318 * scale), int(1198 * scale)), "furuflow", font=fonts["md_b"], fill="#6F7C8B")

    img.save(out_path, quality=95)


if __name__ == "__main__":
    build_signal_card()
