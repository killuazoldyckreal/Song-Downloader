import gevent
from gevent import monkey
monkey.patch_all()

from flask import Flask, request, render_template, make_response
import os, traceback, asyncio, uuid
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
from flask_cors import CORS
from helper import get_mp3, add_mdata, CustomCacheHandler, fetch_playlist
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
CORS(app, supports_credentials=True)
socketio = SocketIO(app, async_mode='gevent', ping_interval=25, ping_timeout=60, cors_allowed_origins=["https://spotifydownloader-killua.onrender.com"])

limiter = Limiter(app, storage_uri='memory://')
limiter.key_func = get_remote_address

client_id = os.getenv('CLIENT_ID')
client_secret = os.getenv('CLIENT_SECRET')
sp = spotipy.Spotify(auth_manager=SpotifyClientCredentials(client_id=client_id, client_secret=client_secret))

loop = asyncio.new_event_loop()
asyncio.set_event_loop(loop)

@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(1))
def fetch_spotify_track(track_id=None, track_name=None):
    if track_id:
        return sp.track(track_id)
    else:
        return sp.search(q=track_name, type='track', limit=1)['tracks']['items'][0]
        
@retry(wait=wait_exponential(multiplier=1, min=2, max=10), stop=stop_after_attempt(1))
def fetch_spotify_playlist(playlist_id):
    return sp.playlist_tracks(playlist_id)['items']

client_status = {} 

def cleanup_inactive_clients():
    while True:
        current_time = time.time()
        to_delete = [
            client_id for client_id, data in client_status.items()
            if not data.get("connected", False) and (current_time - data.get("timestamp", current_time - EXPIRY_TIME)) >= EXPIRY_TIME
        ]

        for client_id in to_delete:
            del client_status[client_id]

        gevent.sleep(300)
        
gevent.spawn(cleanup_inactive_clients)

@socketio.on('connect')
def handle_reconnect(data):
    client_id = request.cookies.get('client_id', None)
    if client_id in client_status:
        client_status[client_id]['connected'] = True
        
@socketio.on('disconnect')
def handle_disconnect():
    client_id = request.cookies.get('client_id', None)
    if client_id in client_status:
        client_status[client_id]['connected'] = False

@socketio.on('request_audio')
def handle_audio_stream(data):
    track_id = data.get('track_id', None)
    if not track_id:
        track_name = data.get('track_name', None)
        if not track_id:
            socketio.emit('error',  {'error': "Please pass either 'track_id' or 'track_name' value"}, room=request.sid)
            return
    try:
        results = fetch_spotify_track(track_id=track_id) if track_id else fetch_spotify_track(track_name=track_name)
        url = f'{api1_url}/spotify/get?url=https://open.spotify.com/track/{results["id"]}'
        audiobytes, filename = loop.run_until_complete(get_mp3(url))
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
        merged_file = loop.run_until_complete(add_mdata(filelike, mdata))
        
        chunk_size = 1024 * 64
        downloaded_size = 0 
        total_size = len(merged_file.getbuffer())
        
        while chunk := merged_file.read(chunk_size):
            downloaded_size += len(chunk)
            progress_percentage = round((downloaded_size / total_size) * 100)
            socketio.emit('audio_chunk', {
                'track_id' : track_id,
                'data': chunk,
                'progress_percentage': progress_percentage
            }, room=request.sid)
        
        socketio.emit('audio_complete', {"filename": f"{mdata['track_name']}.mp3"}, room=request.sid)
    except Exception as e:
        logging.error(traceback.format_exc())
        socketio.emit('error', {'error': str(e)}, room=request.sid)

@socketio.on('request_playlist')
def handle_playlist_stream(data):
    client_id = request.cookies.get('client_id')
    playlist_id = data.get('playlist_id')
    if not playlist_id or not client_id:
        socketio.emit('error', {'error': "Invalid request"}, room=request.sid)
        return
    
    if client_status and client_id in client_status and client_status[client_id]['playlist_id'] == playlist_id:
        progress = client_status[client_id]['progress']
        old_tracks = tracks
        
        tracks = [ track for track in old_tracks if progress.get(track['track']['id'], 0) < 100 ]
    else:
        client_status[client_id] = {'connected': True, 'playlist_id': playlist_id, 'progress': {}}
    
    try:
        try:
            tracks = fetch_spotify_playlist(playlist_id)
        except:
            tracks = loop.run_until_complete(fetch_playlist(playlist_id))
        
        for track in tracks:
            track_info = track['track']
            track_id = track_info['id']
            track_name = track_info['name']
            
            client_status[client_id]['progress'][track_name] = 0
            
            url = f'{api1_url}/spotify/get?url=https://open.spotify.com/track/{track_id}'
            audiobytes, filename = loop.run_until_complete(get_mp3(url))
            filelike = BytesIO(audiobytes)
            
            album_name = track_info['album']['name']
            release_date = track_info['album']['release_date']
            artists = [artist['name'] for artist in track_info['artists']]
            album_artists = [artist['name'] for artist in track_info['album']['artists']]
            if track_info['artists'][0]['id']!="":
                genres = sp.artist(track_info['artists'][0]['id'])['genres']
            else:
                genres = ""
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

            socketio.emit('clear_track', {"filename": f"{mdata['track_name']}.mp3"}, room=request.sid)
            try:
                merged_file = loop.run_until_complete(add_mdata(filelike, mdata))
            
                chunk_size = 1024 * 64
                downloaded_size = 0 
                total_size = len(merged_file.getbuffer())
            except:
                continue
            
            while chunk := merged_file.read(chunk_size):
                if not client_status[client_id]['connected']:
                    return
                downloaded_size += len(chunk)
                progress_percentage = round((downloaded_size / total_size) * 100)
                client_status[client_id]['progress'][track_name] = progress_percentage
                socketio.emit('playlist_audio_chunk', {
                    'data': chunk,
                    'progress_percentage': progress_percentage,
                    'track_name': f"{mdata['track_name']}.mp3"
                }, room=request.sid)
            
            socketio.emit('playlist_audio_complete', {"filename": f"{mdata['track_name']}.mp3"}, room=request.sid)
        socketio.emit('playlist_download_complete', room=request.sid)
        client_status.pop(client_id, None)
    
    except Exception as e:
        logging.error(traceback.format_exc())
        socketio.emit('error', {'error': str(e)}, room=request.sid)
    
@app.route('/')
def home():
    client_id = request.cookies.get('client_id', None)
    if not client_id:
        client_id = str(uuid.uuid4())
        response = make_response(render_template('home.html'))
        response.set_cookie('client_id', client_id, httponly=True, samesite='Lax')
        return response
    return render_template('home.html')

if __name__ == "__main__":
    socketio.run(app, host='0.0.0.0', port=5000, debug=False)
