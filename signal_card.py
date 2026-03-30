from PIL import Image, ImageDraw, ImageFont
import textwrap


from PIL import ImageFont
from pathlib import Path
import os

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

def _fonts():
    windows_font_dir = Path("C:/Windows/Fonts")
    linux_font_dir = Path("/usr/share/fonts/truetype/dejavu")

    return {
        "xs": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            22,
        ),
        "sm": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            28,
        ),
        "sm_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            28,
        ),
        "md": _load_font(
            [
                windows_font_dir / "arial.ttf",
                windows_font_dir / "segoeui.ttf",
                linux_font_dir / "DejaVuSans.ttf",
            ],
            34,
        ),
        "md_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            36,
        ),
        "lg_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            56,
        ),
        "xl_b": _load_font(
            [
                windows_font_dir / "arialbd.ttf",
                windows_font_dir / "segoeuib.ttf",
                linux_font_dir / "DejaVuSans-Bold.ttf",
            ],
            116,
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
    r = risk.lower()
    if "low" in r:
        return ("#10301F", "#1E6B43", "#D8F8E8")
    if "mod" in r:
        return ("#36280C", "#A66B00", "#FFF0C2")
    return ("#3A1414", "#B63A3A", "#FFE0E0")

def _signal_colors(signal):
    s = signal.lower()
    if "strong" in s:
        return ("#102A20", "#1BAA6F", "#D8F8E8")
    if "steady" in s:
        return ("#12253A", "#3F83F8", "#DCEBFF")
    return ("#2B2B2B", "#6F7C8B", "#E7EDF5")

def _chain_colors(chain):
    c = chain.lower()
    if "eth" in c:
        return ("#1A1433", "#8B7CFF", "Ξ")
    if "base" in c:
        return ("#102543", "#3B82F6", "B")
    if "arb" in c:
        return ("#142434", "#7AA2FF", "A")
    return ("#1B2430", "#6F7C8B", "•")

def _token_colors(pool_name):
    p = pool_name.lower()
    if "merkl" in p:
        return ("#18251A", "#35C76F", "M")
    if "uniswap" in p:
        return ("#351228", "#FF5CA8", "U")
    if "aerodrome" in p:
        return ("#16241A", "#59D28C", "A")
    return ("#1B2430", "#AAB4C0", "T")

def _draw_badge(draw, x, y, size, fill, outline, glyph, glyph_fill, fonts):
    _rr(draw, (x, y, x+size, y+size), size//2, fill, outline=outline, width=2)
    _draw_centered_text(draw, (x, y, x+size, y+size), glyph, fonts["sm_b"], glyph_fill)

def _draw_pill(draw, x, y, text, fill, outline, txt, fonts):
    bbox = draw.textbbox((0, 0), text, font=fonts["xs"])
    w = (bbox[2]-bbox[0]) + 34
    h = 42
    _rr(draw, (x, y, x+w, y+h), 21, fill, outline=outline, width=2)
    draw.text((x+17, y+8), text, font=fonts["xs"], fill=txt)
    return w

def _draw_metric(draw, x, y, w, h, label, value, fonts, value_fill="#F4F7FB"):
    _rr(draw, (x, y, x+w, y+h), 26, "#10161D", outline="#202A35", width=2)
    draw.text((x+24, y+20), label.upper(), font=fonts["xs"], fill="#8D99A8")
    draw.text((x+24, y+58), value, font=fonts["sm_b"], fill=value_fill)

def _draw_sparkline(draw, box, values, line_color="#7AA2FF", fill_color="#12253A"):
    x1, y1, x2, y2 = box
    _rr(draw, box, 24, "#10161D", outline="#202A35", width=2)
    inset = 20
    gx1, gy1, gx2, gy2 = x1+inset, y1+inset, x2-inset, y2-inset
    for i in range(4):
        yy = gy1 + i*(gy2-gy1)/3
        draw.line((gx1, yy, gx2, yy), fill="#17202A", width=1)
    mn, mx = min(values), max(values)
    span = mx - mn if mx != mn else 1
    pts = []
    for i, v in enumerate(values):
        px = gx1 + i*(gx2-gx1)/(len(values)-1)
        py = gy2 - ((v-mn)/span)*(gy2-gy1)
        pts.append((px, py))
    poly = [(pts[0][0], gy2)] + pts + [(pts[-1][0], gy2)]
    draw.polygon(poly, fill=fill_color)
    for i in range(len(pts)-1):
        draw.line((pts[i], pts[i+1]), fill=line_color, width=4)
    px, py = pts[-1]
    draw.ellipse((px-7, py-7, px+7, py+7), fill=line_color)

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
    out_path="signal_card_v3_square.png"
):
    fonts = _fonts()
    if sparkline_values is None:
        sparkline_values = [19, 22, 21, 24, 23, 26, 25, 27]
    W = H = 1600
    img = Image.new("RGB", (W, H), "#090C10")
    draw = ImageDraw.Draw(img)

    for y in range(0, H, 96):
        draw.line((0, y, W, y), fill="#0E1319", width=1)
    for x in range(0, W, 96):
        draw.line((x, 0, x, H), fill="#0C1117", width=1)

    _rr(draw, (52, 52, W-52, H-52), 36, "#0D1117", outline="#1A2330", width=2)

    _rr(draw, (96, 96, 380, 156), 20, "#10161D", outline="#202A35", width=2)
    draw.text((122, 113), "FuruFlow Alert", font=fonts["xs"], fill="#DCE5EF")

    token_fill, token_outline, token_glyph = _token_colors(pool_name)
    chain_fill, chain_outline, chain_glyph = _chain_colors(chain)
    _draw_badge(draw, 1260, 92, 64, token_fill, token_outline, token_glyph, "#F4F7FB", fonts)
    _draw_badge(draw, 1338, 92, 64, chain_fill, chain_outline, chain_glyph, "#F4F7FB", fonts)

    draw.text((96, 214), pool_name, font=fonts["lg_b"], fill="#F4F7FB")
    _rr(draw, (96, 300, 844, 584), 30, "#10161D", outline="#202A35", width=2)
    draw.text((132, 340), apy, font=fonts["xl_b"], fill="#F7FAFD")
    draw.text((138, 478), "Annual percentage yield", font=fonts["sm"], fill="#8D99A8")

    rf, ro, rt = _risk_colors(risk)
    sf, so, st = _signal_colors(signal)
    w1 = _draw_pill(draw, 96, 618, f"Risk: {risk}", rf, ro, rt, fonts)
    _draw_pill(draw, 112 + w1, 618, f"Signal: {signal}", sf, so, st, fonts)

    _draw_metric(draw, 884, 214, 620, 130, "TVL", tvl, fonts)
    _draw_metric(draw, 884, 364, 620, 130, "Strength", strength, fonts)
    _draw_sparkline(draw, (884, 514, 1504, 760), sparkline_values, line_color="#78A6FF", fill_color="#10233F")
    draw.text((914, 544), "Trend", font=fonts["xs"], fill="#8D99A8")
    draw.text((914, 582), "APY / TVL sparkline", font=fonts["sm_b"], fill="#EAF0F7")

    _rr(draw, (96, 794, 1400, 1078), 30, "#10161D", outline="#202A35", width=2)
    draw.text((128, 830), "Summary", font=fonts["md_b"], fill="#F1F5FA")
    draw.text((128, 892), textwrap.fill(why_text, width=56), font=fonts["md"], fill="#B6C0CC", spacing=12)

    draw.line((96, 1160, 1504, 1160), fill="#1B2430", width=2)
    draw.text((96, 1198), cta, font=fonts["md_b"], fill="#F4F7FB")
    draw.text((1318, 1198), "furuflow", font=fonts["md_b"], fill="#6F7C8B")

    img.save(out_path, quality=95)

if __name__ == "__main__":
    build_signal_card()
