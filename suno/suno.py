import argparse
import contextlib
import json
import os
import re
import time
import uuid
from http.cookies import SimpleCookie
from typing import Tuple
import random

from curl_cffi import requests
from curl_cffi.requests import Cookies
import httpx
from rich import print
from typing import Union

from dotenv import load_dotenv, find_dotenv

_ = load_dotenv(find_dotenv())

ua = None  # Using fixed browser-version for impersonation
FIXED_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0"

get_session_url = (
    "https://auth.suno.com/v1/client?__clerk_api_version=2025-11-10&_clerk_js_version=5.117.0"
)

base_url = "https://studio-api-prod.suno.com"
browser_version = "edge101"

HEADERS = {
    "Accept-Encoding": "gzip, deflate, br",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) \
        Gecko/20100101 Firefox/117.0",
}

MUSIC_GENRE_LIST = [
    "African",
    "Asian",
    "South and southeast Asian",
    "Avant-garde",
    "Blues",
    "Caribbean and Caribbean-influenced",
    "Comedy",
    "Country",
    "Easy listening",
    "Electronic",
    "Folk",
    "Hip hop",
    "Jazz",
    "Latin",
    "Pop",
    "R&B and soul",
    "Rock",
]


class SongsGen:
    def __init__(self, cookie: str) -> None:
        self.session: requests.Session = requests.Session()
        HEADERS["user-agent"] = FIXED_UA
        self.cookie = cookie
        self.session.cookies = self.parse_cookie_string(self.cookie)
        auth_token = self._get_auth_token()
        HEADERS["Authorization"] = f"Bearer {auth_token}"
        self.session.headers = HEADERS
        self.sid = None
        self.retry_time = 0
        self.song_info_dict = {}
        self.song_info_dict["song_url_list"] = []
        self.now_data = {}
        self._auth_token = auth_token

    def _get_auth_token(self):
        response = self.session.get(get_session_url, impersonate=browser_version)
        data = response.json()
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

    def _renew_auth_token(self):
        auth_token = self._get_auth_token()
        self._auth_token = auth_token
        HEADERS["Authorization"] = f"Bearer {auth_token}"
        self.session.headers = HEADERS

    @staticmethod
    def parse_cookie_string(cookie_string):
        cookie = SimpleCookie()
        cookie.load(cookie_string)
        cookies_dict = {}
        for key, morsel in cookie.items():
            cookies_dict[key] = morsel.value
        return Cookies(cookies_dict)

    def _get_browser_token(self) -> str:
        """Generate browser token for API requests"""
        timestamp_ms = int(time.time() * 1000)
        return '{"token":"eyJ0aW1lc3RhbXAiOj' + str(timestamp_ms) + 'Z"}'

    def _get_device_id(self) -> str:
        """Extract device-id from cookies or generate a default one"""
        device_id_cookie = self.session.cookies.get("ajs_anonymous_id")
        if device_id_cookie:
            match = re.search(r'"(\w{8}-\w{4}-\w{4}-\w{4}-\w{12})"', device_id_cookie)
            if match:
                return match.group(1)
        return "00000000-0000-0000-0000-000000000000"

    def get_song_library(self):
        self._renew_auth_token()
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
                    "disliked": "False",
                    "trashed": "False",
                    "fromStudioProject": {"presence": "False"},
                    "stem": {"presence": "False"},
                    "workspace": {"presence": "True", "workspaceId": "default"}
                }
            }
            
            headers = self.session.headers.copy()
            headers["browser-token"] = self._get_browser_token()
            headers["device-id"] = self._get_device_id()
            
            response = self.session.post(
                url, 
                data=json.dumps(payload),
                headers=headers,
                impersonate=browser_version
            )
            data = response.json()
            
            clips = data.get("clips", [])
            if not clips:
                break
                
            result.extend(clips)
            
            if not data.get("has_more"):
                break
                
            cursor = data.get("next_cursor")
            time.sleep(2)
            
        return result

    def get_limit_left(self) -> dict:
        self.session.headers["user-agent"] = FIXED_UA
        r = self.session.get(
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
            return "", ""
        o3ics = re.sub(r"\[.*?\]", "", mt.get("prompt"))
        return song_name, o3ics

    def _fetch_songs_metadata(self, ids):
        id1, id2 = ids[:2] if len(ids) >= 2 else (ids[0], ids[0])
        url = "https://studio-api-prod.suno.com/api/feed/v3"
        
        headers = self.session.headers.copy()
        headers["browser-token"] = self._get_browser_token()
        headers["device-id"] = self._get_device_id()
        
        payload = {
            "ids": ids,
            "limit": len(ids)
        }
        
        response = self.session.post(
            url,
            data=json.dumps(payload),
            headers=headers,
            impersonate=browser_version
        )
        data = response.json()
        clips = data.get("clips", [])
        
        if not clips or clips == [None]:
            if self.now_data and len(self.now_data) > 0:
                song_name, o3ic = self._parse_o3ics(self.now_data[0])
                self.song_info_dict["song_name"] = song_name
                self.song_info_dict["o3ic"] = o3ic
                self.song_info_dict["song_url"] = (
                    f"https://audiopipe.suno.ai/?item_id={id1}"
                )
                print("Token expired, will sleep 30 seconds and try to download")
                time.sleep(30)
                return True
            return False
            
        self.now_data = clips
        try:
            if all(d.get("audio_url") for d in clips):
                for d in clips:
                    song_name, o3ic = self._parse_o3ics(d)
                    self.song_info_dict["song_name"] = song_name
                    self.song_info_dict["o3ic"] = o3ic
                    self.song_info_dict["song_url_list"].append(d.get("audio_url"))
                    self.song_info_dict["song_url"] = d.get("audio_url")
                return True
            return False
        except Exception as e:
            print(e)
            print("Will sleep 30s and get the music url")
            time.sleep(30)
            if self.now_data and len(self.now_data) > 0:
                song_name, o3ic = self._parse_o3ics(self.now_data[0])
                self.song_info_dict["song_name"] = song_name
                self.song_info_dict["o3ic"] = o3ic
                self.song_info_dict["song_url_list"] = [
                    f"https://audiopipe.suno.ai/?item_id={id1}",
                    f"https://audiopipe.suno.ai/?item_id={id2}",
                ]
                self.song_info_dict["song_url"] = (
                    f"https://audiopipe.suno.ai/?item_id={id1}"
                )
            return True

    def _get_generation_token(self) -> str:
        """Generate token for song generation"""
        timestamp_ms = int(time.time() * 1000)
        token_part = f"eyJ0aW1lc3RhbXAiOj{timestamp_ms}Z"
        return f"P1_eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.haJwZACjZXhwzmnJ8QancGFzc2tlecUFlWDTCuE_JvYKnx5cyfM-5pRZ6gDWz-W2v_y-ivw9zG-U1vjnlNArLlUlr_-PDYig8t3oGEAXExyE0Q0VwHPUkdol6kyemx9jMY7UAJtTJ0EcC9u3FZgY8PiCYygS7dWsglcx-IVKs4qt_ikNNgxW0gI9L9FVRO0DCjq6J9WeowIoQglU9w_EzNgWfW_RqLuRDdFsnrxi-gHN-HeZlItwdiusllebuNCwKApo5B6-WeEwtzTicbKm-Qo356ytFSFX4KkQv2cvwLfR8z1wPae79Tp8X1TdJbEdWqfGMl7E3G3KB3iMJn0QaD5TUxqKl9HZhPKkECieTzft6e14nqolkNI_mD3BiIJImqbrz7Z5c_SQdCasfUXB1HAzDMtCxxte6l1-xMMoTT8So4eyPvLkyYxu0nqbkZDcUPWyRJ4uLfnlTWlmkydhTVjCKSbgDQvGXr40tOpiEnP2OwU5ToX4eIS0_cZnq4lN1Sv1tPdb4B_2RRhfZGKUtwkkb9GNoPHUe54Cz_d6PHrwGyEeoSWt_Wb_QXtKrHRDp3FskIbWxVVKCrTUVJybESKWygts9BNRXaLotF0UIuCbf_VQK1OLaC_TuOyjlGtCm5yFL3z3Y0kOhIs53KcQhB9A-uhJRx2nOfg_G82ZWzc235BpnvARZT_2hfU0oHRORJw9zWUHEHg44Ht4pMVCX5yAC6GgroGssUlHyXG8i05JL8YLU3fsJawuYWl8xEFLt4NeB5BJJkx_x7FTEOK1EAaixpowM6ijyVDBF3ymyBPfCTAdVUcCyncvfOxJup0P4YZIwg12NKHV7JtYQjNyRX4Vk8QeRGw9UulUch1jvRe1BEf_IN98kKRVN5DKfj7pmrgzhXPsnRidQfQ2oIZvUFACDB917u2tNzJ6HiY_Gl-3ZJ5Dx8MKBVccD4EF5sllKxIIP0zLd0mGwrOV6UnsQyQIH37OXA1TvOOOzr3jFQEx_AgO_Njs87L71rq1LQ-02Jp1afsbWcw8p9MisQps6Tsg97Cp2tx_p9iRwuTijGwPzAUTa47qxa9Jp3uVVzE1ZdhxREKBLrKIQczin3UjktEnBOFQNRvYMWlPsiJIDAnHLDJ6keASRObGEIIIGxuVzvJaWeOlhQ2fGr8Qn5vhrrTzRc4cPFthqPU7cf4nLxKbftMZD7x7KvtYSdoqiV-u8fbNHg2grrw-6dqOFBTxSh-odzG5F8jQ8wxm0UDUKH5LYIC-LYBlrAmKjS_cNDuAs-VSbIjST4SaVwpZGRglwdK-aoKLGW3q2HddBh7ezfLyTIT3n1vPQ5JUKMfY60bJeKGRVdxGuK37QndAEUqqQVHKiBnZjRuiq7lE_PEsHXcZhSmKb9B6yk-dRmROMgsWG2xBlPFDK68ekPC2qoNRhr0Dzpz_IBcD1P-Yjrf2hbV4WY8UhI01dQcHugsqa1Ho-Ros7n8uxKD4R_c0oIlrpZRpJsu8Xm3Fda8iRkYUePSmU9R78wMK12DzGy9BKsnjM02tFQ00ERyRWKGlAtCqpR47FgPDVCEyoqA3TMv-bxuQ3Z6e37DrEHLJ5uuhSr7QD0GlYOlLtyHRzWPYIC-_achhxh1CQrDszU1oal0M75F9W-U_F38Ge5ipDCgactV7vT86_KbDRUkNgfx8GvmRXuiohScjMxkxj62gABZYxmRU_fFB0x8PFulVtNQSeKGxqM5ymprcvQtNWOzs1F4CnhPTLGuf4fVPvtHun8jNSsTwh4DQ5YEpWd3yw20gFzGLAlQWZfVElAmLBa_6CEnGxifNcGkkRMUdn8rJc0SZPl6B7i7lJ4PY_-wV8MhzohF9ml0JqtyLgkGCIlFvZwcOe0E63sOarlaCl0qna_at5Z9rV6piKNyLm8QTNNcZcXCbp80OwrTk-Uub7d7uLXCia3KoM2U0MmEzNTeoc2hhcmRfaWTOFZnkVA._m-LpZS7E4KcdYBQwBSNafvEF1cnxQifkCoN_CQc1WE"

    def get_songs(
        self,
        prompt: str,
        tags: Union[str, None] = None,
        title: str = "",
        make_instrumental: bool = False,
        is_custom: bool = False,
    ) -> dict:
        url = "https://studio-api-prod.suno.com/api/generate/v2-web/"
        
        headers = self.session.headers.copy()
        headers["browser-token"] = self._get_browser_token()
        headers["device-id"] = self._get_device_id()
        headers["user-agent"] = FIXED_UA
        
        payload = {
            "token": self._get_generation_token(),
            "generation_type": "TEXT",
            "mv": "chirp-auk-turbo",
            "prompt": "",
            "gpt_description_prompt": prompt,
            "make_instrumental": make_instrumental,
            "user_uploaded_images_b64": None,
            "metadata": {
                "web_client_pathname": "/create",
                "is_max_mode": False,
                "create_mode": "simple",
                "user_tier": "4497580c-f4eb-4f86-9f0e-960eb7c48d7d",
                "create_session_token": str(uuid.uuid4()),
                "disable_volume_normalization": False,
                "o3ics_model": "default"
            },
            "override_fields": [],
            "cover_clip_id": None,
            "cover_start_s": None,
            "cover_end_s": None,
            "persona_id": None,
            "artist_clip_id": None,
            "artist_start_s": None,
            "artist_end_s": None,
            "continue_clip_id": None,
            "continued_aligned_prompt": None,
            "continue_at": None,
            "transaction_uuid": str(uuid.uuid4())
        }
        
        if is_custom:
            payload["prompt"] = prompt
            payload["gpt_description_prompt"] = ""
            payload["title"] = title
            if not tags:
                payload["tags"] = random.choice(MUSIC_GENRE_LIST)
            else:
                payload["tags"] = tags
            print(payload)
            
        response = self.session.post(
            url,
            data=json.dumps(payload),
            headers=headers,
            impersonate=browser_version,
        )
        if not response.ok:
            print(response.text)
            raise Exception(f"Error response {str(response)}")
        response_body = response.json()
        songs_meta_info = response_body["clips"]
        request_ids = [i["id"] for i in songs_meta_info]
        start_wait = time.time()
        print("Waiting for results...")
        print(".", end="", flush=True)
        sleep_time = 10
        while True:
            if int(time.time() - start_wait) > 600:
                raise Exception("Request timeout")
            song_info = self._fetch_songs_metadata(request_ids)
            if sleep_time > 2:
                time.sleep(sleep_time)
                sleep_time -= 1
            else:
                time.sleep(2)

            if not song_info:
                print(".", end="", flush=True)
            else:
                break
        return self.song_info_dict

    def _download_suno_song(self, link: str, song_id: str, output_dir: str) -> None:
        song_name = self.song_info_dict["song_name"]
        o3ic = self.song_info_dict["o3ic"]
        response = httpx.get(link, follow_redirects=False, stream=True)
        if response.status_code != 200:
            raise Exception("Could not download song")
        print(f"Downloading song... {song_id}")
        with open(os.path.join(output_dir, f"suno_{song_id}.mp3"), "wb") as output_file:
            for chunk in response.iter_content(chunk_size=1024):
                if chunk:
                    output_file.write(chunk)
        if not song_name:
            song_name = "Untitled"
        with open(
            os.path.join(output_dir, f"{song_name.replace(' ', '_')}.lrc"),
            "w",
            encoding="utf-8",
        ) as o3ic_file:
            o3ic_file.write(f"{song_name}\n\n{o3ic}")

    def save_songs(
        self,
        prompt: str,
        output_dir: str = "./output",
        tags: Union[str, None] = None,
        title: Union[str, None] = None,
        make_instrumental: bool = False,
        is_custom: bool = False,
    ) -> None:
        try:
            self.get_songs(
                prompt,
                tags=tags,
                title=title,
                is_custom=is_custom,
                make_instrumental=make_instrumental,
            )
            link_list = self.song_info_dict["song_url_list"]
        except Exception as e:
            print(e)
            raise
        with contextlib.suppress(FileExistsError):
            os.mkdir(output_dir)
        print()
        print(link_list)
        for link in link_list:
            if link.endswith(".mp3"):
                mp3_id = link.split("/")[-1][:-4]
            else:
                mp3_id = link.split("=")[-1]
            self._download_suno_song(link, mp3_id, output_dir)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-U", help="Auth cookie from browser", type=str, default="")
    parser.add_argument(
        "--prompt",
        help="Prompt to generate songs for",
        type=str,
    )
    parser.add_argument(
        "--list",
        dest="list_songs",
        action="store_true",
        help="List all songs in library",
    )
    parser.add_argument(
        "--info",
        dest="show_info",
        action="store_true",
        help="Show account info and credits",
    )
    parser.add_argument(
        "--output-dir",
        help="Output directory",
        type=str,
        default="./output",
    )
    parser.add_argument(
        "--is_custom",
        dest="is_custom",
        action="store_true",
        help="use custom mode, need to provide title and tags",
    )
    parser.add_argument(
        "--title",
        help="Title of the song",
        type=str,
        default="",
    )
    parser.add_argument(
        "--tags",
        help="Tags of the song",
        type=str,
        default="",
    )

    args = parser.parse_args()

    song_generator = SongsGen(
        os.environ.get("SUNO_COOKIE") or args.U,
    )

    if args.list_songs:
        songs = song_generator.get_song_library()
        print(f"\nFound {len(songs)} songs:")
        for i, song in enumerate(songs, 1):
            title = song.get("title", "Untitled")
            clip_id = song.get("id", "N/A")
            status = song.get("status", "N/A")
            print(f"{i}. [{status}] {title} (ID: {clip_id})")
        return

    if args.show_info:
        limits = song_generator.get_limit_left()
        print(f"\n=== Account Info ===")
        print(f"Total Credits: {limits['total_credits']}")
        print(f"Free Songs: {limits['free_songs']}")
        print(f"Web v4 Gems: {limits['web_v4_gens']}")
        print(f"Mobile v4 Gems: {limits['mobile_v4_gens']}")
        return

    if not args.prompt:
        parser.error("--prompt is required unless using --list")
    
    limits = song_generator.get_limit_left()
    print(f"Credits: {limits['total_credits']} ({limits['free_songs']} free songs left)")
    print(f"  Web v4: {limits['web_v4_gens']}, Mobile v4: {limits['mobile_v4_gens']}")
    song_generator.save_songs(
        prompt=args.prompt,
        output_dir=args.output_dir,
        title=args.title,
        tags=args.tags,
        make_instrumental=False,
        is_custom=args.is_custom,
    )


if __name__ == "__main__":
    main()
