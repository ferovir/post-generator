import os
import requests

VK_API_URL = "https://api.vk.com/method/"
VK_API_VERSION = "5.199"


def get_config():
    """Возвращает настройки VK из переменных окружения."""
    return {
        "token": os.environ.get("VK_ACCESS_TOKEN", ""),
        "group_id": os.environ.get("VK_GROUP_ID", ""),
    }


def is_configured():
    cfg = get_config()
    return bool(cfg["token"] and cfg["group_id"])


def publish_post(message, publish_date=None):
    """Публикует пост на стене сообщества ВКонтакте.

    Args:
        message: Текст поста.
        publish_date: Unix-метка времени для отложенной публикации (опционально).

    Returns:
        dict с ответом VK API или {'error': ...}.
    """
    cfg = get_config()
    if not cfg["token"] or not cfg["group_id"]:
        return {"error": {"error_msg": "VK не настроен. Укажи VK_ACCESS_TOKEN и VK_GROUP_ID."}}

    params = {
        "owner_id": f"-{cfg['group_id']}",
        "message": message,
        "access_token": cfg["token"],
        "v": VK_API_VERSION,
        "from_group": 1,
    }
    if publish_date:
        params["publish_date"] = publish_date

    try:
        resp = requests.post(f"{VK_API_URL}wall.post", data=params, timeout=20)
        data = resp.json()
        if "error" in data:
            return {"error": {"error_msg": data["error"].get("error_msg", "Неизвестная ошибка VK")}}
        return data
    except requests.RequestException as e:
        return {"error": {"error_msg": f"Ошибка сети: {e}"}}
