#!/usr/bin/env python3
"""
Meta Ads Daily Reporter → Telegram
Звіт 1: Косметички (всі РК з 'kosmet' в назві — Товарка 7 + Аромо)
Звіт 2: Всі інші РК (Товарка 7 + Аромо, включно з вимкненими за день)
"""
import sys, json, io, os
import urllib.request, urllib.parse
from datetime import datetime, timedelta
import pytz

TG_TOKEN   = os.environ.get("TG_TOKEN", "8636205250:AAER0fGj1rBtP1DPZGgM3QbGlhdOSk2Uj8o")
TG_CHAT_ID = "399905488"
META_TOKEN = os.environ.get("META_TOKEN", "EAALFMGdfPjkBQzRwZAjW7kwvyWfZBp4E7DzTzrxGHNmXy13h0rgiBMWoimZAowMZAz25VuH7gSYWoyhCerkhZBvGQY5UJc3dZALPpM5F8GkIp21snuaEU9cIutxMhL0snhcXfI5wG1sKDmTs5btiJgpkrQqWSbB4tbinrShSdeZALPapF9EvKHQ05b45hYnFZAeN")
KYIV_TZ    = pytz.timezone("Europe/Kyiv")

ACCOUNTS = {
    "act_1387877018668243": "Товарка 7",
    "act_599050058732938":  "Аромо",
}
KOSMET_KW      = "kosmet"
TARGET_CPP_MAX = 7.00
TARGET_CR_MIN  = 5.0
TARGET_CPM_MAX = 4.00

# ── META API ──────────────────────────────────────────────────
def meta_get(url):
    with urllib.request.urlopen(url, timeout=30) as r:
        return json.loads(r.read())

def get_insights(account_id, since, until):
    fields = "campaign_name,spend,impressions,clicks,cpm,ctr,actions,reach,frequency"
    params = urllib.parse.urlencode({
        "fields": fields,
        "level": "campaign",
        "time_range": json.dumps({"since": since, "until": until}),
        "limit": 200,
        "access_token": META_TOKEN,
    })
    data = meta_get(f"https://graph.facebook.com/v24.0/{account_id}/insights?{params}").get("data", [])
    results = []
    for row in data:
        spend = float(row.get("spend", 0))
        if spend < 0.01: continue
        impressions = int(row.get("impressions", 0))
        cpm = float(row.get("cpm", 0))
        ctr = float(row.get("ctr", 0))
        frequency = float(row.get("frequency", 0))
        purchases = link_clicks = video_views = 0
        for a in row.get("actions", []):
            t, v = a.get("action_type"), int(float(a.get("value", 0)))
            if t == "purchase":   purchases   = v
            if t == "link_click": link_clicks = v
            if t == "video_view": video_views = v
        results.append({
            "name":        row.get("campaign_name", ""),
            "spend":       spend,
            "purchases":   purchases,
            "link_clicks": link_clicks,
            "impressions": impressions,
            "cpm":         cpm,
            "ctr":         ctr,
            "cr":          round(purchases/link_clicks*100, 2) if link_clicks > 0 else 0.0,
            "cpp":         round(spend/purchases, 2) if purchases > 0 else None,
            "hook_rate":   round(video_views/impressions*100, 2) if impressions > 0 else 0.0,
            "frequency":   frequency,
        })
    return results

