#!/usr/bin/env python3
"""
Генератор кейс-каруселі для Instagram з даних рекламної кампанії Meta Ads.

Робить набір слайдів 1080×1350 (портрет 4:5) у стилі темного дашборду:
  1. Обкладинка          — ніша, назва РК, період, головний результат
  2. Задача              — що було на старті й яка ціль
  3. Ключові результати  — сітка метрик (витрати, покупки, CPP, CR, CPM, CTR)
  4. Динаміка            — графік CPP / покупок по днях
  5. Що робили           — підхід, гіпотези, оптимізації
  6. Підсумок            — головні цифри + висновок

Джерела даних (за пріоритетом):
  --data case.json       готовий JSON з полями кампанії (див. DEMO_CASE)
  --from-api "Клен"      підтягнути з Meta API усі РК, назва яких містить підрядок
  (без аргументів)       DEMO_CASE — демо-цифри-заповнювачі, які треба замінити

Приклади:
  python3 make_case.py                         # демо-рендер у ./case_out
  python3 make_case.py --data klen.json
  python3 make_case.py --from-api "Клен" --send # + відправити в Telegram

Залежності: matplotlib (pip install matplotlib). Для --send/--from-api — доступ
до graph.facebook.com / api.telegram.org.
"""
import sys, os, io, json, argparse
from datetime import datetime, timedelta

# ── ПАЛІТРА / СТИЛЬ ────────────────────────────────────────────
BG      = "#0d1117"   # фон слайда
CARD    = "#161b22"   # картки/панелі
LINE    = "#30363d"   # рамки
TXT     = "#e6edf3"   # основний текст
MUTE    = "#8b949e"   # приглушений текст
BLUE    = "#58a6ff"
GREEN   = "#3fb950"
ORANGE  = "#f0883e"
PURPLE  = "#a371f7"
RED     = "#f85149"
ACCENTS = [BLUE, GREEN, ORANGE, PURPLE]

W, H, DPI = 1080, 1350, 100  # 4:5 портрет

# ── ДЕМО-ДАНІ (ЗАМІНИ РЕАЛЬНИМИ) ───────────────────────────────
# Усі числа нижче — ПЛЕЙСХОЛДЕРИ для прев'ю. Підстав дані РК «Клен».
DEMO_CASE = {
    "brand":     "«Клен»",
    "niche":     "Товарка · дерев'яні кухонні дошки",
    "period":    "01.06 – 30.06.2026",
    "goal":      "Знизити CPP нижче $7 і масштабувати закупівлю без падіння якості ліда.",
    "start":     "Стартова ціна покупки $11.4, вузька аудиторія, 1 креатив.",
    "metrics": {
        "spend":     2840.0,   # витрати, $
        "purchases": 512,      # покупки, шт
        "cpp":       5.55,     # ціна за покупку, $
        "cr":        7.8,      # конверсія, %
        "cpm":       3.10,     # ціна за 1000 показів, $
        "ctr":       2.35,     # клікабельність, %
        "roas":      3.6,      # окупність (опційно, None щоб сховати)
    },
    "did": [
        "Розбили аудиторії на 4 сегменти + запустили broad із cost cap",
        "Зняли 6 нових UGC-креативів, залишили 2 з найкращим Hook Rate",
        "Перевели закупівлю на cost cap $6 і поетапно піднімали бюджет",
        "Прибрали плейсменти зі слабким CR, підсилили лендінг оффером",
    ],
    "outcome": "CPP $11.4 → $5.55 (−51%), обсяг ×3.2 за 30 днів, ROAS 3.6.",
    # Динаміка по днях: {date: {spend, purchases}}. Для демо — синтетика.
    "daily": None,
}

def _demo_daily():
    """Синтетична спадна крива CPP для демо-графіка."""
    base = datetime(2026, 6, 1)
    out = {}
    cpp = 11.4
    for i in range(30):
        d = (base + timedelta(days=i)).strftime("%Y-%m-%d")
        cpp = max(4.8, cpp - 0.22 + (0.35 if i % 5 == 0 else 0))
        purchases = int(6 + i * 0.9)
        out[d] = {"spend": round(cpp * purchases, 2), "purchases": purchases}
    return out


