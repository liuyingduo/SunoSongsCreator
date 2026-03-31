import argparse
import asyncio
import contextlib
import json
import os
import re
import time
import uuid
import random
from http.cookies import SimpleCookie
from typing import Tuple, Union, List, Optional

import httpx
from curl_cffi.requests import AsyncSession, Cookies
from rich import print
from dotenv import load_dotenv, find_dotenv

_ = load_dotenv(find_dotenv())

FIXED_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"

get_session_url = (
    "https://auth.suno.com/v1/client?__clerk_api_version=2025-11-10&_clerk_js_version=5.117.0"
)

base_url = "https://studio-api-prod.suno.com"
browser_version = "edge101"

HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "User-Agent": FIXED_UA,
}

MUSIC_GENRE_LIST = [
    "African", "Asian", "South and southeast Asian", "Avant-garde", "Blues",
    "Caribbean and Caribbean-influenced", "Comedy", "Country", "Easy listening",
    "Electronic", "Folk", "Hip hop", "Jazz", "Latin", "Pop", "R&B and soul", "Rock",
]

class SongsGen:
    def __init__(self, cookie: str) -> None:
        self.cookie = cookie
        self.session: Optional[AsyncSession] = None
        self._auth_token: Optional[str] = None
        self.sid: Optional[str] = None
        self.song_info_dict = {"song_url_list": [], "song_name": "", "o3ic": "", "song_url": ""}
        self.now_data = []

    async def __aenter__(self):
        await self._ensure_session()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def _ensure_session(self):
        if self.session is None:
            self.session = AsyncSession()
            self.session.cookies = self.parse_cookie_string(self.cookie)
            self._auth_token = await self._get_auth_token()
            headers = HEADERS.copy()
            headers["Authorization"] = f"Bearer {self._auth_token}"
            self.session.headers.update(headers)

    @staticmethod
    def parse_cookie_string(cookie_string):
        cookie = SimpleCookie()
        cookie.load(cookie_string)
        cookies_dict = {}
        for key, morsel in cookie.items():
            cookies_dict[key] = morsel.value
        return Cookies(cookies_dict)

    def export_cookie_string(self) -> str:
        if self.session is None:
            return self.cookie
        return "; ".join(f"{key}={value}" for key, value in self.session.cookies.items())

    async def _get_auth_token(self) -> str:
        # 确保 session 已创建（如果是从 _ensure_session 调度的，这里 session 已经存在但还没设置 auth_token）
        # 这里直接用一个临时 session 或者在 _ensure_session 逻辑里闭环处理更好。
        # 这里假设 self.session 已存在。
        resp = await self.session.get(get_session_url, impersonate=browser_version)
        data = resp.json()
        r = data.get("response")
        if not r:
            raise Exception("Failed to get session response")
        
        sessions = r.get("sessions", [])
        if not sessions:
            raise Exception("No active session found")
        
        session = sessions[0]
        self.sid = session.get("id")
        last_active_token = session.get("last_active_token")
        if not last_active_token:
            raise Exception("No auth token found in session")
        
        return last_active_token.get("jwt")

    async def _renew_auth_token(self):
        auth_token = await self._get_auth_token()
        self._auth_token = auth_token
        self.session.headers["Authorization"] = f"Bearer {auth_token}"

    def _get_browser_token(self) -> str:
        timestamp_ms = int(time.time() * 1000)
        return '{"token":"eyJ0aW1lc3RhbXAiOj' + str(timestamp_ms) + 'Z"}'

    def _get_device_id(self) -> str:
        device_id_cookie = self.session.cookies.get("ajs_anonymous_id")
        if device_id_cookie:
            match = re.search(r'"(\w{8}-\w{4}-\w{4}-\w{4}-\w{12})"', device_id_cookie)
            if match:
                return match.group(1)
        return "00000000-0000-0000-0000-000000000000"

    async def get_song_library(self) -> List[dict]:
        await self._ensure_session()
        await self._renew_auth_token()
        result = []
        cursor = None
        limit = 20
        
        while True:
            print("Getting feed data...")
            url = "https://studio-api-prod.suno.com/api/feed/v3"
            payload = {
                "cursor": cursor,
                "limit": limit,
                "filters": {
                    "disliked": "False", "trashed": "False",
                    "fromStudioProject": {"presence": "False"},
                    "stem": {"presence": "False"},
                    "workspace": {"presence": "True", "workspaceId": "default"}
                }
            }
            
            headers = self.session.headers.copy()
            headers["browser-token"] = self._get_browser_token()
            headers["device-id"] = self._get_device_id()
            
            response = await self.session.post(
                url, data=json.dumps(payload), headers=headers, impersonate=browser_version
            )
            data = response.json()
            clips = data.get("clips", [])
            if not clips:
                break
            result.extend(clips)
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")
            await asyncio.sleep(2)
            
        return result

    async def get_limit_left(self) -> dict:
        await self._ensure_session()
        r = await self.session.get(
            "https://studio-api-prod.suno.com/api/billing/info/", impersonate=browser_version
        )
        data = r.json()
        credits = data.get("total_credits_left", 0)
        web_v4 = data.get("free_web_v4_gens_remaining", 0)
        mobile_v4 = data.get("free_mobile_v4_gens_remaining", 0)
        return {
            "total_credits": credits,
            "web_v4_gens": web_v4,
            "mobile_v4_gens": mobile_v4,
            "free_songs": credits // 10,
        }

    def _parse_o3ics(self, data: dict) -> Tuple[str, str]:
        song_name = data.get("title", "")
        mt = data.get("metadata")
        if not mt:
            return song_name, ""
        o3ics = re.sub(r"\[.*?\]", "", mt.get("prompt", ""))
        return song_name, o3ics

    async def get_songs_output(self, ids: List[str]) -> Optional[dict]:
        await self._ensure_session()
        url = "https://studio-api-prod.suno.com/api/feed/v3"
        headers = self.session.headers.copy()
        headers["browser-token"] = self._get_browser_token()
        headers["device-id"] = self._get_device_id()
        payload = {"ids": ids, "limit": len(ids)}
        
        try:
            response = await self.session.post(
                url, data=json.dumps(payload), headers=headers, impersonate=browser_version
            )
            data = response.json()
            clips = data.get("clips", [])
            if not clips or clips == [None]:
                return None
                
            if all(d.get("status") == "complete" for d in clips):
                res = {"song_url_list": []}
                for d in clips:
                    song_name, o3ic = self._parse_o3ics(d)
                    res["song_name"] = song_name
                    res["o3ic"] = o3ic
                    res["song_url_list"].append(d.get("audio_url"))
                    res["song_url"] = d.get("audio_url")
                return res
            return None
        except Exception:
            return None

    async def _fetch_songs_metadata(self, ids: List[str]) -> bool:
        res = await self.get_songs_output(ids)
        if res:
            self.song_info_dict.update(res)
            return True
        return False

    def _get_generation_token(self) -> str:
        timestamp_ms = int(time.time() * 1000)
        return f"P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.haJwZACjZXhwzmnJ8QancGFzc2tlecUFlWDTCuE_JvYKnx5cyfM-5pRZ6gDWz-W2v_y-ivw9zG-U1vjnlNArLlUlr_-PDYig8t3oGEAXExyE0Q0VwHPUkdol6kyemx9jMY7UAJtTJ0EcC9u3FZgY8PiCYygS7dWsglcx-IVKs4qt_ikNNgxW0gI9L9FVRO0DCjq6J9WeowIoQglU9w_EzNgWfW_RqLuRDdFsnrxi-gHN-HeZlItwdiusllebuNCwKApo5B6-WeEwtzTicbKm-Qo356ytFSFX4KkQv2cvwLfR8z1wPae79Tp8X1TdJbEdWqfGMl7E3G3KB3iMJn0QaD5TUxqKl9HZhPKkECieTzft6e14nqolkNI_mD3BiIJImqbrz7Z5c_SQdCasfUXB1HAzDMtCxxte6l1-xMMoTT8So4eyPvLkyYxu0nqbkZDcUPWyRJ4uLfnlTWlmkydhTVjCKSbgDQvGXr40tOpiEnP2OwU5ToX4eIS0_cZnq4lN1Sv1tPdb4B_2RRhfZGKUtwkkb9GNoPHUe54Cz_d6PHrwGyEeoSWt_Wb_QXtKrHRDp3FskIbWxVVKCrTUVJybESKWygts9BNRXaLotF0UIuCbf_VQK1OLaC_TuOyjlGtCm5yFL3z3Y0kOhIs53KcQhB9A-uhJRx2nOfg_G82ZWzc235BpnvARZT_2hfU0oHRORJw9zWUHEHg44Ht4pMVCX5yAC6GgroGssUlHyXG8i05JL8YLU3fsJawuYWl8xEFLt4NeB5BJJkx_x7FTEOK1EAaixpowM6ijyVDBF3ymyBPfCTAdVUcCyncvfOxJup0P4YZIwg12NKHV7JtYQjNyRX4Vk8QeRGw9UulUch1jvRe1BEf_IN98kKRVN5DKfj7pmrgzhXPsnRidQfQ2oIZvUFACDB917u2tNzJ6HiY_Gl-3ZJ5Dx8MKBVccD4EF5sllKxIIP0zLd0mGwrOV6UnsQyQIH37OXA1TvOOOzr3jFQEx_AgO_Njs87L71rq1LQ-02Jp1afsbWcw8p9MisQps6Tsg97Cp2tx_p9iRwuTijGwPzAUTa47qxa9Jp3uVVzE1ZdhxREKBLrKIQczin3UjktEnBOFQNRvYMWlPsiJIDAnHLDJ6keASRObGEIIIGxuVzvJaWeOlhQ2fGr8Qn5vhrrTzRc4cPFthqPU7cf4nLxKbftMZD7x7KvtYSdoqiV-u8fbNHg2grrw-6dqOFBTxSh-odzG5F8jQ8wxm0UDUKH5LYIC-LYBlrAmKjS_cNDuAs-VSbIjST4SaVwpZGRglwdK-aoKLGW3q2HddBh7ezfLyTIT3n1vPQ5JUKMfY60bJeKGRVdxGuK37QndAEUqqQVHKiBnZjRuiq7lE_PEsHXcZhSmKb9B6yk-dRmROMgsWG2xBlPFDK68ekPC2qoNRhr0Dzpz_IBcD1P-Yjrf2hbV4WY8UhI01dQcHugsqa1Ho-Ros7n8uxKD4R_c0oIlrpZRpJsu8Xm3Fda8iRkYUePSmU9R78wMK12DzGy9BKsnjM02tFQ00ERyRWKGlAtCqpR47FgPDVCEyoqA3TMv-bxuQ3Z6e37DrEHLJ5uuhSr7QD0GlYOlLtyHRzWPYIC-_achhxh1CQrDszU1oal0M75F9W-U_F38Ge5ipDCgactV7vT86_KbDRUkNgfx8GvmRXuiohScjMxkxj62gABZYxmRU_fFB0x8PFulVtNQSeKGxqM5ymprcvQtNWOzs1F4CnhPTLGuf4fVPvtHun8jNSsTwh4DQ5YEpWd3yw20gFzGLAlQWZfVElAmLBa_6CEnGxifNcGkkRMUdn8rJc0SZPl6B7i7lJ4PY_-wV8MhzohF9ml0JqtyLgkGCIlFvZwcOe0E63sOarlaCl0qna_at5Z9rV6piKNyLm8QTNNcZcXCbp80OwrTk-Uub7d7uLXCia3KoM2U0MmEzNTeoc2hhcmRfaWTOFZnkVA._m-LpZS7E4KcdYBQwBSNafvEF1cnxQifkCoN_CQc1WE"

    async def create_songs(
        self,
        prompt: str,
        tags: Optional[str] = None,
        title: str = "",
        make_instrumental: bool = False,
        is_custom: bool = False,
        model: str = "chirp-v3.5",
    ) -> List[str]:
        await self._ensure_session()
        url = "https://studio-api-prod.suno.com/api/generate/v2-web/"
        headers = self.session.headers.copy()
        headers["browser-token"] = self._get_browser_token()
        headers["device-id"] = self._get_device_id()
        
        # 映射常用模型名称到 Suno 内部标识符
        model_mappings = {
            # 基础版本
            "v2": "chirp-v2",
            "v3": "chirp-v3-0",
            "v3.5": "chirp-v3-5",
            "v4": "chirp-v4",
            "v4.5": "chirp-auk",
            "v4.5+": "chirp-bluejay",
            "v5": "chirp-crow",
            "v5.5": "chirp-fenix",
            # 特定变体映射
            "chirp-v3.5": "chirp-v3-5",
            "chirp-v3-5-tau": "chirp-v3-5-tau",
            "chirp-v4.5-remaster": "chirp-bass",
            "chirp-v5.0-remaster": "chirp-carp",
        }
        internal_model = model_mappings.get(model, model) # 如果没匹配到，则直接使用原值

        payload = {
            "token": self._get_generation_token(),
            "generation_type": "TEXT",
            "mv": internal_model,
            "prompt": "",
            "gpt_description_prompt": prompt,
            "make_instrumental": make_instrumental,
            "user_uploaded_images_b64": None,
            "metadata": {
                "web_client_pathname": "/create", "is_max_mode": False, "create_mode": "simple",
                "user_tier": "4497580c-f4eb-4f86-9f0e-960eb7c48d7d",
                "create_session_token": str(uuid.uuid4()),
                "disable_volume_normalization": False, "o3ics_model": "default"
            },
            "override_fields": [], "cover_clip_id": None, "cover_start_s": None, "cover_end_s": None,
            "persona_id": None, "artist_clip_id": None, "artist_start_s": None, "artist_end_s": None,
            "continue_clip_id": None, "continued_aligned_prompt": None, "continue_at": None,
            "transaction_uuid": str(uuid.uuid4())
        }
        
        if is_custom:
            payload["prompt"] = prompt
            payload["gpt_description_prompt"] = ""
            payload["title"] = title
            payload["tags"] = tags if tags else random.choice(MUSIC_GENRE_LIST)
            
        response = await self.session.post(
            url, data=json.dumps(payload), headers=headers, impersonate=browser_version,
        )
        if not response.ok:
            raise Exception(f"Error response {response.status_code}")
            
        songs_meta_info = response.json().get("clips", [])
        return [i["id"] for i in songs_meta_info]

    async def get_songs(self, prompt: str, **kwargs) -> dict:
        request_ids = await self.create_songs(prompt, **kwargs)
        start_wait = time.time()
        while True:
            if time.time() - start_wait > 600:
                raise Exception("Request timeout")
            if await self._fetch_songs_metadata(request_ids):
                break
            await asyncio.sleep(5)
        return self.song_info_dict

    async def _download_suno_song(self, link: str, song_id: str, output_dir: str) -> None:
        song_name = self.song_info_dict.get("song_name") or "Untitled"
        o3ic = self.song_info_dict.get("o3ic") or ""
        async with httpx.AsyncClient() as client:
            response = await client.get(link, follow_redirects=True)
            if response.status_code != 200:
                raise Exception("Could not download song")
            
            os.makedirs(output_dir, exist_ok=True)
            with open(os.path.join(output_dir, f"suno_{song_id}.mp3"), "wb") as f:
                f.write(response.content)
            with open(os.path.join(output_dir, f"{song_name.replace(' ', '_')}.lrc"), "w", encoding="utf-8") as f:
                f.write(f"{song_name}\n\n{o3ic}")

    async def save_songs(self, prompt: str, output_dir: str = "./output", **kwargs) -> None:
        await self.get_songs(prompt, **kwargs)
        for link in self.song_info_dict["song_url_list"]:
            mp3_id = link.split("/")[-1].replace(".mp3", "") if ".mp3" in link else link.split("=")[-1]
            await self._download_suno_song(link, mp3_id, output_dir)

async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-U", help="Auth cookie", type=str, default="")
    parser.add_argument("--prompt", help="Prompt", type=str)
    parser.add_argument("--list", dest="list_songs", action="store_true")
    parser.add_argument("--info", dest="show_info", action="store_true")
    parser.add_argument("--output-dir", help="Output directory", type=str, default="./output")
    parser.add_argument("--is_custom", action="store_true")
    parser.add_argument("--title", type=str, default="")
    parser.add_argument("--tags", type=str, default="")

    args = parser.parse_args()
    async with SongsGen(os.environ.get("SUNO_COOKIE") or args.U) as gen:
        if args.list_songs:
            songs = await gen.get_song_library()
            for i, s in enumerate(songs, 1):
                print(f"{i}. [{s.get('status')}] {s.get('title')} ({s.get('id')})")
        elif args.show_info:
            limits = await gen.get_limit_left()
            print(f"Credits: {limits['total_credits']}, Free Songs: {limits['free_songs']}")
        elif args.prompt:
            await gen.save_songs(prompt=args.prompt, output_dir=args.output_dir, title=args.title, tags=args.tags, is_custom=args.is_custom)

if __name__ == "__main__":
    asyncio.run(main())