def get_daily_breakdown(account_id, since, until, name_filter=None):
    fields = "campaign_name,spend,actions,clicks,impressions"
    params = urllib.parse.urlencode({
        "fields": fields,
        "level": "campaign",
        "time_range": json.dumps({"since": since, "until": until}),
        "time_increment": 1,
        "limit": 500,
        "access_token": META_TOKEN,
    })
    raw = meta_get(f"https://graph.facebook.com/v24.0/{account_id}/insights?{params}").get("data", [])
    by_day = {}
    for row in raw:
        name = row.get("campaign_name", "")
        if name_filter and name_filter.lower() not in name.lower(): continue
        date = row.get("date_start", "")
        spend = float(row.get("spend", 0))
        if spend < 0.01: continue
        purchases = link_clicks = 0
        for a in row.get("actions", []):
            t, v = a.get("action_type"), int(float(a.get("value", 0)))
            if t == "purchase":   purchases   = v
            if t == "link_click": link_clicks = v
        if date not in by_day:
            by_day[date] = {"spend":0,"purchases":0,"link_clicks":0}
        by_day[date]["spend"]       += spend
        by_day[date]["purchases"]   += purchases
        by_day[date]["link_clicks"] += link_clicks
    result = {}
    for date, d in sorted(by_day.items()):
        result[date] = {
            "spend":     d["spend"],
            "purchases": d["purchases"],
            "cpp":       round(d["spend"]/d["purchases"], 2) if d["purchases"] > 0 else None,
            "cr":        round(d["purchases"]/d["link_clicks"]*100, 2) if d["link_clicks"] > 0 else 0.0,
            "link_clicks": d["link_clicks"],
        }
    return result

# ── TELEGRAM ──────────────────────────────────────────────────
def send_text(text):
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage"
    payload = json.dumps({"chat_id":TG_CHAT_ID,"text":text,"parse_mode":"HTML","disable_web_page_preview":True}).encode()
    req = urllib.request.Request(url, data=payload, headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read()).get("ok", False)

