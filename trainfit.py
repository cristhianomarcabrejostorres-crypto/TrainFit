from __future__ import annotations

import json
import logging
import os
from dotenv import load_dotenv
load_dotenv()
import re
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional

from telegram import BotCommand, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.constants import ParseMode
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN: str = os.getenv("BOT_TOKEN", "PEGA_AQUI_TU_TOKEN_DE_BOTFATHER")
ADMIN_ID: int = int(os.getenv("ADMIN_ID", "0"))
DATA_FILE: str = os.getenv("DATA_FILE", "powerfit_data.json")
REMINDER_HOUR: int = int(os.getenv("REMINDER_HOUR", "8"))
REMINDER_MINUTE: int = int(os.getenv("REMINDER_MINUTE", "0"))
MAX_HISTORY: int = 20

Data = Dict[str, Any]

def load_data() -> Data:
    if not os.path.exists(DATA_FILE):
        return {"users": {}}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
        data.setdefault("users", {})
        return data

def save_data(data: Data) -> None:
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def _get_user(data: Data, user_id: int) -> Dict[str, Any]:
    uid = str(user_id)
    if uid not in data["users"]:
        data["users"][uid] = {
            "username": None,
            "last_sport": None,
            "last_level": None,
            "history": [],
            "favorites": [],
            "reminders": False,
        }
    return data["users"][uid]

def record_selection(user_id: int, username: Optional[str], sport: str, level: str) -> None:
    data = load_data()
    user = _get_user(data, user_id)
    user["username"] = username
    user["last_sport"] = sport
    user["last_level"] = level
    user["history"].append({
        "sport": sport,
        "level": level,
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    })
    user["history"] = user["history"][-MAX_HISTORY:]
    save_data(data)

def get_history(user_id: int, limit: int = 5) -> List[Dict[str, str]]:
    data = load_data()
    user = data["users"].get(str(user_id))
    if not user:
        return []
    return list(reversed(user["history"]))[:limit]

def get_last_selection(user_id: int) -> Optional[Dict[str, str]]:
    data = load_data()
    user = data["users"].get(str(user_id))
    if not user or not user.get("last_sport"):
        return None
    return {"sport": user["last_sport"], "level": user["last_level"]}

def toggle_favorite(user_id: int, sport: str, level: str) -> bool:
    data = load_data()
    user = _get_user(data, user_id)
    entry = {"sport": sport, "level": level}
    if entry in user["favorites"]:
        user["favorites"].remove(entry)
        save_data(data)
        return False
    user["favorites"].append(entry)
    save_data(data)
    return True

def is_favorite(user_id: int, sport: str, level: str) -> bool:
    data = load_data()
    user = data["users"].get(str(user_id))
    if not user:
        return False
    return {"sport": sport, "level": level} in user["favorites"]

def get_favorites(user_id: int) -> List[Dict[str, str]]:
    data = load_data()
    user = data["users"].get(str(user_id))
    if not user:
        return []
    return user["favorites"]

def toggle_reminder(user_id: int) -> bool:
    data = load_data()
    user = _get_user(data, user_id)
    user["reminders"] = not user["reminders"]
    save_data(data)
    return user["reminders"]

def get_reminders_enabled(user_id: int) -> bool:
    data = load_data()
    user = data["users"].get(str(user_id))
    return bool(user and user.get("reminders"))

def get_reminder_subscribers() -> List[Dict[str, Any]]:
    data = load_data()
    result = []
    for uid, user in data["users"].items():
        if user.get("reminders") and user.get("last_sport"):
            result.append({
                "user_id": int(uid),
                "sport": user["last_sport"],
                "level": user["last_level"],
            })
    return result

