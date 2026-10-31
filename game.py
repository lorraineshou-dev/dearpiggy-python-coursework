"""Server-side Dear Piggy rules. No browser-supplied balances or prices are trusted."""

from __future__ import annotations

import base64
import binascii
from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import re
import struct
import unicodedata
from uuid import uuid4
import zlib


CATALOG = json.loads(Path(__file__).with_name("catalogue.json").read_text(encoding="utf-8"))
HABITS = {row["id"]: row for row in CATALOG["habits"]}
ITEMS = {row["id"]: row for row in CATALOG["items"]}
MOODS = {row["id"] for row in CATALOG["moods"]}
SLOTS = {"eyes", "head", "clothes", "seat", "background", "pet"}
DEFAULT_ITEMS = {"seat": "blanket", "background": "room"}
CAPACITIES = {"low", "medium", "high"}
MAX_HABITS = 50
MAX_HABIT_RECORDS = 200
MAX_CATEGORIES = 20
MAX_JOURNAL = 50
MAX_PHOTO_BYTES = 2 * 1024 * 1024
_ID = re.compile(r"[a-zA-Z0-9_-]{1,80}\Z")


def _day(today=None):
    if today is None:
        return date.today().isoformat()
    if isinstance(today, date):
        return today.isoformat()
    if not isinstance(today, str):
        raise ValueError("Invalid calendar date")
    try:
        parsed = date.fromisoformat(today)
    except ValueError as exc:
        raise ValueError("Invalid calendar date") from exc
    if parsed.isoformat() != today:
        raise ValueError("Invalid calendar date")
    return today


def _text(value, limit, *, empty=False, multiline=False):
    if not isinstance(value, str):
        raise ValueError("请输入文字。 / Please enter text.")
    value = unicodedata.normalize("NFC", value).strip()
    forbidden = r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]" if multiline else r"[\x00-\x1f\x7f]"
    if (not empty and not value) or len(value) > limit or re.search(forbidden, value):
        raise ValueError(f"文字为空、过长或包含无效字符（最多 {limit} 字）。 / Invalid text (maximum {limit} characters).")
    return value


def _identity(value):
    if not isinstance(value, str) or not _ID.fullmatch(value):
        raise ValueError("无效的项目。 / Invalid item.")
    return value


def _title_key(value):
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def _habit_copy(row):
    return {key: row[key] for key in ("id", "zh", "en", "category", "icon")}


def new_state(today=None):
    """Return an independent initial state; no money or progress is preloaded."""
    return {
        "name": "小桃", "nickname": "", "lang": "zh-CN", "welcomed": False,
        "energy": 0, "total": 0, "date": _day(today), "done": [],
        "reward_count": 0, "history": [],
        "habits": [_habit_copy(row) for row in CATALOG["habits"][:3]],
        "removed_habits": [], "categories": [], "journal": [],
        "owned": list(DEFAULT_ITEMS.values()), "equipped": dict(DEFAULT_ITEMS),
        "skin": "pink", "cards": {color: 0 for color in CATALOG["skins"] if color != "pink"},
        "checkin": {"mood": "", "capacity": ""}, "rest": False, "music": True,
    }


def rollover(state, today=None):
    """Reset daily presentation, retaining the completion ledger and all purchases.

    Rebuilding from the ledger also prevents a clock rollback or a removed/re-added
    habit from earning twice for the same local calendar date.
    """
    today = _day(today)
    if state["date"] != today:
        state["date"] = today
        state["checkin"] = {"mood": "", "capacity": ""}
        state["rest"] = False
    state["done"] = list(dict.fromkeys(row["id"] for row in state["history"] if row["date"] == today))
    state["reward_count"] = min(6, len(state["done"]))
    return state


