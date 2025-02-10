from mutagen.id3 import ID3, APIC, TIT2, TPE1, TALB, TDRC, TCON, TPE2, USLT
from spotipy.cache_handler import CacheHandler
import logging, itertools
import sys, os, traceback
from io import BytesIO
import aiohttp
from dotenv import load_dotenv
import json, time, base64, hashlib
from Crypto.Cipher import AES
from Crypto.Random import get_random_bytes


load_dotenv()
api1_url = os.environ.get("SONG_API1_URL")
api2_url = os.environ.get("SONG_API2_URL")
api2_key = os.environ.get("SONG_API2_KEY")
api2_headers = os.environ.get("SONG_API2_HEADERS")
api3_url = os.environ.get("SONG_API3_URL")
api3_key = os.environ.get("SONG_API3_KEY")
api4_url = os.environ.get("SONG_API4_URL")


logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s', 
    stream=sys.stdout,
    datefmt='%Y-%m-%d %H:%M:%S',
)

class CustomCacheHandler(CacheHandler):
    def __init__(self):
        self.cache_path = None

    def get_cached_token(self):
        cached_token = os.environ.get("MY_API_TOKEN")
        return eval(cached_token) if cached_token else None

    def save_token_to_cache(self, token_info):
        os.environ["MY_API_TOKEN"] = str(token_info)

async def add_mdata(audio_file, metadata):
    try:
        audio_file.seek(0)
        tags = ID3()
        cover_image_data = None
        if metadata["cover_art_url"] and isinstance(metadata["cover_art_url"], str):
            async with aiohttp.ClientSession() as session:
                async with session.get(metadata["cover_art_url"]) as response:
                    if response.status == 200:
                        cover_image_data = BytesIO(await response.read())                    
        tags["TIT2"] = TIT2(encoding=3, text=metadata["track_name"])
        tags["TPE1"] = TPE1(encoding=3, text=metadata["artists"])
        tags["TALB"] = TALB(encoding=3, text=metadata["album_name"])
        tags["TDRC"] = TDRC(encoding=3, text=metadata["release_date"])
        tags["TCON"] = TCON(encoding=3, text=metadata["genres"])
        if "album_artists" in metadata:
            tags["TPE2"] = TPE2(encoding=3, text=metadata["album_artists"])
        if cover_image_data:
            tags["APIC"] = APIC(encoding=0, mime="image/jpeg", type=3, desc="Cover", data=cover_image_data.getvalue())
        tags.save(audio_file)
        audio_file.seek(0)
        return audio_file
    except Exception as e:
        logging.error(traceback.format_exc())
        return None
        
def derive_key_and_iv(password, salt, key_size=32, iv_size=16, iterations=1):
    """Mimics CryptoJS key derivation using MD5."""
    key_iv = b""
    last = b""
    while len(key_iv) < (key_size + iv_size):
        last = hashlib.md5(last + password.encode() + salt).digest()
        key_iv += last
    return key_iv[:key_size], key_iv[key_size:key_size + iv_size]
    
def get_token(e):
    data = json.dumps({
        "token": e,
        "expiresAt": int(time.time() * 1000) + 20000
    })

    salt = get_random_bytes(8)
    key, iv = derive_key_and_iv(api2_key, salt)

    cipher = AES.new(key, AES.MODE_CBC, iv)
    
    pad = lambda s: s + (16 - len(s) % 16) * chr(16 - len(s) % 16)
    encrypted = cipher.encrypt(pad(data).encode())
    
    token = b"Salted__" + salt + encrypted
    return base64.b64encode(token).decode()
    
async def get_track_data(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                data = await response.json()
                return (
                    data["result"].get("gid"),
                    data["result"].get("id"),
                    data["result"].get("name") + ".mp3",
                )
    return None, None, None

async def fetch_alternate_download3(gid, tid):
    track_url = "https://open.spotify.com/track/" + tid
    body = {"url": track_url}

    async with aiohttp.ClientSession() as session:
        async with session.post(api4_url, json=body) as response:
            if response.status == 200:
                try:
                    data = await response.json()
                    return data.get("file_url", None)
                except aiohttp.ContentTypeError:
                    return None
    return None

async def fetch_alternate_download2(gid, tid):
    track_url = "https://open.spotify.com/track/" + tid
    params = {
        "apikey": api3_key,
        "url": track_url
    }
    
    async with aiohttp.ClientSession() as session:
        async with session.get(api3_url, params=params) as response:
            if response.status == 200:
                try:
                    data = await response.json()
                    error = data.get("error", True)
                    if not error:
                        medias = data.get("medias", [])
                        if medias:
                            return medias[0].get("url", None)
                except aiohttp.ContentTypeError:
                    return None
    return None

async def fetch_alternate_download(gid, tid):
    body = {"data": get_token(tid)}
    headers = json.loads(api2_headers)

    async with aiohttp.ClientSession() as session:
        async with session.post(api2_url, headers=headers, json=body) as response:
            if response.status == 200:
                try:
                    data = await response.json()
                    return data.get("link", None)
                except aiohttp.ContentTypeError:
                    return None
    return None

async def get_download_url(gid, tid):
    url = f"{api1_url}/spotify/mp3-convert-task/{gid}/{tid}"

    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                try:
                    data = await response.json()
                    download_url_endpoint = data.get("result", {}).get("download_url", None)
                    if download_url_endpoint:
                        download_url = api1_url + download_url_endpoint
                        return download_url
                except aiohttp.ContentTypeError:
                    return None
    return None
    
api_sources = itertools.cycle([
    get_download_url,  
    fetch_alternate_download,  
    fetch_alternate_download2,  
    fetch_alternate_download3
])

async def fetch_download_rotated(gid, tid):
    for _ in range(4): 
        api_func = next(api_sources)
        download_url = await api_func(gid, tid)
        if download_url:
            return download_url
    return None

async def download_audio(url):
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                return await response.read()
    return None

async def fetch_playlist(playlistid):
    playlist_url = f"https://open.spotify.com/playlist/{playlistid}"
    body = {
        "data": get_token(playlist_url),
        "offset": "",
        "type": "playlist"
    }
    headers = json.loads(api2_headers)
    url = api2_url.replace("download", "data")

    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as response:
            if response.status == 200:
                try:
                    data = await response.json()
                    statusCode = data.get("statusCode", None)
                    if statusCode and statusCode==200:
                        tracks = data["trackList"]
                        neat_tracks = []
                        for track in tracks:
                            track_info = {}
                            track_info['id'] = track['id']
                            track_info['name'] = track['title']
                            track_info['album'] = {}
                            track_info['album']['name'] = track["album"]
                            track_info['album']['release_date'] = track['releaseDate']
                            track_info['artists'] = []
                            track_info['album']['artists'] = []
                            track_artists = track['artists'].split(", ")
                            for artist in track_artists:
                                artist_info = {}
                                artist_info['id'] = ""
                                artist_info['name'] = artist
                                track_info['artists'].append(artist_info)
                                track_info['album']['artists'].append(artist_info)
                            track_info['album']['images'] = [{"url": track["cover"]}]
                            track_dict = { 'track': track_info }
                            neat_tracks.append(track_dict)
                        return neat_tracks
                except aiohttp.ContentTypeError:
                    return None
    return None

async def get_mp3(url):
    try:
        gid, tid, filename = await get_track_data(url)
        if not gid or not tid:
            return None, None
        
        download_url = await fetch_download_rotated(gid, tid)
        if download_url:
            audiobytes = await download_audio(download_url)
            if audiobytes:
                return audiobytes, filename
        
        return None, None
    except Exception:
        logging.error(traceback.format_exc())
        return None, None
