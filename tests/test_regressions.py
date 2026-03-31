import asyncio
import importlib
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock


REPO_PARENT = Path(__file__).resolve().parents[2]
if str(REPO_PARENT) not in sys.path:
    sys.path.insert(0, str(REPO_PARENT))
TEST_TMP_ROOT = Path(__file__).resolve().parent / ".tmp"
TEST_TMP_ROOT.mkdir(parents=True, exist_ok=True)


class _DummyLogger:
    def __init__(self):
        self.warning_messages = []

    def info(self, *args, **kwargs):
        return None

    def warning(self, message, *args, **kwargs):
        self.warning_messages.append(str(message))

    def error(self, *args, **kwargs):
        return None

    def debug(self, *args, **kwargs):
        return None


class _DummyCookieJar:
    def filter_cookies(self, url):
        return {}


class _DummyClientSession:
    def __init__(self, *args, **kwargs):
        self.closed = False
        self.cookie_jar = _DummyCookieJar()

    async def close(self):
        self.closed = True


class _DummyClientTimeout:
    def __init__(self, *args, **kwargs):
        return None


class _DummyClientError(Exception):
    pass


class _DummyContentTypeError(Exception):
    pass


class _DummyPlain:
    def __init__(self, text):
        self.text = text


class _DummyImage:
    @staticmethod
    def fromBase64(value):
        return value


class _DummyFilter:
    @staticmethod
    def command(_name):
        def decorator(func):
            return func

        return decorator


class _DummyStar:
    def __init__(self, context):
        self.context = context


class _DummyContext:
    async def send_message(self, origin, message):
        return None


def _dummy_register(*args, **kwargs):
    def decorator(cls):
        return cls

    return decorator


class _DummyStarTools:
    @staticmethod
    def get_data_dir(name):
        return Path.cwd() / ".runtime_data"


if "aiohttp" not in sys.modules:
    aiohttp = types.ModuleType("aiohttp")
    aiohttp.ClientSession = _DummyClientSession
    aiohttp.ClientTimeout = _DummyClientTimeout
    aiohttp.CookieJar = _DummyCookieJar
    aiohttp.ClientError = _DummyClientError
    aiohttp.ContentTypeError = _DummyContentTypeError
    sys.modules["aiohttp"] = aiohttp

if "astrbot" not in sys.modules:
    astrbot = types.ModuleType("astrbot")
    api = types.ModuleType("astrbot.api")
    event = types.ModuleType("astrbot.api.event")
    message_components = types.ModuleType("astrbot.api.message_components")
    star = types.ModuleType("astrbot.api.star")

    api.logger = _DummyLogger()
    event.filter = _DummyFilter()
    event.AstrMessageEvent = object
    event.MessageChain = object
    message_components.Plain = _DummyPlain
    message_components.Image = _DummyImage
    star.Context = _DummyContext
    star.Star = _DummyStar
    star.StarTools = _DummyStarTools
    star.register = _dummy_register

    sys.modules["astrbot"] = astrbot
    sys.modules["astrbot.api"] = api
    sys.modules["astrbot.api.event"] = event
    sys.modules["astrbot.api.message_components"] = message_components
    sys.modules["astrbot.api.star"] = star

PACKAGE_NAME = Path(__file__).resolve().parents[1].name
runtime_paths = importlib.import_module(f"{PACKAGE_NAME}.data.runtime_paths")
secret_store = importlib.import_module(f"{PACKAGE_NAME}.data.secret_store")
storage_module = importlib.import_module(f"{PACKAGE_NAME}.data.storage")
game_api_module = importlib.import_module(f"{PACKAGE_NAME}.api.game_api")
red_detector_module = importlib.import_module(f"{PACKAGE_NAME}.monitor.red_detector")
main_module = importlib.import_module(f"{PACKAGE_NAME}.main")
GameAPI = game_api_module.GameAPI
Storage = storage_module.Storage
RedDetector = red_detector_module.RedDetector
DeltaForceRedPlugin = main_module.DeltaForceRedPlugin


