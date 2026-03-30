import aiohttp
import base64
import json
import os
import re
import time
from urllib.parse import unquote
from ..data.runtime_paths import get_runtime_file_path

try:
    from astrbot.api import logger
except ImportError:
    import logging
    logger = logging.getLogger(__name__)

APPID = 101491592
BASE_URL = "https://comm.ams.game.qq.com/ide/"
GAME_API_URL = "https://comm.aci.game.qq.com/main"
LOGIN_APP_ID = 716027609
QQ_QR_SHOW_URL = "https://xui.ptlogin2.qq.com/ssl/ptqrshow"
QQ_LOGIN_TICKET_URL = "https://xui.ptlogin2.qq.com/cgi-bin/xlogin"
QQ_LOGIN_STATUS_URL = "https://ssl.ptlogin2.qq.com/ptqrlogin"
WECHAT_QR_URL = "https://open.weixin.qq.com/connect/qrconnect"
WECHAT_QR_STATUS_URL = "https://lp.open.weixin.qq.com/connect/l/qrconnect"
OBJECT_LIST_PARAMS = {
    "iChartId": "316969",
    "iSubChartId": "316969",
    "sIdeToken": "NoOapI",
    "method": "dfm/object.list",
    "source": "2",
}

class GameAPI:
    def __init__(self, platform="qq"):
        self.platform = platform

    @staticmethod
    def _get_item_catalog_cache_path():
        return get_runtime_file_path("item_catalog_cache.json")

    @staticmethod
    def _safe_json_loads(value, default=None):
        if default is None:
            default = {}
        try:
            return json.loads(value)
        except Exception:
            return default

    @staticmethod
    def _get_headers():
        return {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)",
            "Referer": "https://df.qq.com/",
            "Content-Type": "application/x-www-form-urlencoded",
        }

    @staticmethod
    def _get_gtk(p_skey, h=5381):
        for c in str(p_skey or ""):
            h += (h << 5) + ord(c)
        return h & 0x7FFFFFFF

    @staticmethod
    def _get_micro_time():
        return int(time.time() * 1000000)

    @staticmethod
    def _get_cookies(openid, access_token, platform="qq"):
        return {
            "openid": openid,
            "access_token": access_token,
            "acctype": "qc" if platform == "qq" else "wx",
            "appid": str(APPID)
        }

    def create_cookie(self, openid, access_token):
        return self._get_cookies(openid, access_token, self.platform)

    async def _fetch_role_profile(self, session, access_token, openid, access_type):
        params = {
            "needGopenid": 1,
            "sAMSAcctype": access_type,
            "sAMSAccessToken": access_token,
            "sAMSAppOpenId": openid,
            "sAMSSourceAppId": LOGIN_APP_ID,
            "game": "dfm",
            "sCloudApiName": "ams.gameattr.role",
            "area": 36,
            "platid": 1,
            "partition": 36,
        }
        headers = {"referer": "https://df.qq.com/"}
        async with session.get(GAME_API_URL, params=params, headers=headers) as role_resp:
            result = await role_resp.text()

        pattern = r"\{([^}]*)\}"
        matches = re.search(pattern, result)
        if not matches:
            return {}

        pairs_pattern = r"(\w+):('[^']*'|-?\d+|[^,]*)"
        pairs = re.findall(pairs_pattern, matches.group(1))
        role_data = {}
        for key, value in pairs:
            value = value.strip("'")
            if key == "msg":
                try:
                    role_data[key] = value.encode("latin1").decode("gbk")
                except Exception:
                    role_data[key] = value
            else:
                role_data[key] = value

        checkparam = role_data.get("checkparam", "")
        checkparam_parts = checkparam.split("|")
        if len(checkparam_parts) >= 3:
            role_data["role_id"] = checkparam_parts[2]
        return role_data

    @staticmethod
    def _load_item_catalog_cache():
        cache_path = GameAPI._get_item_catalog_cache_path()
        if not os.path.exists(cache_path):
            return None
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict) and isinstance(data.get("items"), list):
                return data
        except Exception as e:
            logger.debug(f"Failed to load item catalog cache: {type(e).__name__}")
        return None

    @staticmethod
    def _save_item_catalog_cache(items):
        cache_path = GameAPI._get_item_catalog_cache_path()
        try:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "updated_at": int(time.time()),
                        "count": len(items),
                        "items": items,
                    },
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.debug(f"Failed to save item catalog cache: {type(e).__name__}")

    async def get_login_token(self):
        params = {
            "appid": LOGIN_APP_ID,
            "daid": 383,
            "style": 33,
            "login_text": "登录",
            "hide_title_bar": 1,
            "hide_border": 1,
            "target": "self",
            "s_url": "https://graph.qq.com/oauth2.0/login_jump",
            "pt_3rd_aid": APPID,
            "pt_feedback_link": f"https://support.qq.com/products/77942?customInfo=milo.qq.com.appid{APPID}",
            "theme": 2,
            "verify_theme": "",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(QQ_LOGIN_TICKET_URL, params=params, headers=self._get_headers()) as resp:
                    return resp.status == 200
        except Exception as e:
            logger.debug(f"Failed to get login token: {type(e).__name__}")
            return False

    @staticmethod
    def _calc_qr_token(qrsig):
        e = 0
        for char in str(qrsig or ""):
            e += (e << 5) + ord(char)
        return e & 2147483647

    async def get_qq_login_qr(self):
        if not await self.get_login_token():
            return {"status": False, "message": "获取登录token失败", "data": {}}

        params = {
            "appid": LOGIN_APP_ID,
            "e": 2,
            "l": "M",
            "s": 3,
            "d": 72,
            "v": 4,
            "t": 0.6142752744667854,
            "daid": 383,
            "pt_3rd_aid": APPID,
            "u1": "https://graph.qq.com/oauth2.0/login_jump",
        }
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(QQ_QR_SHOW_URL, params=params, headers=self._get_headers()) as resp:
                    if resp.status != 200:
                        return {"status": False, "message": "获取二维码失败", "data": {}}
                    image_bytes = await resp.read()
                    qr_sig = resp.cookies.get("qrsig")
                    login_sig = resp.cookies.get("pt_login_sig")
                    qr_sig_value = qr_sig.value if qr_sig else ""
                    login_sig_value = login_sig.value if login_sig else ""
                    if not qr_sig_value:
                        return {"status": False, "message": "获取二维码失败，请重试", "data": {}}
                    cookie_dict = {k: morsel.value for k, morsel in resp.cookies.items()}
                    return {
                        "status": True,
                        "message": "获取成功",
                        "data": {
                            "image_base64": base64.b64encode(image_bytes).decode("utf-8"),
                            "cookie": cookie_dict,
                            "qrSig": qr_sig_value,
                            "qrToken": self._calc_qr_token(qr_sig_value),
                            "loginSig": login_sig_value,
                        },
                    }
        except Exception as e:
            logger.debug(f"Failed to get QQ login qr: {type(e).__name__}")
            return {"status": False, "message": "获取二维码失败", "data": {}}

    async def get_login_status(self, cookie, qr_sig, qr_token, login_sig):
        if not cookie:
            return {"code": -1, "message": "缺少cookie参数", "data": {}}
        try:
            cookies = cookie if isinstance(cookie, dict) else json.loads(cookie)
            cookies = {str(k): str(v) for k, v in cookies.items() if v != ""}
            cookies["qrsig"] = str(qr_sig)
            params = {
                "u1": "https://graph.qq.com/oauth2.0/login_jump",
                "ptqrtoken": qr_token,
                "ptredirect": 0,
                "h": 1,
                "t": 1,
                "g": 1,
                "from_ui": 1,
                "ptlang": 2052,
                "action": f"0-0-{int(time.time() * 1000)}",
                "js_ver": 25040111,
                "js_type": 1,
                "login_sig": login_sig,
                "pt_uistyle": 40,
                "aid": LOGIN_APP_ID,
                "daid": 383,
                "pt_3rd_aid": APPID,
                "o1vId": "378b06c889d9113b39e814ca627809e3",
                "pt_js_version": "530c3f68",
            }
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.get(QQ_LOGIN_STATUS_URL, params=params, headers=self._get_headers()) as resp:
                    if resp.status != 200:
                        return {"code": -5, "message": "响应错误", "data": {}}
                    result = await resp.text()
                    if result == "":
                        return {"code": -1, "message": "qrSig参数不正确", "data": {}}
                    pattern = r"ptuiCB\s*\(\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*,\s*'(.*?)'\s*\)"
                    matches = re.search(pattern, result)
                    if not matches:
                        return {"code": -4, "message": "响应格式错误", "data": {}}
                    code = matches.group(1)
                    message = matches.group(5)
                    if code == "65":
                        return {"code": -2, "message": message, "data": {}}
                    if code == "66":
                        return {"code": 1, "message": message, "data": {}}
                    if code == "67":
                        return {"code": 2, "message": message, "data": {}}
                    if code == "86":
                        return {"code": -3, "message": message, "data": {}}
                    if code != "0":
                        return {"code": -4, "message": message, "data": {}}
                    q_url = matches.group(3)
                    async with session.get(q_url, headers=self._get_headers()) as redirect_resp:
                        all_cookies = dict(cookies)
                        for jar_cookie in session.cookie_jar:
                            all_cookies[str(jar_cookie.key)] = str(jar_cookie.value)
                        for k, morsel in redirect_resp.cookies.items():
                            all_cookies[str(k)] = str(morsel.value)
                    return {"code": 0, "message": "登录成功", "data": {"cookie": all_cookies}}
        except Exception as e:
            logger.debug(f"Failed to get QQ login status: {type(e).__name__}")
            return {"code": -4, "message": "获取登录状态失败", "data": {}}

    async def get_access_token_by_cookie(self, cookie):
        try:
            cookie_text = cookie if isinstance(cookie, str) else json.dumps(cookie)
            if "\\" in cookie_text:
                cookie_text = cookie_text.replace("\\", "")
            cookies = json.loads(cookie_text)
            cookies = {str(k): str(v) for k, v in cookies.items()}
            headers = {
                "referer": "https://xui.ptlogin2.qq.com/",
                "Content-Type": "application/x-www-form-urlencoded",
                "X-G-TK": str(self._get_gtk(cookies.get("p_skey", ""))),
            }
            form_data = {
                "response_type": "code",
                "client_id": str(APPID),
                "redirect_uri": "https://milo.qq.com/comm-htdocs/login/qc_redirect.html?parent_domain=https://df.qq.com&isMiloSDK=1&isPc=1",
                "scope": "",
                "state": "STATE",
                "switch": "",
                "form_plogin": 1,
                "src": 1,
                "update_auth": 1,
                "openapi": 1010,
                "g_tk": self._get_gtk(cookies.get("p_skey", "")),
                "auth_time": int(time.time()),
                "ui": "979D48F3-6CE2-4E95-A789-3BD3187648B6",
            }
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post("https://graph.qq.com/oauth2.0/authorize", data=form_data, headers=headers, allow_redirects=False) as resp:
                    location = resp.headers.get("Location", "")
                    code_match = re.search(r"code=(.*?)&", location)
                    if not code_match:
                        return {"status": False, "message": "Cookie过期，请重新扫码登录", "data": {}}
                    qc_code = code_match.group(1)
                await session.get(location, headers=headers)
                params = {
                    "a": "qcCodeToOpenId",
                    "qc_code": qc_code,
                    "appid": APPID,
                    "redirect_uri": "https://milo.qq.com/comm-htdocs/login/qc_redirect.html",
                    "callback": "miloJsonpCb_86690",
                    "_": self._get_micro_time(),
                }
                async with session.get("https://ams.game.qq.com/ams/userLoginSvr", params=params, headers={"referer": "https://df.qq.com/"}) as resp:
                    result = await resp.text()
                    jsonp_match = re.search(r"try\{miloJsonpCb_86690\((\{.*?\})\);\}catch\(e\)\{\}", result)
                    if not jsonp_match:
                        jsonp_match = re.search(r"miloJsonpCb_86690\((\{.*?\})\)", result)
                    if not jsonp_match:
                        return {"status": False, "message": "AccessToken获取失败", "data": {}}
                    json_data = json.loads(jsonp_match.group(1))
                    if str(json_data.get("iRet")) != "0":
                        return {"status": False, "message": "AccessToken获取失败", "data": {}}
                    return {
                        "status": True,
                        "message": "获取成功",
                        "data": {
                            "access_token": json_data.get("access_token", ""),
                            "expires_in": json_data.get("expires_in", ""),
                            "openid": json_data.get("openid", ""),
                        },
                    }
        except Exception as e:
            logger.debug(f"Failed to get access token by cookie: {type(e).__name__}")
            return {"status": False, "message": "获取access token失败", "data": {}}

    async def get_wechat_login_qr(self):
        params = {
            "appid": "wxfa0c35392d06b82f",
            "scope": "snsapi_login",
            "redirect_uri": "https://iu.qq.com/comm-htdocs/login/milosdk/wx_pc_redirect.html?appid=wxfa0c35392d06b82f&sServiceType=undefined&originalUrl=https%3A%2F%2Fdf.qq.com%2Fcp%2Frecord202410ver%2F&oriOrigin=https%3A%2F%2Fdf.qq.com",
            "state": 1,
            "login_type": "jssdk",
            "self_redirect": "true",
            "ts": self._get_micro_time(),
            "style": "black",
        }
        headers = {"referer": "https://df.qq.com/"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(WECHAT_QR_URL, params=params, headers=headers) as resp:
                    result = await resp.text()
                    qrcode_match = re.search(r'/connect/qrcode/[^\s<>"]+', result)
                    if not qrcode_match:
                        return {"status": False, "message": "获取二维码失败", "data": {}}
                    qrcode_path = qrcode_match.group(0)
                    uuid = qrcode_path[16:]
                    qrcode_url = f"https://open.weixin.qq.com{qrcode_path}"
                    return {"status": True, "message": "获取成功", "data": {"qrCode": qrcode_url, "uuid": uuid}}
        except Exception as e:
            logger.debug(f"Failed to get wechat login qr: {type(e).__name__}")
            return {"status": False, "message": "获取微信登录二维码失败", "data": {}}

    async def check_wechat_login_status(self, uuid):
        if not uuid:
            return {"status": False, "message": "缺少参数", "code": -1, "data": {}}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(WECHAT_QR_STATUS_URL, params={"uuid": uuid}) as resp:
                    result = await resp.text()
                    errcode_match = re.search(r"wx_errcode=(\d+);", result)
                    code_match = re.search(r"wx_code='([^']*)';", result)
                    if not errcode_match:
                        return {"status": False, "message": "响应格式错误", "code": -4, "data": {}}
                    wx_errcode = int(errcode_match.group(1))
                    wx_code = code_match.group(1) if code_match else ""
                    if wx_errcode == 408:
                        return {"status": True, "message": "等待扫码", "code": 1, "data": {}}
                    if wx_errcode == 404:
                        return {"status": True, "message": "已扫码", "code": 2, "data": {}}
                    if wx_errcode == 405:
                        return {"status": True, "message": "扫码成功", "code": 3, "data": {"wx_code": wx_code}}
                    if wx_errcode == 403:
                        return {"status": False, "message": "扫码被拒绝", "code": -3, "data": {}}
                    return {"status": False, "message": "其他错误代码", "code": -4, "data": {"wx_errcode": wx_errcode, "wx_code": wx_code}}
        except Exception as e:
            logger.debug(f"Failed to check wechat login status: {type(e).__name__}")
            return {"status": False, "message": "获取微信登录状态失败", "code": -4, "data": {}}

    async def get_wechat_access_token(self, code):
        if not code:
            return {"status": False, "message": "缺少参数", "data": {}}
        params = {
            "callback": "",
            "appid": "wxfa0c35392d06b82f",
            "wxcode": code,
            "originalUrl": "https://df.qq.com/cp/record202410ver/",
            "wxcodedomain": "iu.qq.com",
            "acctype": "wx",
            "sServiceType": "undefined",
            "_": self._get_micro_time(),
        }
        headers = {"referer": "https://df.qq.com/"}
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get("https://apps.game.qq.com/ams/ame/codeToOpenId.php", params=params, headers=headers) as resp:
                    result = await resp.text()
                    data = json.loads(result)
                    if data.get("iRet") != 0:
                        return {"status": False, "message": "获取失败", "data": {}}
                    token_data = json.loads(data.get("sMsg", "{}"))
                    return {
                        "status": True,
                        "message": "获取成功",
                        "data": {
                            "access_token": token_data.get("access_token", ""),
                            "expires_in": token_data.get("expires_in", ""),
                            "openid": token_data.get("openid", ""),
                        },
                    }
        except Exception as e:
            logger.debug(f"Failed to get wechat access token: {type(e).__name__}")
            return {"status": False, "message": "获取微信访问令牌失败", "data": {}}

    async def bind_account(self, access_token, openid, platform=None):
        access_type = platform or self.platform
        try:
            if not openid or not access_token:
                return {"status": False, "message": "缺少参数", "data": {}}
            cookies = self._get_cookies(openid, access_token, access_type)
            form_data = {
                "iChartId": 316964,
                "iSubChartId": 316964,
                "sIdeToken": "95ookO",
            }
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=form_data, headers=self._get_headers()) as resp:
                    data = await resp.json(content_type=None)
                if data.get("ret") != 0:
                    return {"status": False, "message": "获取失败,检查鉴权是否过期", "data": {}}
                bindarea = data.get("jData", {}).get("bindarea") or {}
                role_id = str(
                    bindarea.get("role_id")
                    or bindarea.get("roleId")
                    or bindarea.get("sRoleId")
                    or ""
                ).strip()
                role_data = {}
                if not bindarea or not role_id:
                    try:
                        role_data = await self._fetch_role_profile(session, access_token, openid, access_type)
                    except Exception as e:
                        logger.debug(f"Failed to fetch role profile during bind: {type(e).__name__}")
                        role_data = {}
                    role_id = role_id or str(role_data.get("role_id", "")).strip()
                if bindarea:
                    bindarea = dict(bindarea)
                    if role_id:
                        bindarea["role_id"] = role_id
                    return {"status": True, "message": "获取成功", "data": bindarea}

                checkparam = role_data.get("checkparam", "")
                checkparam_parts = checkparam.split("|")
                if len(checkparam_parts) < 3:
                    return {"status": False, "message": "角色信息解析失败", "data": {}}
                role_id = role_id or checkparam_parts[2]
                bind_form = {
                    "iChartId": 316965,
                    "iSubChartId": 316965,
                    "sIdeToken": "sTzZS2",
                    "sArea": 36,
                    "sPlatId": 1,
                    "sPartition": 36,
                    "sCheckparam": checkparam,
                    "sRoleId": role_id,
                    "md5str": role_data.get("md5str", ""),
                }
                async with session.post(BASE_URL, data=bind_form, headers=self._get_headers()) as bind_resp:
                    bind_result = await bind_resp.json(content_type=None)
                if bind_result.get("ret") != 0:
                    return {"status": False, "message": "绑定失败", "data": {}}
                bind_data = bind_result.get("jData", {}).get("bindarea", {}) or {}
                if role_id:
                    bind_data = dict(bind_data)
                    bind_data["role_id"] = role_id
                return {"status": True, "message": "获取成功", "data": bind_data}
        except Exception as e:
            logger.debug(f"Failed to bind account: {type(e).__name__}")
            return {"status": False, "message": "绑定失败", "data": {}}

    async def fetch_records(self, openid, access_token, type_id=4, page=1):
        """
        获取战绩
        type_id: 4 烽火地带, 5 全面战场
        """
        cookies = self._get_cookies(openid, access_token)
        data = {
            "iChartId": "319386",
            "iSubChartId": "319386",
            "sIdeToken": "zMemOt",
            "type": str(type_id),
            "page": str(page)
        }
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        return result.get("jData", {}).get("data", [])
        except Exception as e:
            logger.debug(f"Failed to fetch records (type={type_id}, page={page}): {type(e).__name__}")
        return []

    async def fetch_records_v2(self, openid, access_token, type_id=4, page=1):
        """
        获取新版战绩。
        type_id: 4 烽火地带, 5 全面战场
        """
        cookies = self._get_cookies(openid, access_token)
        data = {
            "iChartId": "450526",
            "iSubChartId": "450526",
            "sIdeToken": "PHq59Y",
            "type": str(type_id),
            "page": str(page)
        }
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        return result.get("jData", {}).get("data", [])
        except Exception as e:
            logger.debug(f"Failed to fetch records_v2 (type={type_id}, page={page}): {type(e).__name__}")
        return []

    async def fetch_room_info(self, openid, access_token, room_id):
        """
        获取烽火地带房间信息。
        """
        cookies = self._get_cookies(openid, access_token)
        data = {
            "iChartId": "450471",
            "iSubChartId": "450471",
            "sIdeToken": "ylP3eG",
            "roomId": str(room_id),
            "type": "2"
        }
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        return result.get("jData", {}).get("data", [])
        except Exception as e:
            logger.debug(f"Failed to fetch room_info (room_id={room_id}): {type(e).__name__}")
        return []

    async def fetch_room_flow(self, openid, access_token, room_id, type_id=1):
        """
        获取战绩流水补充信息。
        type_id=1: 烽火详情补充/昵称
        type_id=3: 烽火收益补充
        """
        cookies = self._get_cookies(openid, access_token)
        data = {
            "iChartId": "450471",
            "iSubChartId": "450471",
            "sIdeToken": "ylP3eG",
            "roomId": str(room_id),
            "typeId": str(type_id)
        }
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        return result.get("jData", {}).get("data")
        except Exception as e:
            logger.debug(f"Failed to fetch room_flow (room_id={room_id}, type_id={type_id}): {type(e).__name__}")
        return None

    async def fetch_item_flow(self, openid, access_token, page=1):
        """
        获取单页道具流水，包含真实物品增减记录。
        type=2 为道具流水。
        """
        cookies = self._get_cookies(openid, access_token)
        data = {
            "iChartId": "319386",
            "iSubChartId": "319386",
            "sIdeToken": "zMemOt",
            "type": "2",
            "page": str(page)
        }
        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        data_obj = result.get("jData", {}).get("data", {})
                        item_arr = data_obj.get("itemArr", []) if isinstance(data_obj, dict) else []
                        normalized = []
                        for item in item_arr:
                            if not isinstance(item, dict):
                                continue
                            reason = unquote(str(item.get("Reason", "")))
                            normalized.append({
                                "dtEventTime": item.get("dtEventTime", ""),
                                "iGoodsId": str(item.get("iGoodsId", "")),
                                "Name": item.get("Name", ""),
                                "AfterCount": item.get("AfterCount", 0),
                                "AddOrReduce": str(item.get("AddOrReduce", "0")),
                                "Reason": reason,
                            })
                        return normalized
        except Exception as e:
            logger.debug(f"Failed to fetch item_flow (page={page}): {type(e).__name__}")
        return []

    async def fetch_all_item_flows(self, openid, access_token, max_pages=10):
        """
        分页获取全量道具流水。
        max_pages：最多拉取页数，防止无限循环。
        """
        all_flows = []
        for page in range(1, max_pages + 1):
            page_flows = await self.fetch_item_flow(openid, access_token, page=page)
            if not page_flows:
                break
            all_flows.extend(page_flows)
        return all_flows

    async def fetch_items_info(self, item_ids):
        """
        获取物品详情，以匹配中文可读名字
        """
        if not isinstance(item_ids, list):
            item_ids = [item_ids]
        data = dict(OBJECT_LIST_PARAMS)
        data["param"] = json.dumps({"objectID": item_ids}, ensure_ascii=False)
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        return result.get("jData", {}).get("data", {}).get("data", {}).get("list", [])
        except Exception as e:
            logger.debug(f"Failed to fetch items_info (count={len(item_ids)}): {type(e).__name__}")
        return []

    async def fetch_item_catalog(self, openid, access_token, force_refresh=False):
        """
        获取并缓存物品列表。
        物品信息相对稳定，默认优先读取本地缓存。
        """
        if not force_refresh:
            cached = self._load_item_catalog_cache()
            if cached:
                return cached.get("items", [])

        cookies = self.create_cookie(openid, access_token)
        data = dict(OBJECT_LIST_PARAMS)
        data["param"] = json.dumps({"primary": "props", "objectID": ""}, ensure_ascii=False)

        try:
            async with aiohttp.ClientSession(cookies=cookies) as session:
                async with session.post(BASE_URL, data=data, headers=self._get_headers()) as resp:
                    result = await resp.json(content_type=None)
                    if result.get("ret") == 0:
                        items = result.get("jData", {}).get("data", {}).get("data", {}).get("list", [])
                        if isinstance(items, list):
                            self._save_item_catalog_cache(items)
                            return items
        except Exception as e:
            logger.debug(f"Failed to fetch item catalog: {type(e).__name__}")

        cached = self._load_item_catalog_cache()
        if cached:
            return cached.get("items", [])
        return []