# ── META API (опційно) ────────────────────────────────────────
def case_from_api(name_filter, token, accounts, days=30):
    import urllib.request, urllib.parse
    until = datetime.utcnow().date()
    since = until - timedelta(days=days - 1)
    since_s, until_s = since.isoformat(), until.isoformat()

    def meta_get(url):
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())

    tot = {"spend": 0.0, "purchases": 0, "impressions": 0, "clicks": 0,
           "link_clicks": 0}
    daily = {}
    matched = []
    for acc in accounts:
        # агреговані метрики
        p = urllib.parse.urlencode({
            "fields": "campaign_name,spend,impressions,clicks,cpm,ctr,actions",
            "level": "campaign",
            "time_range": json.dumps({"since": since_s, "until": until_s}),
            "limit": 300, "access_token": token,
        })
        for row in meta_get(f"https://graph.facebook.com/v24.0/{acc}/insights?{p}").get("data", []):
            nm = row.get("campaign_name", "")
            if name_filter.lower() not in nm.lower():
                continue
            matched.append(nm)
            tot["spend"]       += float(row.get("spend", 0))
            tot["impressions"] += int(row.get("impressions", 0))
            tot["clicks"]      += int(row.get("clicks", 0))
            for a in row.get("actions", []):
                t, v = a.get("action_type"), int(float(a.get("value", 0)))
                if t == "purchase":   tot["purchases"]   += v
                if t == "link_click": tot["link_clicks"] += v
        # денний розбивка
        p2 = urllib.parse.urlencode({
            "fields": "campaign_name,spend,actions",
            "level": "campaign",
            "time_range": json.dumps({"since": since_s, "until": until_s}),
            "time_increment": 1, "limit": 500, "access_token": token,
        })
        for row in meta_get(f"https://graph.facebook.com/v24.0/{acc}/insights?{p2}").get("data", []):
            if name_filter.lower() not in row.get("campaign_name", "").lower():
                continue
            date = row.get("date_start", "")
            pur = 0
            for a in row.get("actions", []):
                if a.get("action_type") == "purchase":
                    pur += int(float(a.get("value", 0)))
            d = daily.setdefault(date, {"spend": 0.0, "purchases": 0})
            d["spend"]     += float(row.get("spend", 0))
            d["purchases"] += pur

    if not matched:
        sys.exit(f"❌ У Meta не знайдено РК з '{name_filter}' у назві.")

    spend, pur = tot["spend"], tot["purchases"]
    lc, impr, clk = tot["link_clicks"], tot["impressions"], tot["clicks"]
    case = dict(DEMO_CASE)
    case["brand"]  = f"«{name_filter}»"
    case["period"] = f"{since.strftime('%d.%m')} – {until.strftime('%d.%m.%Y')}"
    case["metrics"] = {
        "spend": round(spend, 2),
        "purchases": pur,
        "cpp": round(spend / pur, 2) if pur else None,
        "cr":  round(pur / lc * 100, 2) if lc else None,
        "cpm": round(spend / impr * 1000, 2) if impr else None,
        "ctr": round(clk / impr * 100, 2) if impr else None,
        "roas": None,
    }
    case["daily"] = daily
    case["goal"]  = case["start"] = case["outcome"] = ""
    case["did"]   = []
    return case


# ── РЕНДЕР ─────────────────────────────────────────────────────
def _new_slide():
    import matplotlib.pyplot as plt
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.axis("off")
    return fig, ax

def _save(fig, path):
    fig.savefig(path, facecolor=BG, dpi=DPI)
    import matplotlib.pyplot as plt
    plt.close(fig)

def _footer(ax, idx, total):
    ax.text(0.5, 0.035, "гортай →" if idx < total else "•", ha="center",
            va="center", color=MUTE, fontsize=15)
    # прогрес-крапки
    n = total
    xs = [0.5 + (i - (n - 1) / 2) * 0.03 for i in range(n)]
    for i, x in enumerate(xs):
        ax.plot(x, 0.075, "o", ms=6,
                color=(BLUE if i == idx - 1 else LINE))

def _kicker(ax, text, color=BLUE):
    ax.text(0.08, 0.9, text, ha="left", va="center", color=color,
            fontsize=20, fontweight="bold")
    ax.plot([0.08, 0.08], [0.86, 0.895], lw=4, color=color,
            solid_capstyle="round")

