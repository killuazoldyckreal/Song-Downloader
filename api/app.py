from gevent import monkey
monkey.patch_all()

from flask import Flask, request, render_template
import os, traceback, asyncio
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from io import BytesIO
from dotenv import load_dotenv
import logging
import sys
from tenacity import retry, wait_exponential, stop_after_attempt
from flask_socketio import SocketIO, emit
from helper import get_mp3, add_mdata, CustomCacheHandler
from datetime import timedelta

logging.basicConfig(
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s', 
    stream=sys.stdout,
    datefmt='%Y-%m-%d %H:%M:%S',
)

load_dotenv()
api1_url = os.environ.get("SONG_API1_URL")
active_files = {}
app = Flask(__name__)

socketio = SocketIO(app, async_mode='gevent', ping_interval=25, ping_timeout=60, cors_allowed_origins=["https://spotifydownloader-killua.onrender.com"])

limiter = Limiter(app, storage_uri='memory://')
limiter.key_func = get_remote_address

client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def fetch_spotify_track(track_id=None, track_name=None):
    if track_id:
        return sp.track(track_id)
    else:
        return sp.search(q=track_name, type='track', limit=1)['tracks']['items'][0]
        
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(3))
def fetch_spotify_playlist(playlist_id):
    return sp.playlist_tracks(playlist_id)['items']

@socketio.on('request_audio')
def handle_audio_stream(data):
    track_id = data.get('track_id', None)
    if not track_id:
        track_name = data.get('track_name', None)
        if not track_id:
            socketio.emit('error',  {'error': "Please pass either 'track_id' or 'track_name' value"})
            return
    try:
        results = fetch_spotify_track(track_id=track_id) if track_id else fetch_spotify_track(track_name=track_name)
        url = f'{api1_url}/spotify/get?url=https://open.spotify.com/track/{results["id"]}'
        audiobytes, filename = asyncio.run(get_mp3(url))
        filelike = BytesIO(audiobytes)
        
        track_name = results['name']
        album_name = results['album']['name']
        release_date = results['album']['release_date']
        artists = [artist['name'] for artist in results['artists']]
        album_artists = [artist['name'] for artist in results['album']['artists']]
        genres = sp.artist(results['artists'][0]['id'])['genres']
        cover_art_url = results['album']['images'][0]['url']
        mdata = { 
            'track_name': track_name,
            'album_name': album_name,
            'release_date': release_date,
            'artists': artists,
            'album_artists': album_artists,
            'genres': genres,
            'cover_art_url': cover_art_url
        }
        merged_file = asyncio.run(add_mdata(filelike, mdata))
        
        chunk_size = 1024 * 64
        downloaded_size = 0 
        total_size = len(merged_file.getbuffer())
        
        while chunk := merged_file.read(chunk_size):
            downloaded_size += len(chunk)
            progress_percentage = round((downloaded_size / total_size) * 100)
            socketio.emit('audio_chunk', {
                'data': chunk,
                'progress_percentage': progress_percentage
            })
        
        socketio.emit('audio_complete', {"filename": f"{mdata['track_name']}.mp3"})
    except Exception as e:
        logging.error(traceback.format_exc())
        socketio.emit('error', {'error': str(e)})

@socketio.on('request_playlist')
def handle_playlist_stream(data):
    playlist_id = data.get('playlist_id')
    if not playlist_id:
        socketio.emit('error', {'error': "Please provide a valid Spotify playlist ID"})
        return
    
    try:
        tracks = fetch_spotify_playlist(playlist_id)
        
        for track in tracks:
            track_info = track['track']
            track_id = track_info['id']
            
            url = f'{api1_url}/spotify/get?url=https://open.spotify.com/track/{track_id}'
            audiobytes, filename = asyncio.run(get_mp3(url))
            filelike = BytesIO(audiobytes)
            
            track_name = track_info['name']
            album_name = track_info['album']['name']
            release_date = track_info['album']['release_date']
            artists = [artist['name'] for artist in track_info['artists']]
            album_artists = [artist['name'] for artist in track_info['album']['artists']]
            genres = sp.artist(track_info['artists'][0]['id'])['genres']
            cover_art_url = track_info['album']['images'][0]['url']
            
            mdata = { 
                'track_name': track_name,
                'album_name': album_name,
                'release_date': release_date,
                'artists': artists,
                'album_artists': album_artists,
                'genres': genres,
                'cover_art_url': cover_art_url
            }
            merged_file = asyncio.run(add_mdata(filelike, mdata))
            
            chunk_size = 1024 * 64
            downloaded_size = 0 
            total_size = len(merged_file.getbuffer())
            
            while chunk := merged_file.read(chunk_size):
                downloaded_size += len(chunk)
                progress_percentage = round((downloaded_size / total_size) * 100)
                socketio.emit('playlist_audio_chunk', {
                    'data': chunk,
                    'progress_percentage': progress_percentage,
                    'track_name': f"{mdata['track_name']}.mp3"
                })
            
            socketio.emit('playlist_audio_complete', {"filename": f"{mdata['track_name']}.mp3"})
        socketio.emit('playlist_download_complete')
    
    except Exception as e:
        logging.error(traceback.format_exc())
        socketio.emit('error', {'error': str(e)})

@app.route('/')
def home():
    return render_template('home.html')

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
