import os
import re
import time
import logging
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup
from flask import Flask, jsonify, render_template, request

# ------------------------------------------------------------
# Конфигурация
# ------------------------------------------------------------
# API-ключ OpenRouter. Можно задать через переменную окружения
# OPENROUTER_API_KEY или указать здесь напрямую (не рекомендую для GitHub).
API_KEY = os.environ.get(
    "OPENROUTER_API_KEY",
    "",  # ⚠ Укажи ключ через переменную окружения OPENROUTER_API_KEY
)
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Модель по умолчанию — одна из бесплатных (free) на OpenRouter.
# Актуальный список: https://openrouter.ai/models?output_modalities=text
# Если модель недоступна, используем openrouter/free (автовыбор среди free).
DEFAULT_MODEL = "meta-llama/llama-3.3-70b-instruct:free"
FALLBACK_MODEL = "openrouter/free"

# HTTP-заголовки для OpenRouter (включаем referer, чтобы модель была видна в логах)
HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
    "HTTP-Referer": "http://localhost:5000",
    "X-Title": "Post Generator for Courses",
}

# ------------------------------------------------------------
# Настройки из voice.md (читаются при каждом запросе, чтобы changes применялись сразу)
# ------------------------------------------------------------
VOICE_FILE = "voice.md"


def load_voice_settings():
    """Парсит voice.md и возвращает dict с настройками тона / длины / emoji / заголовка."""
    settings = {
        "ton": "профессиональный, вдохновляющий",
        "length": "средний (300-500 слов)",
        "emoji": "умеренное (2-4)",
        "headline": "громкое обещание",
        "format": "список с буллитами",
        "cta": "прямой",
    }
    try:
        with open(VOICE_FILE, "r", encoding="utf-8") as f:
            for line in f:
                # Пропускаем комментарии и пустые строки
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                match = re.match(r"^(\w+):\s*(.+)$", line)
                if match:
                    key = match.group(1).lower()
                    val = match.group(2).strip()
                    if key in settings:
                        settings[key] = val
    except FileNotFoundError:
        logging.warning("voice.md не найден, используются настройки по умолчанию")
    return settings


# ------------------------------------------------------------
# Вспомогательные функции
# ------------------------------------------------------------

def fetch_page_text(url: str) -> str:
    """Загружает страницу по ссылке и извлекает читаемый текст.

    Проверяет Content-Type, парсит HTML и собирает текст из всех
    значимых элементов. Если структурированный сбор дал <200 символов,
    падает на весь текст body."""

    # Проверяем, что ответ — текстовый HTML
    try:
        resp = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
            allow_redirects=True,
        )
        resp.raise_for_status()
    except requests.RequestException as e:
        raise RuntimeError(f"Не удалось загрузить страницу: {e}")

    ct = (resp.headers.get("Content-Type") or "").lower()
    if "text/html" not in ct and "application/xhtml" not in ct:
        raise RuntimeError(
            f"Ссылка должна вести на HTML-страницу, а получен Content-Type: {ct}"
        )

    soup = BeautifulSoup(resp.text, "html.parser")

    # Удаляем мусорные блоки
    for tag in soup(["script", "style", "nav", "footer", "header", "aside",
                      "noscript", "iframe", "form", "svg", "button"]):
        tag.decompose()

    # 1) Собираем текст из ключевых семантических тегов
    text_parts = []
    for tag in soup.find_all(["h1", "h2", "h3", "h4", "h5", "h6",
                               "p", "li", "td", "th", "blockquote",
                               "figcaption", "dt", "dd", "strong", "em"]):
        text = tag.get_text(strip=True)
        if text and len(text) > 15:
            text_parts.append(text)

    full_text = "\n".join(text_parts)

    # 2) Если текста мало — берём всё из body (чистим от лишних пробелов)
    if len(full_text) < 200 and soup.body:
        import re as _re
        raw = soup.body.get_text(separator="\n", strip=True)
        lines = [ln for ln in raw.split("\n") if len(ln.strip()) > 15]
        full_text = "\n".join(lines)

    full_text = full_text[:8000]
    if not full_text.strip():
        raise RuntimeError("Не удалось извлечь описание курса — страница не содержит текста")
    return full_text