class RuntimePathsRegressionTests(unittest.TestCase):
    def test_framework_runtime_dir_retries_after_initial_failure(self):
        resolved_runtime_dir = Path(tempfile.gettempdir()) / "df-red-framework-runtime"
        calls = {"count": 0}

        def fake_get_data_dir(_plugin_name):
            calls["count"] += 1
            if calls["count"] == 1:
                raise RuntimeError("framework not ready")
            return resolved_runtime_dir

        with mock.patch.object(runtime_paths.StarTools, "get_data_dir", side_effect=fake_get_data_dir):
            runtime_paths._FRAMEWORK_RUNTIME_DIR = None
            runtime_paths._FRAMEWORK_RUNTIME_DIR_FAILURE_LOGGED = False

            self.assertIsNone(runtime_paths._get_framework_runtime_dir())
            self.assertEqual(
                runtime_paths._get_framework_runtime_dir(),
                resolved_runtime_dir.resolve(),
            )
            self.assertEqual(calls["count"], 2)

    def test_custom_legacy_relative_paths_are_migrated_from_legacy_dirs(self):
        runtime_dir = TEST_TMP_ROOT / "runtime"
        plugin_root = TEST_TMP_ROOT / "plugin_root"
        legacy_dir = TEST_TMP_ROOT / "legacy_plugin"
        captured = {}

        def fake_copy(target_path, legacy_paths):
            captured["target_path"] = Path(target_path)
            captured["legacy_paths"] = [Path(path) for path in legacy_paths]
            return Path(target_path)

        with (
            mock.patch.object(runtime_paths, "PLUGIN_ROOT", plugin_root),
            mock.patch.object(runtime_paths, "FALLBACK_RUNTIME_DIR", TEST_TMP_ROOT / "fallback"),
            mock.patch.object(runtime_paths, "get_runtime_data_dir", return_value=runtime_dir),
            mock.patch.object(runtime_paths, "_get_legacy_runtime_dirs", return_value=[legacy_dir]),
            mock.patch.object(runtime_paths, "_copy_legacy_file_if_needed", side_effect=fake_copy),
        ):
            target_path = runtime_paths.get_runtime_file_path(
                "new.json",
                legacy_relative_paths=["nested/old.json"],
            )

        self.assertEqual(Path(target_path), runtime_dir / "new.json")
        self.assertIn(
            (legacy_dir / "nested" / "old.json").resolve(),
            [path.resolve() for path in captured["legacy_paths"]],
        )


class SecretProtectorRegressionTests(unittest.TestCase):
    def test_plaintext_warning_is_logged_once_per_instance(self):
        logger = _DummyLogger()
        with mock.patch.object(secret_store, "logger", logger):
            protector = secret_store.SecretProtector()
            self.assertEqual(protector.unprotect("legacy-openid"), "legacy-openid")
            self.assertEqual(protector.unprotect("legacy-openid"), "legacy-openid")

        self.assertEqual(len(logger.warning_messages), 1)
        self.assertIn("legacy plaintext secret value", logger.warning_messages[0])

    def test_windows_dpapi_failure_refuses_plaintext_storage(self):
        logger = _DummyLogger()
        with (
            mock.patch.object(secret_store, "logger", logger),
            mock.patch.object(secret_store.os, "name", "nt"),
            mock.patch.object(
                secret_store.SecretProtector,
                "_protect_with_dpapi",
                side_effect=OSError("dpapi unavailable"),
            ),
        ):
            protector = secret_store.SecretProtector()
            with self.assertRaises(secret_store.SecretProtectionError):
                protector.protect("token-value")
            with self.assertRaises(secret_store.SecretProtectionError):
                protector.protect("token-value")

        self.assertEqual(len(logger.warning_messages), 1)
        self.assertIn("refusing to store sensitive values", logger.warning_messages[0])


class StorageRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_group_origin_is_normalized_to_string(self):
        with mock.patch.object(Storage, "_load_from_disk", return_value=({"group_origins": [], "users": {}}, False)):
            storage = Storage(filepath=TEST_TMP_ROOT / "storage-normalize.json")

        async def fake_persist(new_data=None):
            if new_data is not None:
                storage.data = json.loads(json.dumps(new_data))

        with mock.patch.object(storage, "_persist_locked", side_effect=fake_persist):
            self.assertTrue(await storage.add_group(123))
            self.assertFalse(await storage.add_group("123"))
            self.assertEqual(await storage.get_groups(), ["123"])
            self.assertTrue(await storage.remove_group(123))
            self.assertEqual(await storage.get_groups(), [])


class GameAPIRegressionTests(unittest.IsolatedAsyncioTestCase):
    def test_merge_cookies_accepts_json_and_cookie_header_strings(self):
        merged = GameAPI._merge_cookies(
            {"qrsig": "alpha"},
            json.dumps({"pt_login_sig": "beta"}),
            "p_skey=gamma; pt4_token=delta",
            json.dumps(json.dumps({"double": "encoded"})),
        )

        self.assertEqual(
            merged,
            {
                "qrsig": "alpha",
                "pt_login_sig": "beta",
                "p_skey": "gamma",
                "pt4_token": "delta",
                "double": "encoded",
            },
        )

    async def test_access_token_exchange_rejects_untrusted_redirect_host(self):
        api = GameAPI()
        request_mock = mock.AsyncMock(
            return_value=(
                {
                    "status": 302,
                    "headers": {"Location": "https://evil.example/callback?code=abc"},
                    "cookies": {},
                },
                "",
            )
        )

        with mock.patch.object(api, "_request_text", request_mock):
            result = await api.get_access_token_by_cookie({"p_skey": "token"})

        self.assertFalse(result["status"])
        self.assertEqual(request_mock.await_count, 1)

    async def test_session_uses_dummy_cookie_jar_when_available(self):
        created = {}

        class _ObservedDummyCookieJar:
            pass

        class _ObservedSession:
            def __init__(self, *args, **kwargs):
                self.closed = False
                self.cookie_jar = kwargs.get("cookie_jar")
                created["cookie_jar"] = self.cookie_jar

            async def close(self):
                self.closed = True

        api = GameAPI()
        with (
            mock.patch.object(game_api_module.aiohttp, "ClientSession", _ObservedSession),
            mock.patch.object(game_api_module.aiohttp, "DummyCookieJar", _ObservedDummyCookieJar, create=True),
        ):
            session = await api._get_session()

        self.assertIs(session.cookie_jar, created["cookie_jar"])
        self.assertIsInstance(session.cookie_jar, _ObservedDummyCookieJar)