def _round_panel(ax, x, y, w, h, fc=CARD, ec=LINE):
    from matplotlib.patches import FancyBboxPatch
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.006,rounding_size=0.02",
                                fc=fc, ec=ec, lw=1.5, mutation_aspect=W / H))

def slide_cover(case, idx, total, out):
    fig, ax = _new_slide()
    ax.add_patch(__import__("matplotlib").patches.Rectangle((0, 0.97), 1, 0.03, color=BLUE))
    ax.text(0.08, 0.86, "КЕЙС", ha="left", va="center", color=BG, fontsize=22,
            fontweight="bold",
            bbox=dict(boxstyle="round,pad=0.5", fc=GREEN, ec="none"))
    ax.text(0.08, 0.78, case["niche"], ha="left", va="center", color=MUTE, fontsize=22)
    ax.text(0.08, 0.66, f"РК {case['brand']}", ha="left", va="center", color=TXT,
            fontsize=64, fontweight="bold")
    ax.text(0.08, 0.585, case["period"], ha="left", va="center", color=BLUE, fontsize=24)

    m = case["metrics"]
    hero_val, hero_lbl = None, ""
    if m.get("roas"):
        hero_val, hero_lbl = f"{m['roas']:.1f}", "ROAS — окупність реклами"
    elif m.get("cpp"):
        hero_val, hero_lbl = f"${m['cpp']:.2f}", "CPP — ціна за покупку"
    if hero_val:
        _round_panel(ax, 0.08, 0.24, 0.84, 0.22)
        ax.text(0.12, 0.4, hero_lbl, ha="left", va="center", color=MUTE, fontsize=22)
        ax.text(0.12, 0.31, hero_val, ha="left", va="center", color=GREEN,
                fontsize=90, fontweight="bold")
        if m.get("purchases"):
            ax.text(0.9, 0.31, f"{m['purchases']}\nпокупок", ha="right", va="center",
                    color=TXT, fontsize=30, fontweight="bold", linespacing=1.1)
    _footer(ax, idx, total)
    _save(fig, out); return out

def slide_task(case, idx, total, out):
    fig, ax = _new_slide()
    _kicker(ax, "ЗАДАЧА")
    blocks = [("Ціль", case.get("goal", ""), BLUE),
              ("На старті", case.get("start", ""), ORANGE)]
    y = 0.72
    for title, body, color in blocks:
        if not body:
            continue
        _round_panel(ax, 0.08, y - 0.18, 0.84, 0.2)
        ax.text(0.12, y - 0.02, title, ha="left", va="center", color=color,
                fontsize=26, fontweight="bold")
        ax.text(0.12, y - 0.1, _wrap(body, 34), ha="left", va="center", color=TXT,
                fontsize=23, linespacing=1.35)
        y -= 0.26
    _footer(ax, idx, total)
    _save(fig, out); return out

def slide_metrics(case, idx, total, out):
    fig, ax = _new_slide()
    _kicker(ax, "КЛЮЧОВІ РЕЗУЛЬТАТИ", GREEN)
    m = case["metrics"]
    cells = [
        ("Витрати",  f"${m['spend']:,.0f}".replace(",", " ") if m.get("spend") is not None else "—", BLUE),
        ("Покупки",  f"{m['purchases']}" if m.get("purchases") is not None else "—", GREEN),
        ("CPP",      f"${m['cpp']:.2f}" if m.get("cpp") else "—", ORANGE),
        ("CR",       f"{m['cr']:.1f}%" if m.get("cr") else "—", PURPLE),
        ("CPM",      f"${m['cpm']:.2f}" if m.get("cpm") else "—", BLUE),
        ("CTR",      f"{m['ctr']:.2f}%" if m.get("ctr") else "—", GREEN),
    ]
    # сітка 2×3
    x0, gw, gh, gx, gy = 0.08, 0.4, 0.17, 0.04, 0.025
    for i, (lbl, val, color) in enumerate(cells):
        r, c = divmod(i, 2)
        x = x0 + c * (gw + gx)
        y = 0.74 - r * (gh + gy)
        _round_panel(ax, x, y - gh, gw, gh)
        ax.text(x + 0.03, y - 0.045, lbl, ha="left", va="center", color=MUTE, fontsize=21)
        ax.text(x + 0.03, y - 0.125, val, ha="left", va="center", color=color,
                fontsize=46, fontweight="bold")
    _footer(ax, idx, total)
    _save(fig, out); return out