def get_stats() -> Dict[str, Any]:
    data = load_data()
    users = data["users"]
    sport_counts: Dict[str, int] = {}
    level_counts: Dict[str, int] = {}
    reminder_count = 0
    favorites_count = 0

    for user in users.values():
        if user.get("last_sport"):
            sport_counts[user["last_sport"]] = sport_counts.get(user["last_sport"], 0) + 1
        if user.get("last_level"):
            level_counts[user["last_level"]] = level_counts.get(user["last_level"], 0) + 1
        if user.get("reminders"):
            reminder_count += 1
        favorites_count += len(user.get("favorites", []))

    return {
        "total_users": len(users),
        "sport_counts": sport_counts,
        "level_counts": level_counts,
        "reminder_subscribers": reminder_count,
        "total_favorites": favorites_count,
    }

SPORT_INFO: Dict[str, Dict[str, str]] = {
    "gym": {"emoji": "🏋️", "name": "Gimnasio"},
    "atletismo": {"emoji": "🏃", "name": "Atletismo"},
    "natacion": {"emoji": "🏊", "name": "Natación"},
}

LEVEL_INFO: Dict[str, Dict[str, str]] = {
    "principiante": {"emoji": "🥉", "name": "Principiante"},
    "intermedio": {"emoji": "🥈", "name": "Intermedio"},
    "avanzado": {"emoji": "🥇", "name": "Avanzado"},
}

WEEKDAYS: List[str] = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]

FOOTER_NOTE = (
    "📌 *Notas generales*\n"
    "• Calienta 10–15 min antes de empezar.\n"
    "• Enfría y estira 5–10 min al terminar.\n"
    "• Ajusta cargas/ritmos a tu sensación del día, prioriza la técnica.\n"
    "• Hidrátate durante toda la sesión."
)

def _header(emoji: str, sport_name: str, level_name: str, objetivo: str) -> str:
    return (
        f"{emoji} *{sport_name} — NIVEL {level_name.upper()}*\n"
        f"_Rutina semanal de entrenamiento_\n\n"
        f"🎯 *Objetivo de la semana:* {objetivo}\n"
    )