def recommendations(state):
    """Return catalogue records chosen by mood/capacity, without mutating state."""
    mood, capacity = state["checkin"]["mood"], state["checkin"]["capacity"]
    if state["rest"] or capacity == "low" or mood == "tired":
        pool = ["water", "rest", "kind"]
    elif mood == "mixed":
        pool = ["breathe", "kind", "water"]
    elif mood == "low":
        pool = ["kind", "daylight", "connect"]
    elif mood == "happy" and capacity == "high":
        pool = ["good", "connect", "stretch"]
    else:
        pool = ["water", "daylight", "breathe"]
    blocked = set(state["done"]) | {row["id"] for row in state["removed_habits"]}
    count = 1 if capacity == "low" or state["rest"] else 2
    return [deepcopy(HABITS[key]) for key in pool if key not in blocked][:count]


def _dimensions(width, height):
    if not (0 < width <= 4096 and 0 < height <= 4096 and width * height <= 4_000_000):
        raise ValueError("照片尺寸过大或无效。 / Invalid or oversized photo dimensions.")


def _png(data):
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid PNG")
    pos, header, compressed, ended, palette = 8, None, bytearray(), False, False
    while pos < len(data):
        if pos + 12 > len(data):
            raise ValueError("Truncated PNG")
        length = struct.unpack_from(">I", data, pos)[0]
        end = pos + 12 + length
        if end > len(data):
            raise ValueError("Truncated PNG chunk")
        kind = data[pos + 4:pos + 8]
        part = data[pos + 8:pos + 8 + length]
        crc = struct.unpack_from(">I", data, pos + 8 + length)[0]
        if zlib.crc32(kind + part) & 0xFFFFFFFF != crc:
            raise ValueError("Invalid PNG checksum")
        if header is None and kind != b"IHDR":
            raise ValueError("Missing PNG header")
        if kind == b"IHDR":
            if header is not None or length != 13:
                raise ValueError("Invalid PNG header")
            width, height, bits, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", part)
            _dimensions(width, height)
            permitted = {0: {1, 2, 4, 8, 16}, 2: {8, 16}, 3: {1, 2, 4, 8}, 4: {8, 16}, 6: {8, 16}}
            if color not in permitted or bits not in permitted[color] or compression or filtering or interlace:
                raise ValueError("Unsupported PNG encoding; use a resized PNG or JPEG")
            channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[color]
            stride = 1 + (width * bits * channels + 7) // 8
            header = (height, stride, color)
        elif kind == b"PLTE":
            if not length or length % 3 or length > 768:
                raise ValueError("Invalid PNG palette")
            palette = True
        elif kind == b"IDAT":
            compressed.extend(part)
        elif kind == b"IEND":
            if length or end != len(data):
                raise ValueError("Invalid PNG end")
            ended = True
        elif kind[0] & 32 == 0:
            raise ValueError("Unsupported PNG chunk")
        pos = end
    if not header or not ended or not compressed or (header[2] == 3 and not palette):
        raise ValueError("Incomplete PNG")
    height, stride, _ = header
    decoder = zlib.decompressobj()
    raw = decoder.decompress(bytes(compressed), height * stride + 1)
    if not decoder.eof or decoder.unused_data or decoder.unconsumed_tail or len(raw) != height * stride:
        raise ValueError("Invalid PNG pixels")
    if any(raw[offset] > 4 for offset in range(0, len(raw), stride)):
        raise ValueError("Invalid PNG filter")