def slide_chart(case, idx, total, out):
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    daily = case.get("daily") or {}
    if len(daily) < 3:
        return None
    fig, ax0 = _new_slide()
    _kicker(ax0, "ДИНАМІКА", ORANGE)
    dates = sorted(daily)
    dobj  = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
    cpp   = [round(daily[d]["spend"] / daily[d]["purchases"], 2) if daily[d]["purchases"] else 0 for d in dates]
    pur   = [daily[d]["purchases"] for d in dates]

    # покупки — стовпчики (внизу), CPP — лінія (зверху)
    axp = fig.add_axes([0.1, 0.14, 0.82, 0.30]); _style_axis(axp)
    axp.bar(dobj, pur, color=GREEN, alpha=0.85, width=0.7)
    axp.set_title("Покупки / день", color=TXT, fontsize=20, fontweight="bold", loc="left", pad=8)

    axc = fig.add_axes([0.1, 0.52, 0.82, 0.30]); _style_axis(axc)
    axc.plot(dobj, cpp, color=BLUE, lw=3, marker="o", ms=5)
    axc.fill_between(dobj, cpp, alpha=0.12, color=BLUE)
    axc.set_title("CPP, $  (нижче = краще)", color=TXT, fontsize=20, fontweight="bold", loc="left", pad=8)
    if cpp[0] and cpp[-1]:
        axc.annotate(f"${cpp[0]:.1f}", (dobj[0], cpp[0]), color=ORANGE, fontsize=16,
                     fontweight="bold", xytext=(0, 8), textcoords="offset points")
        axc.annotate(f"${cpp[-1]:.1f}", (dobj[-1], cpp[-1]), color=GREEN, fontsize=16,
                     fontweight="bold", ha="right", xytext=(0, 8), textcoords="offset points")
    for ax in (axp, axc):
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates) // 6)))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=0, fontsize=13, color=MUTE)
    _footer(ax0, idx, total)
    _save(fig, out); return out

def slide_did(case, idx, total, out):
    did = case.get("did") or []
    if not did:
        return None
    fig, ax = _new_slide()
    _kicker(ax, "ЩО РОБИЛИ", PURPLE)
    y = 0.76
    for i, item in enumerate(did[:5]):
        color = ACCENTS[i % len(ACCENTS)]
        ax.add_patch(__import__("matplotlib").patches.Circle((0.11, y), 0.022,
                     color=color, transform=ax.transData))
        ax.text(0.11, y, str(i + 1), ha="center", va="center", color=BG,
                fontsize=20, fontweight="bold")
        ax.text(0.17, y, _wrap(item, 32), ha="left", va="center", color=TXT,
                fontsize=24, linespacing=1.3)
        y -= 0.145
    _footer(ax, idx, total)
    _save(fig, out); return out

def slide_outcome(case, idx, total, out):
    fig, ax = _new_slide()
    _kicker(ax, "ПІДСУМОК", GREEN)
    m = case["metrics"]
    _round_panel(ax, 0.08, 0.46, 0.84, 0.30, fc="#0f2417", ec=GREEN)
    ax.text(0.12, 0.7, "Результат", ha="left", va="center", color=GREEN,
            fontsize=24, fontweight="bold")
    ax.text(0.12, 0.58, _wrap(case.get("outcome", ""), 34), ha="left", va="center",
            color=TXT, fontsize=27, linespacing=1.35)
    # рядок головних цифр
    trio = []
    if m.get("cpp"):       trio.append((f"${m['cpp']:.2f}", "CPP"))
    if m.get("purchases"): trio.append((f"{m['purchases']}", "покупок"))
    if m.get("roas"):      trio.append((f"{m['roas']:.1f}", "ROAS"))
    elif m.get("cr"):      trio.append((f"{m['cr']:.1f}%", "CR"))
    for i, (val, lbl) in enumerate(trio[:3]):
        x = 0.08 + i * 0.29
        ax.text(x + 0.13, 0.34, val, ha="center", va="center", color=ACCENTS[i],
                fontsize=48, fontweight="bold")
        ax.text(x + 0.13, 0.27, lbl, ha="center", va="center", color=MUTE, fontsize=20)
    ax.text(0.5, 0.13, "Хочеш так само? — напиши в директ",
            ha="center", va="center", color=TXT, fontsize=24, fontweight="bold")
    _footer(ax, idx, total)
    _save(fig, out); return out


