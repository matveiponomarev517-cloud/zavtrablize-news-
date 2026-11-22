"""Обложки: фон (картинка от ИИ или процедурный градиент) + фирменное оформление."""
import base64
import io
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
_HERE = os.path.dirname(os.path.abspath(__file__))
FONT_PATHS = [
    os.path.join(_HERE, "fonts", "DejaVuSans-Bold.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]
LABELS = {
    "news": "НОВОСТЬ",
    "explain": "ПРОСТЫМИ СЛОВАМИ",
    "question": "ВОПРОС",
    "longread": "ЛОНГРИД",
    "digest": "ИТОГИ НЕДЕЛИ",
    "history": "СЕГОДНЯ В ИСТОРИИ НАУКИ",
}
PALETTES = [
    ((8, 18, 48), (70, 25, 120)),
    ((4, 38, 58), (12, 120, 125)),
    ((28, 8, 48), (160, 45, 95)),
    ((6, 18, 40), (28, 95, 170)),
    ((14, 14, 34), (95, 65, 170)),
]


def _font(size):
    for p in FONT_PATHS:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    raise RuntimeError("Не найден шрифт с кириллицей (fonts/DejaVuSans-Bold.ttf)")


def extract_image(resp):
    """Достаёт байты изображения из ответа Gemini (inlineData / inline_data)."""
    for cand in resp.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    return None


def _gradient_bg(seed):
    rnd = random.Random(seed)
    c1, c2 = rnd.choice(PALETTES)
    img = Image.new("RGB", (W, H))
    d = ImageDraw.Draw(img)
    for y in range(H):
        t = y / (H - 1)
        d.line([(0, y), (W, y)], fill=tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    for _ in range(5):
        r = rnd.randint(120, 300)
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        col = tuple(min(255, v + rnd.randint(40, 110)) for v in rnd.choice(PALETTES)[1])
        g.ellipse([x - r, y - r, x + r, y + r], fill=col + (70,))
    glow = glow.filter(ImageFilter.GaussianBlur(70))
    img = Image.alpha_composite(img.convert("RGBA"), glow)

    d = ImageDraw.Draw(img)
    for _ in range(90):
        x, y, s = rnd.randint(0, W), rnd.randint(0, H), rnd.choice((1, 1, 2, 3))
        d.ellipse([x, y, x + s, y + s], fill=(255, 255, 255, rnd.randint(90, 230)))
    return img.convert("RGB")


def _ai_bg(data):
    img = Image.open(io.BytesIO(data)).convert("RGB")
    w, h = img.size
    target = W / H
    if w / h > target:
        nw = int(h * target)
        img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
    else:
        nh = int(w / target)
        img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    return img.resize((W, H), Image.LANCZOS)


def _wrap(draw, text, font, max_w):
    lines, cur = [], ""
    for word in text.split():
        test = (cur + " " + word).strip()
        if draw.textlength(test, font=font) <= max_w or not cur:
            cur = test
        else:
            lines.append(cur)
            cur = word
    if cur:
        lines.append(cur)
    return lines


def render(title, kind="news", seed="", ai_image=None):
    """Возвращает JPEG 1280x720 в байтах."""
    bg = _ai_bg(ai_image) if ai_image else _gradient_bg(seed)

    # затемнение снизу: заголовок всегда читается
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    top = int(H * 0.28)
    for y in range(top, H):
        sd.line([(0, y), (W, y)], fill=(0, 0, 0, int(225 * ((y - top) / (H - top)) ** 0.9)))
    sd.rectangle([0, 0, W, 90], fill=(0, 0, 0, 90))
    img = Image.alpha_composite(bg.convert("RGBA"), shade)
    d = ImageDraw.Draw(img)

    pad = 70
    label = "ЗАВТРА БЛИЖЕ  ·  " + LABELS.get(kind, "НОВОСТЬ")
    d.text((pad, 30), label, font=_font(26), fill=(255, 205, 90))

    title = " ".join((title or "").split()) or "Завтра ближе"
    for size in (70, 62, 54, 46, 40):
        f = _font(size)
        lines = _wrap(d, title, f, W - 2 * pad)
        if len(lines) <= 3:
            break
    lines = lines[:3]
    line_h = int(size * 1.22)
    y = H - 60 - line_h * len(lines)
    d.rectangle([pad, y - 22, pad + 90, y - 16], fill=(255, 205, 90))
    for ln in lines:
        d.text((pad + 2, y + 2), ln, font=f, fill=(0, 0, 0, 160))
        d.text((pad, y), ln, font=f, fill=(255, 255, 255))
        y += line_h

    out = io.BytesIO()
    img.convert("RGB").save(out, "JPEG", quality=88)
    return out.getvalue()