def weeks_text(sport: str, level: str) -> str:

    if sport == "gym":
        if level == "principiante":
            body = (
                "*Lunes — Pierna + Core*\n"
                "• Sentadilla goblet — 3×10\n"
                "• Peso muerto rumano — 3×10\n"
                "• Zancadas — 2×10 por pierna\n"
                "• Plancha — 3×30–45 s\n\n"
                "*Martes — Torso (empuje)*\n"
                "• Press de pecho con mancuernas — 3×10\n"
                "• Flexiones inclinadas — 2×AMRAP\n"
                "• Press militar — 3×10\n"
                "• Tríceps en polea — 2×12\n\n"
                "*Miércoles — Descanso activo*\n"
                "• Caminata 30–45 min + estiramientos\n\n"
                "*Jueves — Torso (tirón) + espalda*\n"
                "• Remo con mancuerna — 3×10 por brazo\n"
                "• Jalón al pecho — 3×10\n"
                "• Face pulls — 2×12\n"
                "• Curl de bíceps — 3×10\n\n"
                "*Viernes — Full body suave*\n"
                "• Bisagra de cadera (RDL) — 2×12\n"
                "• Sentadilla a caja — 2×10\n"
                "• Press — 2×10\n"
                "• Remo — 2×10\n"
                "• Core: dead bug — 3×10\n\n"
                "*Sábado / Domingo — Descanso*"
            )
            return _header("🏋️", "GIMNASIO", level, "construir base técnica y adaptación muscular.") + "\n" + body + "\n\n" + FOOTER_NOTE

        if level == "intermedio":
            body = (
                "*Lunes — Pierna (fuerza)*\n"
                "• Sentadilla frontal — 4×6–8\n"
                "• Peso muerto rumano — 3×8\n"
                "• Prensa — 3×10\n"
                "• Gemelos — 3×12–15\n"
                "• Plancha lateral — 3×30–45 s\n\n"
                "*Martes — Torso (empuje) + core*\n"
                "• Press banca con barra — 4×6–8\n"
                "• Press inclinado con mancuernas — 3×10\n"
                "• Elevaciones laterales — 3×12\n"
                "• Rueda abdominal / crunch en polea — 3×10–12\n\n"
                "*Miércoles — Cardio + movilidad*\n"
                "• Intervalos 20–25 min (1:1 o 2:2)\n\n"
                "*Jueves — Torso (tirón) + hombro*\n"
                "• Dominadas asistidas / jalón — 4×6–8\n"
                "• Remo con barra — 3×8\n"
                "• Remo en polea — 2×10\n"
                "• Face pulls — 3×12\n"
                "• Curl martillo — 3×10\n\n"
                "*Viernes — Full body (hipertrofia)*\n"
                "• Zancadas caminando — 3×10 por pierna\n"
                "• Sentadilla parcial — 3×8\n"
                "• Press militar — 3×8–10\n"
                "• Jalón al pecho — 2×12\n"
                "• Core: hanging leg raise — 3×8–12\n\n"
                "*Sábado / Domingo — Descanso*"
            )
            return _header("🏋️", "GIMNASIO", level, "ganar fuerza e hipertrofia con progresión controlada.") + "\n" + body + "\n\n" + FOOTER_NOTE

        body = (
            "*Lunes — Pierna (intensidad alta)*\n"
            "• Sentadilla trasera — 5×3–5\n"
            "• Peso muerto — 3×3–5\n"
            "• Hip thrust — 4×6\n"
            "• Curl femoral — 3×10–12\n"
            "• Core: rueda abdominal — 4×6–10\n\n"
            "*Martes — Torso (empuje) pesado + accesorios*\n"
            "• Press banca — 5×3–5\n"
            "• Press militar — 4×4–6\n"
            "• Superserie: elevaciones laterales 3×12 + tríceps overhead 3×10–12\n\n"
            "*Miércoles — Cardio / recuperación*\n"
            "• Zona 2 — 35–50 min + movilidad 15 min\n\n"
            "*Jueves — Torso (tirón) pesado*\n"
            "• Remo con barra — 5×3–5\n"
            "• Dominadas lastradas — 4×4–6\n"
            "• Jalón neutro — 3×8–10\n"
            "• Face pulls — 4×12–15\n\n"
            "*Viernes — Full body power / volumen*\n"
            "• Sentadilla (ligera/moderada) — 3×5\n"
            "• Peso muerto rumano — 4×6–8\n"
            "• Press inclinado — 4×8\n"
            "• Remo — 3×10\n"
            "• Core: L-sit o plancha avanzada — 4×25–40 s\n\n"
            "*Sábado / Domingo — Descanso*"
        )
        return _header("🏋️", "GIMNASIO", level, "maximizar fuerza y potencia con cargas altas.") + "\n" + body + "\n\n" + FOOTER_NOTE

    if sport == "atletismo":
        if level == "principiante":
            body = (
                "*Lunes — Técnica + trote*\n"
                "• Movilidad dinámica — 10 min\n"
                "• Skipping A/B — 4×20 m\n"
                "• Trote suave — 20–25 min\n\n"
                "*Martes — Fuerza de carrera (suave)*\n"
                "• 6×20 s progresivos (descanso 60–90 s)\n"
                "• Multisaltos cortos — 3×6 (intensidad suave)\n\n"
                "*Miércoles — Descanso activo*\n"
                "• Caminata + estiramientos — 20–30 min\n\n"
                "*Jueves — Series cortas (básico)*\n"
                "• 8×200 m a ritmo cómodo (descanso 60–90 s)\n"
                "• 4×30 s técnica de zancada\n\n"
                "*Viernes — Terreno variable o trote*\n"
                "• 25–35 min trote + 4 aceleraciones de 10–15 s\n\n"
                "*Sábado / Domingo — Descanso*"
            )
            return _header("🏃", "ATLETISMO", level, "desarrollar base aeróbica y técnica de carrera.") + "\n" + body + "\n\n" + FOOTER_NOTE

        if level == "intermedio":
            body = (
                "*Lunes — Técnica + fuerza ligera*\n"
                "• Técnica de carrera progresiva — 20 min\n"
                "• Skipping 6×20 m + multisaltos 4×5\n"
                "• Trote — 15–20 min\n\n"
                "*Martes — Tempo (controlado)*\n"
                "• Calentamiento\n"
                "• 3×8 min a ritmo sostenible (descanso 3 min)\n"
                "• Enfriamiento — 8–10 min\n\n"
                "*Miércoles — Recuperación*\n"
                "• Zona 1–2, 25–35 min + movilidad\n\n"
                "*Jueves — Series 400–600 m*\n"
                "• 10×400 m (descanso 90 s) o 8×500 m (descanso 2 min)\n"
                "• 4×20 m aceleraciones\n\n"
                "*Viernes — Cuestas + técnica*\n"
                "• 6× cuesta de 20–30 s (bajada como recuperación)\n"
                "• Drills — 10 min\n"
                "• Trote — 10–15 min\n\n"
                "*Sábado / Domingo — Descanso*"
            )
            return _header("🏃", "ATLETISMO", level, "elevar capacidad de umbral y economía de carrera.") + "\n" + body + "\n\n" + FOOTER_NOTE

        body = (
            "*Lunes — Técnica + fuerza específica*\n"
            "• Drills — 20–25 min\n"
            "• Multisaltos completos — 5×5–6\n"
            "• Trote — 15–20 min\n\n"
            "*Martes — Intervalos VO2máx*\n"
            "• 5×800 m a ritmo alto (descanso 2–3 min) o 6×600 m (descanso 2 min)\n\n"
            "*Miércoles — Recuperación activa*\n"
            "• 30–45 min suave + movilidad 15 min\n\n"
            "*Jueves — Series de velocidad*\n"
            "• 12×200 m (descanso 60–75 s) a ritmo rápido\n"
            "• 6×60 m aceleraciones finales\n\n"
            "*Viernes — Cuestas (potencia)*\n"
            "• 10×30 s cuesta fuerte (bajada completa como recuperación)\n"
            "• Enfriamiento — 10 min\n\n"
            "*Sábado — Aeróbico opcional*\n"
            "• 45–60 min zona 2\n\n"
            "*Domingo — Descanso*"
        )
        return _header("🏃", "ATLETISMO", level, "maximizar velocidad, potencia y VO2máx.") + "\n" + body + "\n\n" + FOOTER_NOTE

    if level == "principiante":
        body = (
            "*Lunes — Técnica + base*\n"
            "• 6×25 m (descanso 30–45 s) estilo cómodo\n"
            "• 4×50 m suave (descanso 45–60 s)\n"
            "• 4×25 m patada con tabla (descanso 30 s)\n\n"
            "*Martes — Técnica de respiración*\n"
            "• 8×25 m respiración controlada (descanso 20–30 s)\n"
            "• 4×50 m nado fácil\n\n"
            "*Miércoles — Descanso activo*\n"
            "• Movilidad + caminata — 20–30 min\n\n"
            "*Jueves — Series moderadas*\n"
            "• 6×50 m a ritmo sostenido (descanso 60 s)\n"
            "• 4×25 m sprint suave (descanso 45 s)\n\n"
            "*Viernes — Resistencia suave*\n"
            "• 8–12×25 m ritmo fácil\n"
            "• Nado continuo — 150–250 m suave\n\n"
            "*Sábado / Domingo — Descanso*"
        )
        return _header("🏊", "NATACIÓN", level, "afianzar técnica de nado y confianza en el agua.") + "\n" + body + "\n\n" + FOOTER_NOTE

    if level == "intermedio":
        body = (
            "*Lunes — Técnica + calidad*\n"
            "• 10×25 m con drills (descanso 20–30 s)\n"
            "• 6×50 m suave (descanso 45–60 s)\n\n"
            "*Martes — Tempo*\n"
            "• 3×200 m a ritmo sostenible (descanso 2 min)\n\n"
            "*Miércoles — Recuperación*\n"
            "• 300–500 m total muy suave + movilidad\n\n"
            "*Jueves — Intervalos (series)*\n"
            "• 12×50 m progresivo (descanso 40–60 s)\n"
            "• 6×25 m sprint (descanso 30–40 s)\n\n"
            "*Viernes — Fuerza específica (pull + kick)*\n"
            "• 8×25 m pull (descanso 30 s) + 8×25 m kick (descanso 30 s)\n"
            "• 4×100 m nado fácil (descanso 90 s)\n\n"
            "*Sábado / Domingo — Descanso*"
        )
        return _header("🏊", "NATACIÓN", level, "mejorar resistencia y ritmo de competición.") + "\n" + body + "\n\n" + FOOTER_NOTE

    body = (
        "*Lunes — Técnica + sprints*\n"
        "• 6×50 m técnica (descanso 45–60 s)\n"
        "• 12×25 m sprint (descanso 25–35 s)\n\n"
        "*Martes — VO2 / intervalos altos*\n"
        "• 10×50 m a ritmo muy alto (descanso 50–70 s)\n"
        "• 4×25 m final rápido\n\n"
        "*Miércoles — Recuperación activa*\n"
        "• 400–600 m muy suave + movilidad 15 min\n\n"
        "*Jueves — Series largas controladas*\n"
        "• 4×200 m fuerte (descanso 2–3 min)\n"
        "• 2×100 m all-out controlado (descanso 2 min)\n\n"
        "*Viernes — Fuerza específica*\n"
        "• 10×25 m pull con foco (descanso 30 s)\n"
        "• 6×75 m progresivo (descanso 60–90 s)\n"
        "• Enfriamiento — 200 m\n\n"
        "*Sábado — Aeróbico opcional*\n"
        "• 600–1000 m zona 2\n\n"
        "*Domingo — Descanso*"
    )
    return _header("🏊", "NATACIÓN", level, "rendimiento máximo y afinación de ritmo de carrera.") + "\n" + body + "\n\n" + FOOTER_NOTE

