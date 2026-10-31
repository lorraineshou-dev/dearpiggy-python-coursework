"""Behavioral tests for authoritative game rules and transactional persistence."""

import base64
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import date, timedelta
import json
from pathlib import Path
import sqlite3
import struct
import sys
from tempfile import TemporaryDirectory
import unittest
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from game import CATALOG, MAX_CATEGORIES, MAX_HABITS, MAX_JOURNAL, MAX_PHOTO_BYTES, apply_action, new_state, recommendations, rollover, validate_photo
from storage import Store


TODAY = "2026-11-01"
TOMORROW = "2026-11-02"

# Independent 2x2 image fixtures, created once with an image encoder. The tests
# themselves require only Python's standard library, not Pillow or a browser.
JPEG = (
    "data:image/jpeg;base64,/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwClRRRXyB9Uf//Z"
)
WEBP = "data:image/webp;base64,UklGRjoAAABXRUJQVlA4IC4AAADQAQCdASoCAAIAAUAmJaACdLoB+AADsAD+5Qr/+mkeNI8aR8xb/5xLHU7u0AAA"


def png_uri(width=1, height=1, pixels=None):
    def chunk(kind, content):
        return struct.pack(">I", len(content)) + kind + content + struct.pack(">I", zlib.crc32(kind + content) & 0xFFFFFFFF)
    header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    pixels = b"\0\xff\0\0" if pixels is None else pixels
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(pixels)) + chunk(b"IEND", b"")
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