def send_photo(img_bytes, caption=""):
    boundary = "----Boundary7MA4YW"
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n{TG_CHAT_ID}\r\n"
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"photo\"; filename=\"chart.png\"\r\nContent-Type: image/png\r\n\r\n").encode()
    body += img_bytes
    body += (f"\r\n--{boundary}\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n{caption}\r\n--{boundary}--\r\n").encode()
    url = f"https://api.telegram.org/bot{TG_TOKEN}/sendPhoto"
    req = urllib.request.Request(url, data=body, headers={"Content-Type":f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read()).get("ok", False)

# ── ГРАФІКИ ───────────────────────────────────────────────────
def make_chart(by_day, title):
    try:
        import matplotlib; matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
    except ImportError:
        return None
    dates = sorted(by_day.keys())
    if len(dates) < 2: return None
    date_objs  = [datetime.strptime(d, "%Y-%m-%d") for d in dates]
    cpp_vals   = [by_day[d]["cpp"] or 0 for d in dates]
    spend_vals = [by_day[d]["spend"] for d in dates]
    pur_vals   = [by_day[d]["purchases"] for d in dates]
    cr_vals    = [by_day[d]["cr"] for d in dates]

    fig, axes = plt.subplots(2, 2, figsize=(12, 7))
    fig.patch.set_facecolor("#0d1117")
    for ax in axes.flat:
        ax.set_facecolor("#161b22")
        ax.tick_params(colors="#c9d1d9", labelsize=8)
        ax.spines[:].set_color("#30363d")
        ax.xaxis.set_major_formatter(mdates.DateFormatter("%d.%m"))
        ax.xaxis.set_major_locator(mdates.DayLocator(interval=max(1, len(dates)//7)))
        plt.setp(ax.xaxis.get_majorticklabels(), rotation=45, ha="right", fontsize=7, color="#8b949e")

    # CPP
    ax = axes[0][0]
    ax.plot(date_objs, cpp_vals, color="#58a6ff", lw=2.5, marker="o", ms=5)
    ax.fill_between(date_objs, cpp_vals, alpha=0.12, color="#58a6ff")
    ax.axhline(y=TARGET_CPP_MAX, color="#f85149", ls="--", lw=1.2, alpha=0.7, label=f"Ціль ${TARGET_CPP_MAX}")
    ax.set_title("💵 CPP ($)", color="#e6edf3", fontsize=10, fontweight="bold", pad=8)
    ax.legend(fontsize=7, labelcolor="#f85149", facecolor="#161b22", edgecolor="#30363d")
    for i, (x, y) in enumerate(zip(date_objs, cpp_vals)):
        if y > 0: ax.annotate(f"${y:.2f}", (x, y), textcoords="offset points",
                               xytext=(0,6), ha="center", fontsize=6.5, color="#58a6ff")

    # Витрати
    ax = axes[0][1]
    bars = ax.bar(date_objs, spend_vals, color="#7c3aed", width=0.6, alpha=0.85)
    ax.set_title("💰 Витрати ($)", color="#e6edf3", fontsize=10, fontweight="bold", pad=8)
    for bar, val in zip(bars, spend_vals):
        ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.5,
                f"${val:.0f}", ha="center", va="bottom", fontsize=6.5, color="#c9d1d9")

    # Покупки
    ax = axes[1][0]
    bars = ax.bar(date_objs, pur_vals, color="#3fb950", width=0.6, alpha=0.85)
    ax.set_title("🛒 Покупки", color="#e6edf3", fontsize=10, fontweight="bold", pad=8)
    for bar, val in zip(bars, pur_vals):
        if val > 0:
            ax.text(bar.get_x()+bar.get_width()/2, bar.get_height()+0.1,
                    str(val), ha="center", va="bottom", fontsize=7, color="#c9d1d9")

    # CR
    ax = axes[1][1]
    ax.plot(date_objs, cr_vals, color="#f0883e", lw=2.5, marker="s", ms=5)
    ax.fill_between(date_objs, cr_vals, alpha=0.12, color="#f0883e")
    ax.axhline(y=TARGET_CR_MIN, color="#f85149", ls="--", lw=1.2, alpha=0.7, label=f"Ціль {TARGET_CR_MIN}%")
    ax.set_title("📈 CR (%)", color="#e6edf3", fontsize=10, fontweight="bold", pad=8)
    ax.legend(fontsize=7, labelcolor="#f85149", facecolor="#161b22", edgecolor="#30363d")
    for x, y in zip(date_objs, cr_vals):
        if y > 0: ax.annotate(f"{y:.1f}%", (x, y), textcoords="offset points",
                               xytext=(0,6), ha="center", fontsize=6.5, color="#f0883e")

    fig.suptitle(title, color="#e6edf3", fontsize=12, fontweight="bold", y=1.01)
    plt.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format="png", dpi=130, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    buf.seek(0)
    return buf.read()

# ── АНАЛІЗ ────────────────────────────────────────────────────
def analyze(r):
    issues, positives = [], []
    cpp, cr, cpm = r["cpp"], r["cr"], r["cpm"]
    spend, purchases = r["spend"], r["purchases"]

    if purchases == 0 and spend >= 10:
        status = "🔴"; issues.append("нуль покупок при значних витратах — перевір піксель та лендінг")
    elif purchases == 0 and spend < 10:
        status = "🟡"; issues.append("ще немає покупок (навчання, мало даних)")
    elif cpp and cpp > TARGET_CPP_MAX * 1.3:
        status = "🔴"; issues.append(f"CPP критично вище норми — розглянь вимкнення або зміну cost cap")
    elif cpp and cpp > TARGET_CPP_MAX:
        status = "🟡"; issues.append(f"CPP трохи вище цілі ${TARGET_CPP_MAX} — спостерігати")
    else:
        status = "🟢"

    if cpm > TARGET_CPM_MAX * 1.5: issues.append(f"дуже дорогий трафік CPM ${cpm:.2f}")
    elif cpm > TARGET_CPM_MAX: issues.append(f"CPM ${cpm:.2f} вище норми")
    else: positives.append(f"дешевий трафік CPM ${cpm:.2f}")

    if cr > 0 and cr < TARGET_CR_MIN: issues.append(f"слабка конверсія CR {cr}% (ціль >{TARGET_CR_MIN}%)")
    elif cr >= TARGET_CR_MIN: positives.append(f"конверсія в нормі CR {cr}%")

    if r["hook_rate"] > 0:
        if r["hook_rate"] < 15: issues.append(f"слабкий Hook Rate {r['hook_rate']}% — відео не чіпляє в перші секунди")
        elif r["hook_rate"] >= 25: positives.append(f"сильний Hook Rate {r['hook_rate']}%")

    if r["frequency"] > 2.5: issues.append(f"висока частота {r['frequency']:.1f} — аудиторія вигорає")

    return status, issues, positives

def format_rk(r):
    status, issues, positives = analyze(r)
    cpp_str  = f"${r['cpp']:.2f}" if r["cpp"] else "—"
    cr_str   = f"{r['cr']:.1f}%"
    hook_str = f"{r['hook_rate']:.1f}%" if r["hook_rate"] > 0 else "—"
    name_s   = r["name"][:44] + ("…" if len(r["name"]) > 44 else "")
    lines = [
        f"\n{status} <b>{name_s}</b>",
        f"├ 💰 Витрати:  <b>${r['spend']:.2f}</b>",
        f"├ 🛒 Покупки:  <b>{r['purchases']}</b>",
        f"├ 💵 CPP:      <b>{cpp_str}</b>",
        f"├ 📈 CR:       <b>{cr_str}</b>",
        f"├ 📡 CPM:      <b>${r['cpm']:.2f}</b>",
        f"├ 🎬 Hook:     <b>{hook_str}</b>",
        f"└ 🖱 CTR/Freq: <b>{r['ctr']:.2f}% / {r['frequency']:.1f}</b>",
    ]
    if issues:
        for i in issues:
            lines.append(f"   ⚠️ {i}")
    if positives:
        for p in positives:
            lines.append(f"   ✅ {p}")
    return "\n".join(lines)

def format_account_block(rows, acc_name):
    total_spend = sum(r["spend"] for r in rows)
    total_pur   = sum(r["purchases"] for r in rows)
    total_lc    = sum(r["link_clicks"] for r in rows)
    total_impr  = sum(r["impressions"] for r in rows)
    total_cpp   = round(total_spend/total_pur, 2) if total_pur > 0 else None
    total_cr    = round(total_pur/total_lc*100, 2) if total_lc > 0 else 0
    avg_cpm     = round(sum(r["cpm"]*r["impressions"] for r in rows)/max(total_impr,1), 2)
    cpp_str     = f"${total_cpp:.2f}" if total_cpp else "—"

    sorted_rows = sorted(rows, key=lambda x: (x["purchases"]==0, -x["spend"]))
    lines = [f"\n🏪 <b>{acc_name}</b>"]
    for r in sorted_rows:
        lines.append(format_rk(r))
    lines += [
        f"\n{'━'*30}",
        f"📊 <b>РАЗОМ {acc_name}</b>",
        f"├ 💰 Витрати:  <b>${total_spend:.2f}</b>",
        f"├ 🛒 Покупки:  <b>{total_pur}</b>",
        f"├ 💵 CPP:      <b>{cpp_str}</b>",
        f"├ 📈 CR:       <b>{total_cr}%</b>",
        f"└ 📡 CPM:      <b>${avg_cpm}</b>",
    ]
    if total_cpp and total_cpp <= TARGET_CPP_MAX and total_cr >= TARGET_CR_MIN:
        lines.append("💡 <i>Акаунт працює добре — тримати курс</i>")
    elif total_pur == 0:
        lines.append("💡 <i>Немає покупок — перевір статуси РК та піксель</i>")
    elif total_cpp and total_cpp > TARGET_CPP_MAX*1.2:
        lines.append("💡 <i>CPP вище норми — переглянь cost cap рівні</i>")
    return "\n".join(lines)

def summary_header(all_rows, emoji, title, date_label):
    total_spend = sum(r["spend"] for r in all_rows)
    total_pur   = sum(r["purchases"] for r in all_rows)
    total_lc    = sum(r["link_clicks"] for r in all_rows)
    total_cpp   = round(total_spend/total_pur, 2) if total_pur > 0 else None
    total_cr    = round(total_pur/total_lc*100, 2) if total_lc > 0 else 0
    cpp_str     = f"${total_cpp:.2f}" if total_cpp else "—"

    if total_cpp and total_cpp <= TARGET_CPP_MAX and total_cr >= TARGET_CR_MIN:
        grade = "🟢 Добрий день"
    elif total_cpp and total_cpp <= TARGET_CPP_MAX*1.15:
        grade = "🟡 Нормальний день"
    else:
        grade = "🔴 Складний день — потрібна увага"

    cpp_diff = ""
    if total_cpp:
        diff = total_cpp - TARGET_CPP_MAX
        cpp_diff = f" <i>({'↑' if diff>0 else '↓'}${abs(diff):.2f} {'від' if diff>0 else 'нижче'} ліміту)</i>"

    return (
        f"{emoji} <b>{title}</b>  |  {date_label}\n"
        f"{'═'*35}\n"
        f"{grade}\n\n"
        f"💰 Витрати:  <b>${total_spend:.2f}</b>\n"
        f"🛒 Покупки:  <b>{total_pur}</b>\n"
        f"💵 CPP:      <b>{cpp_str}</b>{cpp_diff}\n"
        f"📈 CR:       <b>{total_cr}%</b>  (ціль >{TARGET_CR_MIN}%)\n"
    )

# ── DAILY ─────────────────────────────────────────────────────
def run_daily():
    now = datetime.now(KYIV_TZ)
    yesterday   = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    date_label  = (now - timedelta(days=1)).strftime("%d.%m.%Y")
    since_7d    = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    print(f"📊 Збираю дані за {yesterday}...")

    for kw, emoji, title in [(KOSMET_KW,"🧴","КОСМЕТИЧКИ"),(None,"🏢","ІНШІ РК")]:
        all_rows, by_acc = [], {}
        for acc_id, acc_name in ACCOUNTS.items():
            rows = get_insights(acc_id, yesterday, yesterday)
            if kw:
                filtered = [r for r in rows if kw.lower() in r["name"].lower()]
            else:
                filtered = [r for r in rows if KOSMET_KW.lower() not in r["name"].lower()]
            if filtered:
                all_rows.extend(filtered)
                by_acc[acc_name] = filtered

        if not all_rows:
            send_text(f"{emoji} <b>{title} | {date_label}</b>\n📭 Немає РК з витратами")
            continue

        send_text(summary_header(all_rows, emoji, title, date_label))
        for acc_name, rows in by_acc.items():
            send_text(format_account_block(rows, acc_name))

        # Графік 7 днів
        combined = {}
        for acc_id in ACCOUNTS:
            day_data = get_daily_breakdown(acc_id, since_7d, yesterday, kw)
            for date, d in day_data.items():
                if date not in combined:
                    combined[date] = {"spend":0,"purchases":0,"link_clicks":0}
                combined[date]["spend"]       += d["spend"]
                combined[date]["purchases"]   += d["purchases"]
                combined[date]["link_clicks"] += d.get("link_clicks",0)
        for date in combined:
            d = combined[date]
            d["cpp"] = round(d["spend"]/d["purchases"],2) if d["purchases"]>0 else None
            d["cr"]  = round(d["purchases"]/d["link_clicks"]*100,2) if d["link_clicks"]>0 else 0.0

        if len(combined) >= 3:
            chart = make_chart(combined, f"{emoji} {title} — динаміка 7 днів")
            if chart:
                send_photo(chart, f"📈 {title} | 7 днів до {date_label}")

    print("✅ Готово!")

# ── WEEKLY ────────────────────────────────────────────────────
def run_weekly():
    now = datetime.now(KYIV_TZ)
    since = (now - timedelta(days=now.weekday()+7)).strftime("%Y-%m-%d")
    until = (now - timedelta(days=now.weekday()+1)).strftime("%Y-%m-%d")
    s_l = datetime.strptime(since,"%Y-%m-%d").strftime("%d.%m")
    u_l = datetime.strptime(until,"%Y-%m-%d").strftime("%d.%m.%Y")
    week_label = f"{s_l}–{u_l}"
    print(f"📅 Тижневий {week_label}")

    for kw, emoji, title in [(KOSMET_KW,"🧴","КОСМЕТИЧКИ"),(None,"🏢","ІНШІ РК")]:
        all_rows = []
        for acc_id, acc_name in ACCOUNTS.items():
            rows = get_insights(acc_id, since, until)
            filtered = [r for r in rows if kw.lower() in r["name"].lower()] if kw \
                  else [r for r in rows if KOSMET_KW.lower() not in r["name"].lower()]
            all_rows.extend(filtered)
        if not all_rows: continue

        total_spend = sum(r["spend"] for r in all_rows)
        total_pur   = sum(r["purchases"] for r in all_rows)
        total_lc    = sum(r["link_clicks"] for r in all_rows)
        total_cpp   = round(total_spend/total_pur,2) if total_pur>0 else None
        total_cr    = round(total_pur/total_lc*100,2) if total_lc>0 else 0
        cpp_str     = f"${total_cpp:.2f}" if total_cpp else "—"

        top   = sorted([r for r in all_rows if r["cpp"]], key=lambda x: x["cpp"])[:3]
        worst = [r for r in sorted([r for r in all_rows if r["cpp"]],
                 key=lambda x: x["cpp"], reverse=True) if r not in top][:2]

        lines = [
            f"{emoji} <b>{title} — тижневий підсумок</b>",
            f"📅 {week_label}",
            f"{'═'*35}",
            f"💰 Витрати: <b>${total_spend:.2f}</b>",
            f"🛒 Покупки: <b>{total_pur}</b>",
            f"💵 CPP: <b>{cpp_str}</b>",
            f"📈 CR: <b>{total_cr}%</b>",
            "",
            "🏆 <b>Топ РК (найдешевша покупка):</b>",
        ]
        for r in top:
            lines.append(f"  ✅ {r['name'][:38]} — CPP ${r['cpp']:.2f} | CR {r['cr']:.1f}%")
        if worst:
            lines.append("\n⚠️ <b>Проблемні РК:</b>")
            for r in worst:
                lines.append(f"  🔴 {r['name'][:38]} — CPP ${r['cpp']:.2f} | CR {r['cr']:.1f}%")
        send_text("\n".join(lines))

        # Графік тижня
        combined = {}
        for acc_id in ACCOUNTS:
            day_data = get_daily_breakdown(acc_id, since, until, kw)
            for date, d in day_data.items():
                if date not in combined:
                    combined[date] = {"spend":0,"purchases":0,"link_clicks":0}
                combined[date]["spend"]       += d["spend"]
                combined[date]["purchases"]   += d["purchases"]
                combined[date]["link_clicks"] += d.get("link_clicks",0)
        for date in combined:
            d = combined[date]
            d["cpp"] = round(d["spend"]/d["purchases"],2) if d["purchases"]>0 else None
            d["cr"]  = round(d["purchases"]/d["link_clicks"]*100,2) if d["link_clicks"]>0 else 0.0
        if len(combined) >= 3:
            chart = make_chart(combined, f"{emoji} {title} — тиждень {week_label}")
            if chart: send_photo(chart, f"📈 {title} | тиждень {week_label}")

    print("✅ Тижневий звіт готово!")

# ── TEST ──────────────────────────────────────────────────────
def run_test():
    now = datetime.now(KYIV_TZ).strftime("%d.%m.%Y %H:%M")
    ok = send_text(
        f"✅ <b>Meta Ads Reporter — підключено!</b>\n\n"
        f"🕐 {now} (Київ)\n\n"
        f"<b>Звіти:</b>\n"
        f"🧴 Косметички — всі РК з <code>kosmet</code> в назві\n"
        f"🏢 Інші РК — всі решта (включно з вимкненими за день)\n\n"
        f"<b>Акаунти:</b> Товарка 7 · Аромо\n\n"
        f"<b>Метрики:</b> CPP · CR · CPM · CTR · Hook Rate · Frequency\n"
        f"<b>Графіки:</b> CPP / Витрати / Покупки / CR — динаміка 7 днів\n\n"
        f"<b>Розклад:</b>\n"
        f"📊 Щоденний — 08:00\n"
        f"📅 Тижневий — пн 08:30"
    )
    print("✅ Тест відправлено!" if ok else "❌ Помилка — перевір токени")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "test"
    if   mode == "daily":   run_daily()
    elif mode == "weekly":  run_weekly()
    elif mode == "test":    run_test()
    else: print("Використання: python3 meta_report.py [daily|weekly|test]")