def extract_day_section(full_text: str, weekday_index: int) -> str:
    day_name = WEEKDAYS[weekday_index]
    blocks = re.split(r"\n(?=\*[^\n*]+\*)", full_text)
    for block in blocks:
        header_line = block.strip().split("\n", 1)[0]
        if day_name in header_line:
            return block.strip()
    return f"📌 Hoy ({day_name}) no tienes sesión programada. ¡Aprovecha para descansar o hacer movilidad ligera!"

def main_menu(reminders_on: bool = False) -> InlineKeyboardMarkup:
    reminder_label = "🔕 Desactivar recordatorios" if reminders_on else "🔔 Activar recordatorios diarios"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🏃 Atletismo", callback_data="atletismo_menu")],
        [InlineKeyboardButton("🏋️ Gimnasio", callback_data="gym_menu")],
        [InlineKeyboardButton("🏊 Natación", callback_data="natacion_menu")],
        [InlineKeyboardButton("⭐ Mis favoritos", callback_data="favoritos")],
        [InlineKeyboardButton("📊 Mi progreso", callback_data="progreso")],
        [InlineKeyboardButton(reminder_label, callback_data="toggle_reminder")],
        [InlineKeyboardButton("❓ Cómo usar", callback_data="ayuda")],
    ])

def level_keyboard(tag: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🥉 Principiante", callback_data=f"{tag}_p")],
        [InlineKeyboardButton("🥈 Intermedio", callback_data=f"{tag}_i")],
        [InlineKeyboardButton("🥇 Avanzado", callback_data=f"{tag}_a")],
        [InlineKeyboardButton("🏠 Menú", callback_data="menu")],
    ])

