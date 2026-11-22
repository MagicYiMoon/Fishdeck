import importlib
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from fishdeck.memory import diary_rows


def event(owner, origin, group=""):
    return types.SimpleNamespace(
        get_platform_name=lambda: "aiocqhttp",
        get_group_id=lambda: group,
        get_sender_id=lambda: owner,
        unified_msg_origin=origin,
    )


class TestAstrHost(unittest.IsolatedAsyncioTestCase):
    async def test_bind_and_read_only_as_private_owner(self):
        with tempfile.TemporaryDirectory() as tmp:

            def decorator(*args, **kwargs):
                return lambda f: f

            class Star:
                def __init__(self, context):
                    pass

            api = types.SimpleNamespace(AstrBotConfig=dict, logger=types.SimpleNamespace())
            star = types.SimpleNamespace(
                Context=object,
                Star=Star,
                register=decorator,
                StarTools=types.SimpleNamespace(get_data_dir=lambda name: Path(tmp)),
            )
            filters = types.SimpleNamespace(
                PermissionType=types.SimpleNamespace(ADMIN="admin"),
                llm_tool=decorator,
                command=decorator,
                permission_type=decorator,
            )
            evt = types.SimpleNamespace(AstrMessageEvent=object, filter=filters)
            with patch.dict(
                sys.modules,
                {
                    "astrbot": types.ModuleType("astrbot"),
                    "astrbot.api": api,
                    "astrbot.api.event": evt,
                    "astrbot.api.star": star,
                },
            ):
                module = importlib.import_module("fishdeck.main")
            plugin = module.FishDeck(object(), {"watch_key": "fwr_simulated"})
            owner, other, group = event("1", "p:1"), event("2", "p:2"), event("1", "p:1", "20")

            async def get(_key, path, cursor=""):
                if path == "state":
                    return {"fish": "我的鱼#36", "stage": "live"}
                return {"cursor": "cursor1", "items": []}

            plugin._get = get
            self.assertIn("管理员", await plugin._owner(group, "绑定", ""))
            self.assertIn("#36", await plugin._owner(owner, "绑定", ""))
            self.assertIn("已有绑定", await plugin._owner(other, "绑定", ""))
            self.assertIn("基准", await plugin._owner(owner, "同步", ""))
            plugin._memory(plugin._binding()).merge(diary_rows("11:33 抵达：医院", "2026-11-22"))
            self.assertIn("医院", await plugin.recall(owner, "医院"))
            self.assertNotIn("医院", await plugin.recall(other, "医院"))
            self.assertNotIn("医院", await plugin.recall(group, "医院"))
            self.assertIn("已清除 1 条", await plugin._owner(owner, "清除确认", ""))
            self.assertNotIn("医院", await plugin.recall(owner, "医院"))

            summary = "2026-11-25 19:30 在海边影院一起看电影"
            self.assertIn("尚未", await plugin.remember_agreement(owner, "#108", summary))
            self.assertNotIn("海边影院", await plugin.recall(owner, kind="agreement"))
            plugin.config["allow_agreement_write"] = True
            for outsider in (other, group, event("2", "p:1")):
                self.assertIn("仅在", await plugin.remember_agreement(outsider, "#108", summary))
            self.assertIn("未写入", await plugin.remember_agreement(owner, "#36", summary))
            self.assertIn("未写入", await plugin.remember_agreement(owner, "#108", "fwr_sensitive"))
            self.assertIn("已记", await plugin.remember_agreement(owner, "#108", summary))
            self.assertIn("已有", await plugin.remember_agreement(owner, "#108", summary))
            self.assertIn("【约定 #108】", await plugin._owner(owner, "查询", "#108"))
            self.assertNotIn(summary, await plugin.recall(owner, "#10", kind="agreement"))
            plugin.config["allow_agreement_write"] = False
            self.assertIn(summary, await plugin.recall(owner, "#108", kind="agreement"))
            self.assertIn("尚未", await plugin.remember_agreement(owner, "#109", summary))