def _jpeg(data):
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Invalid JPEG")
    pos, frame, scan = 2, False, False
    while pos < len(data):
        if data[pos] != 0xFF:
            raise ValueError("Invalid JPEG marker")
        while pos < len(data) and data[pos] == 0xFF:
            pos += 1
        if pos >= len(data):
            raise ValueError("Truncated JPEG")
        marker = data[pos]
        pos += 1
        if marker == 0xD9:
            if pos != len(data) or not frame or not scan:
                raise ValueError("Incomplete JPEG")
            return
        if marker in (0, 0xD8) or 0xD0 <= marker <= 0xD7:
            raise ValueError("Unexpected JPEG marker")
        if pos + 2 > len(data):
            raise ValueError("Truncated JPEG")
        length = int.from_bytes(data[pos:pos + 2], "big")
        if length < 2 or pos + length > len(data):
            raise ValueError("Invalid JPEG segment")
        segment = data[pos + 2:pos + length]
        if marker in {0xC0, 0xC1, 0xC2}:
            if len(segment) < 6 or segment[0] != 8 or segment[5] not in (1, 3, 4) or len(segment) != 6 + 3 * segment[5]:
                raise ValueError("Invalid JPEG frame")
            _dimensions(int.from_bytes(segment[3:5], "big"), int.from_bytes(segment[1:3], "big"))
            frame = True
        pos += length
        if marker == 0xDA:
            if not frame or len(segment) < 4 or len(segment) != 4 + 2 * segment[0]:
                raise ValueError("Invalid JPEG scan")
            scan = True
            start = pos
            while pos < len(data):
                if data[pos] != 0xFF:
                    pos += 1
                    continue
                if pos + 1 >= len(data):
                    raise ValueError("Truncated JPEG scan")
                following = data[pos + 1]
                if following == 0 or 0xD0 <= following <= 0xD7:
                    pos += 2
                elif following == 0xFF:
                    pos += 1
                else:
                    break
            if pos == start:
                raise ValueError("Empty JPEG scan")
    raise ValueError("Missing JPEG end")


def _webp(data):
    if len(data) < 20 or data[:4] != b"RIFF" or data[8:12] != b"WEBP" or int.from_bytes(data[4:8], "little") != len(data) - 8:
        raise ValueError("Invalid WebP")
    pos, image = 12, False
    while pos < len(data):
        if pos + 8 > len(data):
            raise ValueError("Truncated WebP")
        kind, length = data[pos:pos + 4], int.from_bytes(data[pos + 4:pos + 8], "little")
        end = pos + 8 + length
        if end + (length & 1) > len(data):
            raise ValueError("Truncated WebP chunk")
        part = data[pos + 8:end]
        if kind == b"VP8 ":
            if image or length < 10 or part[0] & 1 or part[3:6] != b"\x9d\x01\x2a":
                raise ValueError("Invalid WebP frame")
            _dimensions(int.from_bytes(part[6:8], "little") & 0x3FFF, int.from_bytes(part[8:10], "little") & 0x3FFF)
            image = True
        elif kind == b"VP8L":
            if image or length < 6 or part[0] != 0x2F:
                raise ValueError("Invalid lossless WebP")
            packed = int.from_bytes(part[1:5], "little")
            if packed >> 29:
                raise ValueError("Invalid WebP version")
            _dimensions((packed & 0x3FFF) + 1, ((packed >> 14) & 0x3FFF) + 1)
            image = True
        elif kind == b"VP8X":
            if pos != 12 or length != 10 or part[0] & 2:
                raise ValueError("Animated WebP is not supported for photos")
            _dimensions(int.from_bytes(part[4:7], "little") + 1, int.from_bytes(part[7:10], "little") + 1)
        elif kind not in {b"ALPH", b"ICCP", b"EXIF", b"XMP "}:
            raise ValueError("Unsupported WebP chunk")
        pos = end + (length & 1)
    if not image:
        raise ValueError("Missing WebP image")