def routine_keyboard(sport: str, level: str, is_fav: bool) -> InlineKeyboardMarkup:
    fav_label = "💔 Quitar de favoritos" if is_fav else "⭐ Guardar como favorito"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(fav_label, callback_data=f"fav_{sport}_{level}")],
        [InlineKeyboardButton("🏠 Menú", callback_data="menu")],
    ])

def favorites_keyboard(favorites: List[Dict[str, str]]) -> InlineKeyboardMarkup:
    buttons = []
    for fav in favorites:
        sport_label = SPORT_INFO[fav["sport"]]["name"]
        level_label = LEVEL_INFO[fav["level"]]["name"]
        buttons.append([
            InlineKeyboardButton(
                f"{sport_label} · {level_label}",
                callback_data=f"view_{fav['sport']}_{fav['level']}"
            )
        ])
    buttons.append([InlineKeyboardButton("🏠 Menú", callback_data="menu")])
    return InlineKeyboardMarkup(buttons)

def _job_name(user_id: int) -> str:
    return f"reminder_{user_id}"

async def send_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = context.job.chat_id
    selection = get_last_selection(user_id)
    if not selection:
        return

    sport, level = selection["sport"], selection["level"]
    sport_name = SPORT_INFO[sport]["name"]
    full_text = weeks_text(sport, level)
    today_section = extract_day_section(full_text, datetime.now().weekday())

    mensaje = f"🔔 *Recordatorio TrainFit — {sport_name}*\n\n{today_section}"
    await context.bot.send_message(chat_id=user_id, text=mensaje, parse_mode=ParseMode.MARKDOWN)

