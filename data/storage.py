import json
import os
from astrbot.api import logger
from .runtime_paths import get_runtime_file_path

class Storage:
    def __init__(self, filepath=None):
        if filepath is None:
            filepath = get_runtime_file_path("df_red_data.json")
        self.filepath = os.path.abspath(filepath)
        self.data = {
            "group_origins": [],
            "users": {} # sender_id -> {"name": "", "platform": "qq", "openid": "", "access_token": "", "last_match_time": "", "last_room_id": "", "last_item_flow_keys": [], "assets": []}
        }
        self.load()

    def load(self):
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    file_data = json.load(f)
                    self.data.update(file_data)
            except Exception as e:
                logger.warning(f"Failed to load storage from {self.filepath}: {e}")

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.filepath), exist_ok=True)
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(self.data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save storage to {self.filepath}: {e}")

    def add_user(self, sender_id, openid, access_token, name="", platform="qq", role_id=""):
        if sender_id not in self.data["users"]:
            self.data["users"][sender_id] = {}
        self.data["users"][sender_id].update({
            "name": name,
            "platform": platform,
            "openid": openid,
            "access_token": access_token,
            "role_id": role_id or self.data["users"][sender_id].get("role_id", ""),
            "last_match_time": self.data["users"][sender_id].get("last_match_time", ""),
            "last_room_id": self.data["users"][sender_id].get("last_room_id", ""),
            "last_item_flow_keys": self.data["users"][sender_id].get("last_item_flow_keys", []),
            "assets": self.data["users"][sender_id].get("assets", [])
        })
        self.save()

    def remove_user(self, sender_id):
        if sender_id in self.data["users"]:
            del self.data["users"][sender_id]
            self.save()

    def add_group(self, origin):
        if origin not in self.data["group_origins"]:
            self.data["group_origins"].append(origin)
            self.save()

    def remove_group(self, origin):
        if origin in self.data["group_origins"]:
            self.data["group_origins"].remove(origin)
            self.save()
            return True
        return False

    def get_users(self):
        return self.data.get("users", {})

    def get_groups(self):
        return self.data.get("group_origins", [])

    def update_user_state(self, sender_id, key, value):
        if sender_id in self.data["users"]:
            self.data["users"][sender_id][key] = value
            self.save()