class GameTests(unittest.TestCase):
    def setUp(self):
        self.state = new_state(TODAY)

    def act(self, action, today=TODAY, **form):
        return apply_action(self.state, action, form, today=today)

    def rejected_without_change(self, action, **form):
        before = deepcopy(self.state)
        with self.assertRaises(ValueError):
            self.act(action, **form)
        self.assertEqual(self.state, before)

    def test_defaults_are_independent_and_builtin_items_available(self):
        other = new_state(TODAY)
        self.assertEqual(self.state["energy"], 0)
        self.assertEqual(self.state["equipped"], {"seat": "blanket", "background": "room"})
        self.state["habits"][0]["zh"] = "changed"
        self.assertNotEqual(other["habits"][0]["zh"], "changed")
        self.assertNotEqual(CATALOG["habits"][0]["zh"], "changed")

    def test_six_reward_cap_but_growth_continues(self):
        for row in CATALOG["habits"]:
            if row["id"] not in {habit["id"] for habit in self.state["habits"]}:
                self.act("add_habit", catalog_id=row["id"])
            self.act("complete", id=row["id"], reward="999", energy="90000", total="90000", date=TOMORROW)
        self.assertEqual(self.state["energy"], 60)
        self.assertEqual(self.state["total"], 10)
        self.assertEqual(self.state["reward_count"], 6)
        self.assertEqual(len(self.state["history"]), 10)
        self.assertEqual({row["date"] for row in self.state["history"]}, {TODAY})
        self.rejected_without_change("complete", id="water")

    def test_rollover_resets_daily_state_without_erasing_progress(self):
        self.act("complete", id="water")
        self.act("checkin", mood="tired", capacity="low")
        self.act("rest", enabled="on")
        rollover(self.state, TOMORROW)
        self.assertEqual(self.state["done"], [])
        self.assertEqual(self.state["reward_count"], 0)
        self.assertEqual(self.state["checkin"], {"mood": "", "capacity": ""})
        self.assertFalse(self.state["rest"])
        self.assertEqual(self.state["energy"], 10)
        self.act("complete", today=TOMORROW, id="water")
        self.assertEqual((self.state["energy"], self.state["total"]), (20, 2))
        rollover(self.state, TODAY)
        self.rejected_without_change("complete", id="water")

    def test_delete_restore_and_add_again_cannot_repeat_reward(self):
        self.act("complete", id="water")
        self.act("delete_habit", id="water")
        self.rejected_without_change("complete", id="water")
        self.act("restore_habit", id="water")
        self.rejected_without_change("complete", id="water")
        self.act("delete_habit", id="water")
        self.act("add_habit", catalog_id="water")
        self.rejected_without_change("complete", id="water")
        self.assertEqual((self.state["energy"], self.state["total"]), (10, 1))

    def test_custom_duplicates_and_recreation_preserve_identity(self):
        self.act("add_habit", title="Read one page", category="mind")
        identity = self.state["habits"][-1]["id"]
        self.rejected_without_change("add_habit", title="READ ONE PAGE", category="body")
        self.act("complete", id=identity)
        self.act("delete_habit", id=identity)
        self.act("add_habit", title=" Read one page ", category="body")
        self.assertEqual(self.state["habits"][-1]["id"], identity)
        self.rejected_without_change("complete", id=identity)
        self.act("edit_habit", id=identity, title="Read gently", category="rest")
        self.assertIn(identity, self.state["done"])
        self.rejected_without_change("complete", id=identity)
        self.rejected_without_change("edit_habit", id="water", title="Changed builtin", category="body")

    def test_only_current_recommendations_can_autojoin_on_completion(self):
        self.assertIn("daylight", [row["id"] for row in recommendations(self.state)])
        self.act("complete", id="daylight")
        self.assertIn("daylight", [row["id"] for row in self.state["habits"]])
        self.rejected_without_change("complete", id="meal")
        self.act("delete_habit", id="daylight")
        rollover(self.state, TOMORROW)
        self.assertNotIn("daylight", [row["id"] for row in recommendations(self.state)])
        self.rejected_without_change("complete", today=TOMORROW, id="daylight")

    def test_categories_and_custom_habits_crud(self):
        self.act("add_category", title="Creative time")
        identity = self.state["categories"][0]["id"]
        self.act("add_habit", title="Draw a leaf", category=identity)
        habit = self.state["habits"][-1]["id"]
        self.act("edit_category", id=identity, title="Art time")
        self.assertEqual(self.state["categories"][0]["en"], "Art time")
        self.act("delete_habit", id=habit)
        self.act("delete_category", id=identity)
        self.assertEqual(self.state["removed_habits"][0]["category"], "body")
        self.assertEqual(self.state["categories"], [])
        self.rejected_without_change("delete_category", id="mind")
        self.rejected_without_change("add_category", title="Body")
        self.rejected_without_change("add_habit", title="Invalid category", category="all")

    def test_profile_language_checkin_and_rest_are_validated(self):
        self.act("welcome")
        self.act("profile", name="Peach", nickname="Learner", music="on")
        self.act("language", lang="en")
        self.assertTrue(self.state["welcomed"])
        self.assertTrue(self.state["music"])
        self.assertEqual(self.state["name"], "Peach")
        self.rejected_without_change("profile", name="", nickname="Learner")
        self.rejected_without_change("language", lang="javascript")
        self.rejected_without_change("checkin", mood="invented", capacity="high")
        self.act("checkin", mood="tired", capacity="low")
        self.assertEqual(len(recommendations(self.state)), 1)
        self.act("rest", enabled="on")
        self.act("complete", id="water")
        self.assertTrue(self.state["rest"])
        self.assertEqual(self.state["energy"], 10)

    def test_shop_uses_catalogue_price_and_slots(self):
        self.rejected_without_change("buy", id="glasses", price="0", energy="999999")
        self.state["energy"] = 3000  # Trusted fixture; no HTTP action can do this.
        self.act("buy", id="glasses", price="1", slot="clothes")
        self.assertEqual(self.state["energy"], 2580)
        self.assertEqual(self.state["equipped"]["eyes"], "glasses")
        self.rejected_without_change("buy", id="glasses")
        self.act("buy", id="rimless")
        self.assertEqual(self.state["equipped"]["eyes"], "rimless")
        self.assertIn("glasses", self.state["owned"])
        self.act("equip", id="rimless")
        self.assertNotIn("eyes", self.state["equipped"])
        self.act("equip", id="glasses")
        self.assertEqual(self.state["equipped"]["eyes"], "glasses")
        self.act("buy", id="sofa")
        self.act("equip", id="sofa")
        self.assertEqual(self.state["equipped"]["seat"], "blanket")
        self.rejected_without_change("equip", id="coat")
        self.rejected_without_change("buy", id="not-an-item")

    def test_color_cards_persist_until_consumed_and_pink_is_free(self):
        self.state["energy"] = 2000
        self.act("buy", id="color-black")
        self.act("buy", id="color-black")
        self.assertEqual(self.state["cards"]["black"], 2)
        self.assertEqual(self.state["skin"], "pink")
        self.assertNotIn("color-black", self.state["owned"])
        self.act("use_color", color="black")
        self.assertEqual(self.state["cards"]["black"], 1)
        self.rejected_without_change("use_color", color="black")
        self.rejected_without_change("use_color", color="brown", cards="999")
        self.act("use_color", color="pink")
        self.assertEqual(self.state["energy"], 800)
        self.act("use_color", color="black")
        self.assertEqual(self.state["cards"]["black"], 0)
        self.assertEqual(self.state["skin"], "black")

    def test_journal_photo_validation_and_deletion(self):
        photo = png_uri()
        self.assertEqual(validate_photo(photo), photo)
        self.act("save_journal", mood="calm", note="A small moment.\nStill here.", photo_data=photo)
        entry = self.state["journal"][0]
        self.assertEqual(entry["photo"], photo)
        self.assertEqual(entry["date"], TODAY)
        self.assertEqual(self.state["energy"], 0)
        self.act("delete_journal", id=entry["id"])
        self.assertEqual(self.state["journal"], [])
        for invalid in ("data:image/svg+xml;base64,PHN2Zz4=", "data:image/png;base64,aGVsbG8=", "https://example.invalid/photo.png", "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff\xd9").decode()):
            self.rejected_without_change("save_journal", mood="calm", note="", photo_data=invalid)
        self.rejected_without_change("save_journal", mood="other", note="")
        self.rejected_without_change("save_journal", mood="calm", note="x" * 501)

    def test_photo_size_pixels_and_checksums_are_bounded(self):
        oversized = "data:image/png;base64," + base64.b64encode(b"a" * (MAX_PHOTO_BYTES + 1)).decode()
        for invalid in (oversized, png_uri(5000, 1), png_uri(1, 1, b"\0" * 100000), png_uri(1, 1, b"\5\xff\0\0")):
            with self.assertRaises(ValueError):
                validate_photo(invalid)
        data = bytearray(base64.b64decode(png_uri().split(",", 1)[1]))
        data[20] ^= 1
        with self.assertRaises(ValueError):
            validate_photo("data:image/png;base64," + base64.b64encode(data).decode())

    def test_real_jpeg_and_webp_fixtures_and_truncated_containers(self):
        for photo in (JPEG, WEBP):
            self.assertEqual(validate_photo(photo), photo)
            self.act("save_journal", mood="happy", photo_data=photo)
            self.assertEqual(self.state["journal"][0]["photo"], photo)
            prefix, content = photo.split(",", 1)
            truncated = prefix + "," + base64.b64encode(base64.b64decode(content)[:-3]).decode()
            with self.assertRaises(ValueError):
                validate_photo(truncated)

    def test_habit_and_category_collection_limits(self):
        for i in range(MAX_HABITS - len(self.state["habits"])):
            self.act("add_habit", title=f"Little act {i}", category="body")
        self.rejected_without_change("add_habit", title="Too many", category="body")
        self.rejected_without_change("complete", id="daylight")
        for i in range(MAX_CATEGORIES):
            self.act("add_category", title=f"Category {i}")
        self.rejected_without_change("add_category", title="Too many")

    def test_collection_limits_and_unknown_actions_do_not_partially_write(self):
        for i in range(MAX_JOURNAL):
            self.act("save_journal", mood="calm", note=str(i))
        self.rejected_without_change("save_journal", mood="calm", note="one too many")
        self.rejected_without_change("set_energy", energy="9999")
        self.rejected_without_change("profile", today=TOMORROW, name="x" * 25, nickname="")
        with self.assertRaises(ValueError):
            apply_action(self.state, "profile", {"name": ["x"]}, today=TODAY)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.path = Path(self.directory.name) / "players.sqlite3"
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        self.directory.cleanup()

    def test_persistence_and_session_isolation(self):
        self.store.mutate("alice", lambda state: apply_action(state, "complete", {"id": "water"}))
        self.store.mutate("alice", lambda state: apply_action(state, "save_journal", {"mood": "calm", "note": "private note", "photo_data": png_uri()}))
        self.assertEqual(self.store.get("bob")["energy"], 0)
        self.assertEqual(self.store.get("bob")["journal"], [])
        with Store(self.path) as reopened:
            self.assertEqual(reopened.get("alice")["energy"], 10)
            self.assertEqual(reopened.get("alice")["journal"][0]["note"], "private note")
            self.assertEqual(reopened.get("alice")["journal"][0]["photo"], png_uri())
        detached = self.store.get("alice")
        detached["energy"] = 99999
        self.assertEqual(self.store.get("alice")["energy"], 10)

    def test_failed_callback_and_invalid_schema_rollback(self):
        original = self.store.get("alice")
        def failed(state):
            state["energy"] += 1000
            raise ValueError("No commit")
        with self.assertRaises(ValueError):
            self.store.mutate("alice", failed)
        self.assertEqual(self.store.get("alice"), original)
        with self.assertRaises(ValueError):
            self.store.mutate("alice", lambda state: state.update(chats=[{"content": "must not persist"}]))
        self.assertEqual(self.store.get("alice"), original)
        with self.assertRaises(ValueError):
            self.store.get("alice'; DROP TABLE player_state;--")
        self.assertEqual(self.store.get("alice"), original)

    def test_get_persists_calendar_rollover(self):
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        old = new_state(yesterday)
        apply_action(old, "complete", {"id": "water"}, today=yesterday)
        apply_action(old, "rest", {"enabled": "on"}, today=yesterday)
        with sqlite3.connect(self.path) as db:
            db.execute("INSERT INTO player_state VALUES (?, ?)", ("alice", json.dumps(old)))
        current = self.store.get("alice")
        self.assertEqual(current["date"], date.today().isoformat())
        self.assertEqual(current["energy"], 10)
        self.assertEqual(current["done"], [])
        self.assertFalse(current["rest"])
        with sqlite3.connect(self.path) as db:
            persisted = json.loads(db.execute("SELECT payload FROM player_state WHERE session_id = ?", ("alice",)).fetchone()[0])
        self.assertEqual(persisted, current)

    def test_concurrent_duplicate_completion_awards_once(self):
        self.store.get("alice")
        with Store(self.path) as second:
            stores = [self.store, second]
            def complete(index):
                try:
                    stores[index % 2].mutate("alice", lambda state: apply_action(state, "complete", {"id": "water"}))
                    return True
                except ValueError:
                    return False
            with ThreadPoolExecutor(max_workers=8) as pool:
                successes = list(pool.map(complete, range(16)))
        self.assertEqual(sum(successes), 1)
        state = self.store.get("alice")
        self.assertEqual((state["energy"], state["total"], len(state["history"])), (10, 1, 1))

    def test_concurrent_updates_do_not_lose_writes(self):
        self.store.get("alice")
        with Store(self.path) as second:
            def add(index):
                store = self.store if index % 2 else second
                store.mutate("alice", lambda state: apply_action(state, "add_habit", {"title": f"Custom habit {index}", "category": "mind"}))
            with ThreadPoolExecutor(max_workers=8) as pool:
                list(pool.map(add, range(20)))
        self.assertEqual(len(self.store.get("alice")["habits"]), 23)

    def test_color_inventory_survives_reopening_and_consumption(self):
        self.store.mutate("alice", lambda state: state.update(energy=1200))
        self.store.mutate("alice", lambda state: apply_action(state, "buy", {"id": "color-black"}))
        self.store.mutate("alice", lambda state: apply_action(state, "buy", {"id": "color-black"}))
        with Store(self.path) as reopened:
            self.assertEqual(reopened.get("alice")["cards"]["black"], 2)
            reopened.mutate("alice", lambda state: apply_action(state, "use_color", {"color": "black"}))
        self.assertEqual(self.store.get("alice")["cards"]["black"], 1)
        self.assertEqual(self.store.get("alice")["skin"], "black")
        self.assertEqual(self.store.get("alice")["energy"], 0)


if __name__ == "__main__":
    unittest.main()