def validate_photo(value):
    """Validate declared type, base64, size and image container; never accept SVG.

    PNG pixel data is also checked using bounded standard-library decompression.
    JPEG/WebP decoding remains the browser's job; their containers and dimensions
    are checked here without installing an image-processing dependency.
    """
    if not value:
        return ""
    if not isinstance(value, str) or len(value) > 4 * ((MAX_PHOTO_BYTES + 2) // 3) + 40:
        raise ValueError("照片最多 2 MiB。 / Photos must be no larger than 2 MiB.")
    match = re.fullmatch(r"data:image/(png|jpeg|webp);base64,([A-Za-z0-9+/]*={0,2})", value)
    if not match:
        raise ValueError("请选择 PNG、JPEG 或 WebP 照片。 / Choose a PNG, JPEG or WebP photo.")
    try:
        data = base64.b64decode(match[2], validate=True)
        if not data or len(data) > MAX_PHOTO_BYTES:
            raise ValueError("Invalid photo size")
        {"png": _png, "jpeg": _jpeg, "webp": _webp}[match[1]](data)
    except (ValueError, binascii.Error, zlib.error, struct.error, IndexError) as exc:
        raise ValueError("照片无效、过大或格式不受支持。 / Invalid, oversized or unsupported photo.") from exc
    return f"data:image/{match[1]};base64," + base64.b64encode(data).decode("ascii")


def _category(state, value):
    allowed = (set(CATALOG["categories"]) - {"all"}) | {row["id"] for row in state["categories"]}
    if value not in allowed:
        raise ValueError("请选择有效分类。 / Choose a valid category.")
    return value


def _row(rows, key):
    return next((row for row in rows if row["id"] == key), None)


def _room_for_habit(state, *, new_record=False):
    if len(state["habits"]) >= MAX_HABITS or (new_record and len(state["habits"]) + len(state["removed_habits"]) >= MAX_HABIT_RECORDS):
        raise ValueError("小事列表已满，请先整理。 / Your habit list is full.")


def _add_habit(state, form):
    key = form.get("catalog_id", "")
    if key:
        if key not in HABITS:
            raise ValueError("找不到这件小事。 / Unknown habit.")
        candidate = _habit_copy(HABITS[key])
        if _row(state["habits"], key):
            raise ValueError("这件小事已在列表中。 / This habit is already in your list.")
        removed = _row(state["removed_habits"], key)
    else:
        title = _text(form.get("title", ""), 60)
        category = _category(state, form.get("category", ""))
        titles = {_title_key(title)}
        if any(titles & {_title_key(row["zh"]), _title_key(row["en"])} for row in state["habits"]):
            raise ValueError("这件小事已在列表中。 / This habit is already in your list.")
        removed = next((row for row in state["removed_habits"] if titles & {_title_key(row["zh"]), _title_key(row["en"])}), None)
        builtin = next((row for row in CATALOG["habits"] if titles & {_title_key(row["zh"]), _title_key(row["en"])}), None)
        candidate = _habit_copy(builtin) if builtin else {"id": "habit-" + uuid4().hex, "zh": title, "en": title, "category": category, "icon": "✧"}
    _room_for_habit(state, new_record=removed is None)
    if removed is not None:
        state["removed_habits"].remove(removed)
        candidate = removed
    state["habits"].append(candidate)


def _apply(state, action, form):
    if action == "welcome":
        state["welcomed"] = True
        return "欢迎回到小屋。", "Welcome to your little corner."
    if action == "language":
        if form.get("lang") not in {"zh-CN", "en"}:
            raise ValueError("不支持的语言。 / Unsupported language.")
        state["lang"] = form["lang"]
        return "语言已更新。", "Language updated."
    if action == "profile":
        state["name"] = _text(form.get("name", ""), 24)
        state["nickname"] = _text(form.get("nickname", ""), 40, empty=True)
        state["music"] = form.get("music") == "on"
        return "小屋设置已保存。", "Your settings are saved."
    if action == "checkin":
        mood, capacity = form.get("mood", ""), form.get("capacity", "")
        if mood not in MOODS | {""} or capacity not in CAPACITIES | {""} or not (mood or capacity):
            raise ValueError("请选择心情或精力。 / Choose a mood or energy level.")
        state["checkin"] = {"mood": mood, "capacity": capacity}
        return "今天的感受被看见了。", "There is room for how you feel today."
    if action == "rest":
        state["rest"] = form.get("enabled") == "on"
        return ("今天可以慢慢来。", "Take today at your own pace.") if state["rest"] else ("已结束休息模式。", "Rest mode is off.")
    if action == "complete":
        key = _identity(form.get("id", ""))
        if key in state["done"]:
            raise ValueError("今天已经记下这件小事了。 / This habit is already complete today.")
        habit = _row(state["habits"], key)
        if habit is None:
            suggested = {row["id"] for row in recommendations(state)}
            if key not in suggested or _row(state["removed_habits"], key):
                raise ValueError("请先把这件小事加入列表。 / Add this habit to your list first.")
            _room_for_habit(state, new_record=True)
            state["habits"].append(_habit_copy(HABITS[key]))
        reward = 10 if state["reward_count"] < 6 else 0
        state["done"].append(key)
        state["history"].append({"id": key, "date": state["date"]})
        state["reward_count"] = min(6, state["reward_count"] + 1)
        state["energy"] += reward
        state["total"] += 1
        return ("小事已记下，获得 10 能量。", "Habit recorded. You earned 10 energy.") if reward else ("小事已记下，成长仍在继续。今天的能量已满 60。", "Habit recorded; your growth continues. Today's 60 energy is complete.")
    if action == "add_habit":
        _add_habit(state, form)
        return "小事已加入。", "Habit added."
    if action in {"delete_habit", "restore_habit"}:
        key = _identity(form.get("id", ""))
        source, target = (state["habits"], state["removed_habits"]) if action == "delete_habit" else (state["removed_habits"], state["habits"])
        habit = _row(source, key)
        if habit is None:
            raise ValueError("找不到这件小事。 / Unknown habit.")
        if action == "restore_habit":
            _room_for_habit(state)
        source.remove(habit)
        target.append(habit)
        return ("小事已移除，可以稍后恢复。", "Habit removed; you can restore it later.") if action == "delete_habit" else ("小事已恢复，原来的记录仍在。", "Habit restored with its existing record.")
    if action == "edit_habit":
        habit = _row(state["habits"], _identity(form.get("id", "")))
        if habit is None or habit["id"] in HABITS:
            raise ValueError("只能编辑自建小事。 / Only custom habits can be edited.")
        title = _text(form.get("title", ""), 60)
        for other in state["habits"] + state["removed_habits"] + list(HABITS.values()):
            if other["id"] != habit["id"] and _title_key(title) in {_title_key(other["zh"]), _title_key(other["en"])}:
                raise ValueError("这个名称已经存在。 / This name is already in use.")
        habit.update(zh=title, en=title, category=_category(state, form.get("category", "")))
        return "小事已更新。", "Habit updated."
    if action in {"add_category", "edit_category"}:
        title = _text(form.get("title", ""), 24)
        category = None
        if action == "edit_category":
            category = _row(state["categories"], _identity(form.get("id", "")))
            if category is None:
                raise ValueError("只能编辑自建分类。 / Only custom categories can be edited.")
        elif len(state["categories"]) >= MAX_CATEGORIES:
            raise ValueError("最多创建 20 个分类。 / You can create up to 20 categories.")
        titles = [name for names in CATALOG["categories"].values() for name in names]
        titles += [row[key] for row in state["categories"] if row is not category for key in ("zh", "en")]
        if _title_key(title) in {_title_key(name) for name in titles}:
            raise ValueError("这个分类已存在。 / This category already exists.")
        if category is None:
            state["categories"].append({"id": "category-" + uuid4().hex, "zh": title, "en": title})
        else:
            category.update(zh=title, en=title)
        return "分类已保存。", "Category saved."
    if action == "delete_category":
        category = _row(state["categories"], _identity(form.get("id", "")))
        if category is None:
            raise ValueError("只能删除自建分类。 / Only custom categories can be removed.")
        state["categories"].remove(category)
        for habit in state["habits"] + state["removed_habits"]:
            if habit["category"] == category["id"]:
                habit["category"] = "body"
        return "分类已删除，小事已移到身体照顾。", "Category removed. Its habits moved to Body."
    if action == "save_journal":
        if len(state["journal"]) >= MAX_JOURNAL:
            raise ValueError("手帐已满 50 条，请先整理旧记录。 / Your journal has 50 entries; remove an old entry first.")
        mood = form.get("mood", "")
        if mood not in MOODS:
            raise ValueError("请选择心情。 / Choose a mood.")
        note = _text(form.get("note", ""), 500, empty=True, multiline=True)
        photo = validate_photo(form.get("photo_data", ""))
        state["journal"].insert(0, {"id": "journal-" + uuid4().hex, "date": state["date"], "mood": mood, "note": note, "photo": photo})
        return "这一刻已收进手帐。", "This moment is saved in your journal."
    if action == "delete_journal":
        entry = _row(state["journal"], _identity(form.get("id", "")))
        if entry is None:
            raise ValueError("找不到这条手帐。 / Unknown journal entry.")
        state["journal"].remove(entry)
        return "手帐记录已删除。", "Journal entry removed."
    if action in {"buy", "equip"}:
        item = ITEMS.get(form.get("id", ""))
        if item is None:
            raise ValueError("找不到这件装扮。 / Unknown shop item.")
        key, slot = item["id"], item["slot"]
        if action == "buy":
            if slot != "color" and key in state["owned"] and not item.get("builtin"):
                raise ValueError("已经拥有这件装扮，无需再买。 / You already own this item.")
            if state["energy"] < item["price"]:
                raise ValueError("能量还不够，慢慢来。 / Not enough energy yet; take your time.")
            state["energy"] -= item["price"]
            if slot == "color":
                state["cards"][item["color"]] += 1
                return "改色卡已收好，使用时才会消耗。", "Color card saved; it is consumed only when used."
            if key not in state["owned"]:
                state["owned"].append(key)
            state["equipped"][slot] = key
            return "装扮已兑换并穿好。", "Item purchased and equipped."
        if slot == "color" or key not in state["owned"]:
            raise ValueError("请先兑换这件装扮。 / Purchase this item first.")
        if state["equipped"].get(slot) == key and not item.get("builtin"):
            if slot in DEFAULT_ITEMS:
                state["equipped"][slot] = DEFAULT_ITEMS[slot]
            else:
                state["equipped"].pop(slot, None)
        else:
            state["equipped"][slot] = key
        return "装扮已更新。", "Outfit updated."
    if action == "use_color":
        color = form.get("color", "")
        if color not in CATALOG["skins"]:
            raise ValueError("找不到这个颜色。 / Unknown color.")
        if color != "pink":
            if color == state["skin"]:
                raise ValueError("已经是这个颜色，改色卡已保留。 / Already this color; your card is kept.")
            if state["cards"].get(color, 0) < 1:
                raise ValueError("请先兑换对应的改色卡。 / Purchase a matching color card first.")
            state["cards"][color] -= 1
        state["skin"] = color
        return "小猪的颜色已更新。", "Piggy's color is updated."
    raise ValueError("未知操作。 / Unknown action.")


def apply_action(state, action, form, today=None):
    """Apply one validated action atomically, ignoring client-supplied accounting.

    A failed action leaves even daily rollover untouched. Store.get performs a
    separate persisted rollover whenever a page is loaded.
    """
    if not isinstance(action, str) or not isinstance(form, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in form.items()):
        raise ValueError("无效的表单。 / Invalid form.")
    working = deepcopy(state)
    rollover(working, today)
    result = _apply(working, action, form)
    validate_state(working)
    state.clear()
    state.update(working)
    return result


def validate_state(state):
    """Check the persistent schema; transient chats, secrets and worries have no slot."""
    if not isinstance(state, dict) or set(state) != set(new_state()):
        raise ValueError("Invalid stored state fields")
    _day(state["date"])
    _text(state["name"], 24)
    _text(state["nickname"], 40, empty=True)
    if state["lang"] not in {"zh-CN", "en"} or state["skin"] not in CATALOG["skins"]:
        raise ValueError("Invalid stored preferences")
    if any(type(state[key]) is not bool for key in ("welcomed", "rest", "music")):
        raise ValueError("Invalid stored flags")
    if any(type(state[key]) is not int or state[key] < 0 for key in ("energy", "total", "reward_count")) or state["reward_count"] > 6:
        raise ValueError("Invalid stored accounting")
    for key in ("habits", "removed_habits", "categories", "journal", "history", "owned", "done"):
        if not isinstance(state[key], list):
            raise ValueError("Invalid stored list")
    if len(state["habits"]) > MAX_HABITS or len(state["habits"]) + len(state["removed_habits"]) > MAX_HABIT_RECORDS or len(state["categories"]) > MAX_CATEGORIES or len(state["journal"]) > MAX_JOURNAL:
        raise ValueError("Stored collection is too large")
    seen = set()
    for category in state["categories"]:
        if set(category) != {"id", "zh", "en"} or category["id"] in CATALOG["categories"] or category["id"] in seen:
            raise ValueError("Invalid stored category")
        seen.add(_identity(category["id"]))
        _text(category["zh"], 24)
        _text(category["en"], 24)
    seen = set()
    for habit in state["habits"] + state["removed_habits"]:
        if set(habit) != {"id", "zh", "en", "category", "icon"} or habit["id"] in seen:
            raise ValueError("Invalid stored habit")
        seen.add(_identity(habit["id"]))
        _text(habit["zh"], 60)
        _text(habit["en"], 60)
        _text(habit["icon"], 16)
        _category(state, habit["category"])
    seen = set()
    for completion in state["history"]:
        if set(completion) != {"id", "date"}:
            raise ValueError("Invalid completion record")
        identity = (_identity(completion["id"]), _day(completion["date"]))
        if identity in seen:
            raise ValueError("Duplicate completion record")
        seen.add(identity)
    if len(set(state["done"])) != len(state["done"]) or any(not _ID.fullmatch(key) for key in state["done"]):
        raise ValueError("Invalid completed habits")
    if len(set(state["owned"])) != len(state["owned"]) or not set(DEFAULT_ITEMS.values()).issubset(state["owned"]) or any(key not in ITEMS or ITEMS[key]["slot"] == "color" for key in state["owned"]):
        raise ValueError("Invalid owned items")
    if not isinstance(state["equipped"], dict) or not set(state["equipped"]).issubset(SLOTS):
        raise ValueError("Invalid equipped slots")
    if any(key not in state["owned"] or ITEMS[key]["slot"] != slot for slot, key in state["equipped"].items()) or not set(DEFAULT_ITEMS).issubset(state["equipped"]):
        raise ValueError("Invalid equipped item")
    if not isinstance(state["cards"], dict) or set(state["cards"]) != set(CATALOG["skins"]) - {"pink"} or any(type(n) is not int or n < 0 for n in state["cards"].values()):
        raise ValueError("Invalid color cards")
    checkin = state["checkin"]
    if not isinstance(checkin, dict) or set(checkin) != {"mood", "capacity"} or checkin["mood"] not in MOODS | {""} or checkin["capacity"] not in CAPACITIES | {""}:
        raise ValueError("Invalid check-in")
    seen = set()
    for entry in state["journal"]:
        if set(entry) != {"id", "date", "mood", "note", "photo"} or entry["id"] in seen or entry["mood"] not in MOODS:
            raise ValueError("Invalid journal entry")
        seen.add(_identity(entry["id"]))
        _day(entry["date"])
        _text(entry["note"], 500, empty=True, multiline=True)
        # Photos were fully validated at creation; keep subsequent reads bounded.
        if not isinstance(entry["photo"], str) or len(entry["photo"]) > 4 * ((MAX_PHOTO_BYTES + 2) // 3) + 40 or (entry["photo"] and not re.fullmatch(r"data:image/(png|jpeg|webp);base64,[A-Za-z0-9+/]*={0,2}", entry["photo"])):
            raise ValueError("Invalid stored photo")