def build_prompt(course_text: str, mood: str, settings: dict) -> str:
    """Формирует промпт для нейросети на основе текста курса, настроения и voice-настроек."""
    return f"""Ты — профессиональный копирайтер, специализирующийся на продающих постах для онлайн-курсов. Напиши пост по правилам ниже.

ОПИСАНИЕ КУРСА (извлечено со страницы):
{course_text}

НАСТРОЕНИЕ ПОСТА: {mood}

НАСТРОЙКИ СТИЛЯ:
- Общий тон: {settings['ton']}
- Длина: {settings['length']}
- Количество эмодзи: {settings['emoji']}
- Стиль заголовка: {settings['headline']}
- Формат: {settings['format']}
- Призыв к действию (CTA): {settings['cta']}

Напиши готовый продающий пост для соцсетей на русском языке. Используй информацию из описания курса."""


def call_openrouter(messages: list, model: str = DEFAULT_MODEL, retry: int = 1) -> str:
    """Отправляет запрос к OpenRouter API. При ошибке пробует fallback-модель."""
    models_to_try = [model, FALLBACK_MODEL] if model != FALLBACK_MODEL else [model]

    for attempt, current_model in enumerate(models_to_try):
        payload = {
            "model": current_model,
            "messages": messages,
            "temperature": 0.8,
            "max_tokens": 2048,
        }
        try:
            resp = requests.post(
                OPENROUTER_URL,
                headers=HEADERS,
                json=payload,
                timeout=60,
            )
            if resp.status_code == 429 and retry > 0:
                # Rate limit — ждём и повторяем
                time.sleep(3)
                return call_openrouter(messages, model, retry - 1)
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except Exception as e:
            logging.warning(f"Модель {current_model} не сработала: {e}")
            if attempt == len(models_to_try) - 1:
                raise RuntimeError(
                    f"Ошибка OpenRouter (модель {current_model}): {e}"
                )
    return ""


# ------------------------------------------------------------
# Flask-приложение
# ------------------------------------------------------------
app = Flask(__name__)

# Настроения поста — пользователь выбирает из списка
MOOD_OPTIONS = [
    {"id": "professional", "label": "Деловой", "icon": "💼"},
    {"id": "inspirational", "label": "Вдохновляющий", "icon": "✨"},
    {"id": "casual", "label": "Непринуждённый", "icon": "😊"},
    {"id": "urgent", "label": "Срочный", "icon": "⚡"},
    {"id": "academic", "label": "Академический", "icon": "🎓"},
    {"id": "humorous", "label": "Юмористический", "icon": "😂"},
]

# Маппинг id настроения → текст для промпта
MOOD_MAP = {
    "professional": "Деловой, уверенный, экспертный",
    "inspirational": "Вдохновляющий, мотивирующий, эмоциональный",
    "casual": "Непринуждённый, дружеский, разговорный",
    "urgent": "Срочный, создающий ощущение ограниченности по времени",
    "academic": "Академический, структурированный, обоснованный",
    "humorous": "Юмористический, лёгкий, с иронией",
}


@app.route("/")
def index():
    """Главная страница."""
    settings = load_voice_settings()
    return render_template(
        "index.html",
        moods=MOOD_OPTIONS,
        settings=settings,
    )


@app.route("/generate", methods=["POST"])
def generate():
    """
    Эндпоинт генерации поста.
    Принимает JSON: { "url": "...", "mood": "professional" }
    Возвращает JSON: { "success": true, "post": "..." }
    """
    data = request.get_json(silent=True) or {}
    course_url = data.get("url", "").strip()
    mood_id = data.get("mood", "professional")

    # Валидация
    if not course_url:
        return jsonify({"success": False, "error": "Введите ссылку на курс"}), 400

    parsed = urlparse(course_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return jsonify({"success": False, "error": "Некорректная ссылка"}), 400

    if mood_id not in MOOD_MAP:
        mood_id = "professional"

    mood_text = MOOD_MAP[mood_id]
    settings = load_voice_settings()

    # 1. Получаем текст страницы курса
    try:
        course_text = fetch_page_text(course_url)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 400

    if not course_text:
        return jsonify({"success": False, "error": "Не удалось извлечь описание курса со страницы"}), 400

    # 2. Собираем промпт
    prompt = build_prompt(course_text, mood_text, settings)

    # 3. Отправляем в нейросеть
    try:
        messages = [
            {
                "role": "system",
                "content": "Ты — опытный маркетолог и копирайтер. Пишешь продающие посты для онлайн-курсов на русском языке. Всегда следуй указанным настройкам стиля.",
            },
            {"role": "user", "content": prompt},
        ]
        post = call_openrouter(messages)
    except RuntimeError as e:
        return jsonify({"success": False, "error": str(e)}), 500

    if not post:
        return jsonify({"success": False, "error": "Нейросеть не вернула результат"}), 500

    return jsonify({"success": True, "post": post.strip()})


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    app.run(debug=True, host="0.0.0.0", port=5000)