class RedDetectorRegressionTests(unittest.IsolatedAsyncioTestCase):
    def test_flow_key_includes_additional_fields_without_breaking_legacy_matching(self):
        first_item = {
            "dtEventTime": "2026-03-31 12:00:00",
            "iGoodsId": "1001",
            "AddOrReduce": "+1",
            "Reason": "撤离带出",
            "Name": "样本A",
            "AfterCount": 1,
        }
        second_item = {
            **first_item,
            "Name": "样本B",
            "AfterCount": 2,
        }

        legacy_key = RedDetector._build_legacy_flow_key(first_item)
        self.assertEqual(legacy_key, RedDetector._build_legacy_flow_key(second_item))
        self.assertNotEqual(RedDetector._build_flow_key(first_item), RedDetector._build_flow_key(second_item))
        self.assertIn(legacy_key, RedDetector._build_flow_key_variants(first_item))

    async def test_check_all_users_keeps_other_tasks_running_after_one_failure(self):
        storage = mock.AsyncMock()
        storage.get_users = mock.AsyncMock(return_value={"user-a": {}, "user-b": {}})
        detector = RedDetector(storage, context=mock.Mock(), api=mock.Mock())
        started = asyncio.Event()
        completed = []

        async def fake_check_user(sender_id, user_data):
            if sender_id == "user-a":
                started.set()
                raise RuntimeError("boom")
            await started.wait()
            await asyncio.sleep(0)
            completed.append(sender_id)

        detector.check_user = fake_check_user

        await detector.check_all_users()

        self.assertEqual(completed, ["user-b"])

    async def test_retry_pending_broadcasts_keeps_only_still_failing_targets(self):
        storage = mock.AsyncMock()
        storage.get_groups = mock.AsyncMock(return_value=["group:1", "group:2", "group:3"])
        storage.update_user_state = mock.AsyncMock(return_value=True)
        detector = RedDetector(storage, context=mock.Mock(), api=mock.Mock())
        detector.broadcast_message = mock.AsyncMock(
            return_value={
                "message": "msg",
                "total_groups": 2,
                "success_groups": [{"origin": "group:1"}],
                "failed_groups": [{"origin": "group:2", "error": "boom"}],
            }
        )
        user_data = {
            "pending_broadcasts": [
                {"message": "msg", "origins": ["group:1", "group:2", "group:removed"]}
            ]
        }

        still_pending = await detector.retry_pending_broadcasts("user-a", user_data)

        self.assertTrue(still_pending)
        detector.broadcast_message.assert_awaited_with(
            "msg",
            origins=["group:1", "group:2"],
            write_debug_snapshot=False,
            log_prefix="Retrying pending broadcast",
        )
        storage.update_user_state.assert_awaited_with(
            "user-a",
            pending_broadcasts=[{"message": "msg", "origins": ["group:2"]}],
        )

    async def test_check_user_queues_failed_groups_and_advances_flow_baseline(self):
        storage = mock.AsyncMock()
        storage.update_user_state = mock.AsyncMock(return_value=True)
        api = mock.Mock()
        api.fetch_records_v2 = mock.AsyncMock(
            return_value=[{"dtEventTime": "2026-03-31 12:00:00", "roomId": "room-1"}]
        )
        api.fetch_records = mock.AsyncMock(return_value=[])
        api.fetch_all_item_flows = mock.AsyncMock(
            return_value=[
                {
                    "dtEventTime": "2026-03-31 12:00:05",
                    "iGoodsId": "1001",
                    "AddOrReduce": "+1",
                    "Reason": "撤离带出",
                    "Name": "样本A",
                    "AfterCount": 1,
                }
            ]
        )
        detector = RedDetector(storage, context=mock.Mock(), api=api)
        detector._get_item_catalog_map = mock.AsyncMock(
            return_value={
                "1001": {
                    "primaryClass": "props",
                    "secondClass": "collection",
                    "grade": 6,
                }
            }
        )
        detector._enrich_match_info = mock.AsyncMock(
            return_value={"dtEventTime": "2026-03-31 12:00:00", "roomId": "room-1"}
        )
        detector.ensure_user_role_id = mock.AsyncMock(return_value="role-1")
        detector.broadcast = mock.AsyncMock(
            return_value={
                "message": "msg",
                "total_groups": 2,
                "success_groups": [{"origin": "group:1"}],
                "failed_groups": [{"origin": "group:2", "error": "boom"}],
            }
        )
        user_data = {
            "openid": "openid",
            "access_token": "token",
            "platform": "qq",
            "name": "tester",
            "last_match_time": "2026-03-30 11:59:59",
            "last_room_id": "room-0",
            "last_item_flow_keys": ["legacy-key"],
        }

        await detector._check_user_impl("user-a", user_data)

        expected_flow_key = RedDetector._build_flow_key(
            {
                "dtEventTime": "2026-03-31 12:00:05",
                "iGoodsId": "1001",
                "AddOrReduce": "+1",
                "Reason": "撤离带出",
                "Name": "样本A",
                "AfterCount": 1,
            }
        )
        storage.update_user_state.assert_awaited_with(
            "user-a",
            last_item_flow_keys=[expected_flow_key],
            last_match_time="2026-03-31 12:00:00",
            last_room_id="room-1",
            pending_broadcasts=[
                {
                    "message": "msg",
                    "origins": ["group:2"],
                    "event_time": "2026-03-31 12:00:00",
                    "room_id": "room-1",
                }
            ],
        )


class MainRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def test_finish_bind_handles_storage_write_failure(self):
        storage = mock.AsyncMock()
        command_api = mock.AsyncMock()
        detector = mock.Mock()
        command_api.bind_account = mock.AsyncMock(
            return_value={"status": True, "data": {"role_id": "role-1"}}
        )
        storage.add_user = mock.AsyncMock(side_effect=OSError("disk full"))

        with (
            mock.patch.object(main_module, "Storage", return_value=storage),
            mock.patch.object(main_module, "GameAPI", return_value=command_api),
            mock.patch.object(main_module, "RedDetector", return_value=detector),
        ):
            plugin = DeltaForceRedPlugin(_DummyContext())

        success, message = await plugin._finish_bind(
            "sender-1",
            "tester",
            "qq",
            "openid",
            "token",
        )

        self.assertFalse(success)
        self.assertIn("保存失败", message)

    async def test_set_group_reports_duplicate_binding(self):
        storage = mock.AsyncMock()
        command_api = mock.AsyncMock()
        detector = mock.Mock()
        storage.add_group = mock.AsyncMock(return_value=False)

        with (
            mock.patch.object(main_module, "Storage", return_value=storage),
            mock.patch.object(main_module, "GameAPI", return_value=command_api),
            mock.patch.object(main_module, "RedDetector", return_value=detector),
        ):
            plugin = DeltaForceRedPlugin(_DummyContext())

        class _DummyEvent:
            unified_msg_origin = "group:1"

            @staticmethod
            def plain_result(message):
                return message

        messages = []
        async for result in plugin.set_group(_DummyEvent()):
            messages.append(result)

        self.assertEqual(messages, ["当前群已经设置为播报群，无需重复设置。"])

    async def test_unbind_account_handles_storage_write_failure(self):
        storage = mock.AsyncMock()
        command_api = mock.AsyncMock()
        detector = mock.Mock()
        storage.remove_user = mock.AsyncMock(side_effect=OSError("disk full"))

        with (
            mock.patch.object(main_module, "Storage", return_value=storage),
            mock.patch.object(main_module, "GameAPI", return_value=command_api),
            mock.patch.object(main_module, "RedDetector", return_value=detector),
        ):
            plugin = DeltaForceRedPlugin(_DummyContext())

        class _DummyEvent:
            @staticmethod
            def get_sender_id():
                return "sender-1"

            @staticmethod
            def plain_result(message):
                return message

        messages = []
        async for result in plugin.unbind_account(_DummyEvent()):
            messages.append(result)

        self.assertEqual(messages, ["解绑失败，请检查插件运行目录写入权限后重试。"])

    async def test_unset_group_handles_storage_write_failure(self):
        storage = mock.AsyncMock()
        command_api = mock.AsyncMock()
        detector = mock.Mock()
        storage.remove_group = mock.AsyncMock(side_effect=OSError("disk full"))

        with (
            mock.patch.object(main_module, "Storage", return_value=storage),
            mock.patch.object(main_module, "GameAPI", return_value=command_api),
            mock.patch.object(main_module, "RedDetector", return_value=detector),
        ):
            plugin = DeltaForceRedPlugin(_DummyContext())

        class _DummyEvent:
            unified_msg_origin = "group:1"

            @staticmethod
            def plain_result(message):
                return message

        messages = []
        async for result in plugin.unset_group(_DummyEvent()):
            messages.append(result)

        self.assertEqual(messages, ["取消群绑定失败，请检查插件运行目录写入权限后重试。"])


if __name__ == "__main__":
    unittest.main()