def schedule_reminder(app: Application, user_id: int) -> None:
    remove_reminder(app, user_id)
    app.job_queue.run_daily(
        send_reminder,
        time=time(hour=REMINDER_HOUR, minute=REMINDER_MINUTE),
        chat_id=user_id,
        name=_job_name(user_id),
    )

def remove_reminder(app: Application, user_id: int) -> None:
    for job in app.job_queue.get_jobs_by_name(_job_name(user_id)):
        job.schedule_removal()

def restore_reminders(app: Application) -> None:
    for sub in get_reminder_subscribers():
        schedule_reminder(app, sub["user_id"])

logger = logging.getLogger(__name__)

async def _send(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, reply_markup=None) -> None:
    if update.callback_query:
        q = update.callback_query
        await q.answer()
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=text,
            reply_markup=reply_markup,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(text, reply_markup=reply_markup, parse_mode=ParseMode.MARKDOWN)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    reminders_on = get_reminders_enabled(user_id)
    await update.message.reply_text(
        "💪 *TrainFit*\nTu entrenador personal de bolsillo.\n\nSelecciona una opción:",
        reply_markup=main_menu(reminders_on=reminders_on),
        parse_mode=ParseMode.MARKDOWN,
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = (
        "📖 *CÓMO USAR TRAINFIT*\n\n"
        "1️⃣ Elige tu disciplina:\n"
        "   🏋️ Gimnasio · 🏃 Atletismo · 🏊 Natación\n\n"
        "2️⃣ Selecciona tu nivel:\n"
        "   🥉 Principiante · 🥈 Intermedio · 🥇 Avanzado\n\n"
        "3️⃣ Recibe tu rutina semanal personalizada como un nuevo mensaje.\n\n"
        "⭐ *Favoritos:* guarda tus rutinas preferidas para acceder rápido.\n"
        "📊 *Progreso:* revisa tu historial de entrenamientos.\n"
        "🔔 *Recordatorios:* activa avisos diarios con la sesión del día.\n\n"
        "📌 *Comandos disponibles:*\n"
        "/start – Menú principal\n"
        "/gym – Rutinas de gimnasio\n"
        "/atletismo – Rutinas de atletismo\n"
        "/natacion – Rutinas de natación\n"
        "/progreso – Tu historial de rutinas\n"
        "/favoritos – Tus rutinas guardadas\n"
        "/help – Ver esta ayuda"
    )
    await _send(update, context, texto)

async def atletismo_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = "🏃 *ATLETISMO*\nSelecciona tu nivel para ver la rutina semanal:"
    await _send(update, context, texto, reply_markup=level_keyboard("atletismo"))

async def gym_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = "🏋️ *GIMNASIO*\nSelecciona tu nivel para ver la rutina semanal:"
    await _send(update, context, texto, reply_markup=level_keyboard("gym"))

async def natacion_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    texto = "🏊 *NATACIÓN*\nSelecciona tu nivel para ver la rutina semanal:"
    await _send(update, context, texto, reply_markup=level_keyboard("natacion"))

async def show_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    reminders_on = get_reminders_enabled(user_id)
    await _send(update, context, "💪 *Menú*", reply_markup=main_menu(reminders_on=reminders_on))

async def show_week_plan(update: Update, context: ContextTypes.DEFAULT_TYPE, sport: str, level: str) -> None:
    user = update.effective_user
    text = weeks_text(sport, level)
    record_selection(user.id, user.username, sport, level)
    is_fav = is_favorite(user.id, sport, level)
    keyboard = routine_keyboard(sport, level, is_fav)

    if update.callback_query:
        q = update.callback_query
        await q.answer(text="✅ Rutina generada")
        await context.bot.send_message(
            chat_id=q.message.chat_id,
            text=text,
            reply_markup=keyboard,
            parse_mode=ParseMode.MARKDOWN,
        )
    else:
        await update.message.reply_text(text, reply_markup=keyboard, parse_mode=ParseMode.MARKDOWN)

async def atletismo_p(update, context): await show_week_plan(update, context, "atletismo", "principiante")
async def atletismo_i(update, context): await show_week_plan(update, context, "atletismo", "intermedio")
async def atletismo_a(update, context): await show_week_plan(update, context, "atletismo", "avanzado")
async def gym_p(update, context): await show_week_plan(update, context, "gym", "principiante")
async def gym_i(update, context): await show_week_plan(update, context, "gym", "intermedio")
async def gym_a(update, context): await show_week_plan(update, context, "gym", "avanzado")
async def natacion_p(update, context): await show_week_plan(update, context, "natacion", "principiante")
async def natacion_i(update, context): await show_week_plan(update, context, "natacion", "intermedio")
async def natacion_a(update, context): await show_week_plan(update, context, "natacion", "avanzado")

async def toggle_favorite_callback(update: Update, context: ContextTypes.DEFAULT_TYPE, sport: str, level: str) -> None:
    q = update.callback_query
    user_id = update.effective_user.id
    now_fav = toggle_favorite(user_id, sport, level)
    texto = "⭐ Añadida a tus favoritos" if now_fav else "💔 Quitada de tus favoritos"
    await q.answer(text=texto)

async def favoritos(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    favs = get_favorites(user_id)
    if not favs:
        texto = "⭐ Aún no tienes rutinas favoritas.\nGuarda una desde el botón que aparece bajo cada rutina."
        await _send(update, context, texto)
        return

    texto = "⭐ *Tus rutinas favoritas*\nToca una para verla de nuevo:"
    await _send(update, context, texto, reply_markup=favorites_keyboard(favs))

async def view_favorite(update: Update, context: ContextTypes.DEFAULT_TYPE, sport: str, level: str) -> None:
    await show_week_plan(update, context, sport, level)

async def progreso(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    last = get_last_selection(user_id)
    history = get_history(user_id, limit=5)

    if not last:
        texto = "📊 Todavía no tienes historial.\n¡Elige un deporte y un nivel para empezar!"
        await _send(update, context, texto)
        return

    last_sport = SPORT_INFO[last["sport"]]["name"]
    last_level = LEVEL_INFO[last["level"]]["name"]

    lineas = [f"📊 *TU PROGRESO*\n", f"🕓 Última rutina vista: *{last_sport} — {last_level}*\n"]
    lineas.append("📅 *Historial reciente:*")
    for entry in history:
        sport_name = SPORT_INFO[entry["sport"]]["name"]
        level_name = LEVEL_INFO[entry["level"]]["name"]
        fecha = entry["ts"].split("T")[0]
        lineas.append(f"• {fecha} — {sport_name} · {level_name}")

    await _send(update, context, "\n".join(lineas))

async def toggle_reminder_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    user_id = update.effective_user.id
    now_on = toggle_reminder(user_id)

    if now_on:
        schedule_reminder(context.application, user_id)
        toast = "🔔 Recordatorios diarios activados"
    else:
        remove_reminder(context.application, user_id)
        toast = "🔕 Recordatorios diarios desactivados"

    await q.answer(text=toast)
    await context.bot.send_message(
        chat_id=q.message.chat_id,
        text="💪 *Menú*",
        reply_markup=main_menu(reminders_on=now_on),
        parse_mode=ParseMode.MARKDOWN,
    )

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    if ADMIN_ID == 0 or user_id != ADMIN_ID:
        await update.message.reply_text("🚫 No tienes permiso para usar este comando.")
        return

    data = get_stats()
    lineas = [
        "📊 *ESTADÍSTICAS DE TRAINFIT*\n",
        f"👥 Usuarios totales: *{data['total_users']}*",
        f"🔔 Con recordatorios activos: *{data['reminder_subscribers']}*",
        f"⭐ Rutinas guardadas como favoritas: *{data['total_favorites']}*\n",
        "🏆 *Deporte más elegido (última rutina vista):*",
    ]
    if data["sport_counts"]:
        for sport, count in sorted(data["sport_counts"].items(), key=lambda x: -x[1]):
            lineas.append(f"• {SPORT_INFO[sport]['name']}: {count}")
    else:
        lineas.append("• Sin datos todavía")

    lineas.append("\n🥇 *Nivel más elegido:*")
    if data["level_counts"]:
        for level, count in sorted(data["level_counts"].items(), key=lambda x: -x[1]):
            lineas.append(f"• {LEVEL_INFO[level]['name']}: {count}")
    else:
        lineas.append("• Sin datos todavía")

    await update.message.reply_text("\n".join(lineas), parse_mode=ParseMode.MARKDOWN)

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    data = q.data

    try:
        if data == "menu":
            await q.answer()
            await show_menu(update, context)
        elif data == "ayuda":
            await help_command(update, context)
        elif data == "favoritos":
            await favoritos(update, context)
        elif data == "progreso":
            await progreso(update, context)
        elif data == "toggle_reminder":
            await toggle_reminder_callback(update, context)

        elif data == "atletismo_menu":
            await atletismo_menu(update, context)
        elif data == "atletismo_p":
            await atletismo_p(update, context)
        elif data == "atletismo_i":
            await atletismo_i(update, context)
        elif data == "atletismo_a":
            await atletismo_a(update, context)

        elif data == "gym_menu":
            await gym_menu(update, context)
        elif data == "gym_p":
            await gym_p(update, context)
        elif data == "gym_i":
            await gym_i(update, context)
        elif data == "gym_a":
            await gym_a(update, context)

        elif data == "natacion_menu":
            await natacion_menu(update, context)
        elif data == "natacion_p":
            await natacion_p(update, context)
        elif data == "natacion_i":
            await natacion_i(update, context)
        elif data == "natacion_a":
            await natacion_a(update, context)

        elif data.startswith("fav_"):
            _, sport, level = data.split("_", 2)
            await toggle_favorite_callback(update, context, sport, level)
        elif data.startswith("view_"):
            _, sport, level = data.split("_", 2)
            await view_favorite(update, context, sport, level)
        else:
            await q.answer()

    except Exception:
        logger.exception("Error manejando el callback '%s'", data)
        await q.answer(text="⚠️ Ocurrió un error, intenta de nuevo.")

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.exception("Excepción no controlada", exc_info=context.error)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

async def set_commands(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand("start", "Inicio"),
        BotCommand("atletismo", "Atletismo"),
        BotCommand("gym", "Gym"),
        BotCommand("natacion", "Natación"),
        BotCommand("progreso", "Tu historial de rutinas"),
        BotCommand("favoritos", "Tus rutinas guardadas"),
        BotCommand("help", "Cómo usar el bot"),
    ])
    restore_reminders(app)
    logger.info("Comandos registrados y recordatorios restaurados.")

def main() -> None:
    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("atletismo", atletismo_menu))
    app.add_handler(CommandHandler("natacion", natacion_menu))
    app.add_handler(CommandHandler("gym", gym_menu))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("progreso", progreso))
    app.add_handler(CommandHandler("favoritos", favoritos))
    app.add_handler(CommandHandler("stats", stats))

    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_error_handler(error_handler)

    app.post_init = set_commands

    logger.info("TrainFit CALENTANDO...")
    app.run_polling()

if __name__ == "__main__":
    main()