# ── УТИЛІТИ ────────────────────────────────────────────────────
def _style_axis(ax):
    ax.set_facecolor(CARD)
    ax.tick_params(colors=MUTE, labelsize=12)
    for s in ax.spines.values():
        s.set_color(LINE)
    ax.grid(axis="y", color=LINE, alpha=0.3, lw=0.6)

def _wrap(text, width):
    import textwrap
    return "\n".join(textwrap.wrap(text, width=width)) if text else ""


# ── TELEGRAM ───────────────────────────────────────────────────
def send_album(paths, token, chat_id, caption=""):
    import urllib.request
    boundary = "----CaseBoundary9x"
    media = []
    parts = []
    for i, p in enumerate(paths):
        key = f"photo{i}"
        media.append({"type": "photo", "media": f"attach://{key}",
                      **({"caption": caption, "parse_mode": "HTML"} if i == 0 and caption else {})})
        with open(p, "rb") as f:
            data = f.read()
        head = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"; "
                f"filename=\"{os.path.basename(p)}\"\r\nContent-Type: image/png\r\n\r\n").encode()
        parts.append(head + data + b"\r\n")
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{chat_id}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"media\"\r\n\r\n{json.dumps(media)}\r\n").encode()
    body += b"".join(parts)
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMediaGroup",
                                 data=body, headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("ok", False)


def build(case, outdir):
    import matplotlib
    matplotlib.use("Agg")
    os.makedirs(outdir, exist_ok=True)
    if case.get("daily") is None:
        case["daily"] = _demo_daily()

    # (builder, чи є дані для слайда). Порядок = порядок у каруселі.
    m = case["metrics"]
    plan = [
        (slide_cover,   True),
        (slide_task,    bool(case.get("goal") or case.get("start"))),
        (slide_metrics, True),
        (slide_chart,   len(case.get("daily") or {}) >= 3),
        (slide_did,     bool(case.get("did"))),
        (slide_outcome, True),
    ]
    active = [b for b, ok in plan if ok]
    total = len(active)
    paths = []
    for i, b in enumerate(active, 1):
        p = os.path.join(outdir, f"slide_{i:02d}.png")
        b(case, i, total, p)
        paths.append(p)
    return paths


def main():
    ap = argparse.ArgumentParser(description="Instagram carousel case generator")
    ap.add_argument("--data", help="JSON-файл з даними кейсу")
    ap.add_argument("--from-api", help="Підтягнути РК з Meta API за підрядком у назві")
    ap.add_argument("--out", default="case_out", help="Тека для слайдів (default: case_out)")
    ap.add_argument("--send", action="store_true", help="Відправити альбом у Telegram")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as f:
            case = json.load(f)
    elif args.from_api:
        token = os.environ.get("META_TOKEN")
        if not token:
            sys.exit("❌ Задай META_TOKEN у середовищі для --from-api")
        accounts = os.environ.get("META_ACCOUNTS",
                                  "act_1387877018668243,act_599050058732938").split(",")
        case = case_from_api(args.from_api, token, accounts)
        print("ℹ️  Дані підтягнуто з Meta. Заповни goal/start/did/outcome вручну для повного кейсу.")
    else:
        case = DEMO_CASE
        print("⚠️  Використано ДЕМО-цифри (плейсхолдери). Заповни реальні дані РК «Клен».")

    paths = build(case, args.out)
    print(f"✅ Слайди: {', '.join(paths)}")

    if args.send:
        tg_token = os.environ.get("TG_TOKEN")
        tg_chat  = os.environ.get("TG_CHAT_ID")
        if not (tg_token and tg_chat):
            sys.exit("❌ Задай TG_TOKEN і TG_CHAT_ID для --send")
        cap = f"📎 Кейс РК {case.get('brand','')} — {case.get('period','')}"
        print("📤 Відправлено!" if send_album(paths, tg_token, tg_chat, cap) else "❌ Помилка відправки")


if __name__ == "__main__":
    main()
