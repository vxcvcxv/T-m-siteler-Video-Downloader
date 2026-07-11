import sys
import os
import re
import json
import sqlite3
import math
import random
import subprocess
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer

from PyQt5.QtWidgets import *
from PyQt5.QtCore import *
from PyQt5.QtGui import *

import yt_dlp
import imageio_ffmpeg

# ── FFmpeg ──────────────────────────────────────────────────
ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()
os.environ["PATH"] += os.pathsep + os.path.dirname(ffmpeg_path)



class UltraDatabase:
    def __init__(self):
        self.db_path = Path("alidwd.db")
        self.conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.create_tables()

    def create_tables(self):
        c = self.conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, title TEXT, format TEXT, quality TEXT,
            file_path TEXT, file_size INTEGER, download_date TEXT,
            duration INTEGER, playlist_name TEXT, status TEXT)''')
        try:
            c.execute("ALTER TABLE downloads ADD COLUMN platform TEXT")
        except:
            pass
        c.execute('''CREATE TABLE IF NOT EXISTS playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, name TEXT, total_videos INTEGER,
            downloaded INTEGER, download_date TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS tiktok_downloads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT, video_id TEXT, username TEXT, title TEXT,
            file_path TEXT, file_size INTEGER, download_date TEXT,
            thumbnail TEXT, status TEXT)''')
        self.conn.commit()

    def add_download(self, data):
        self.conn.execute(
            '''INSERT INTO downloads
            (url,title,format,quality,file_path,file_size,download_date,duration,playlist_name,status)
            VALUES (?,?,?,?,?,?,?,?,?,?)''',
            (data['url'], data['title'], data['format'], data['quality'],
             data['file_path'], data['file_size'], data['download_date'],
             data['duration'], data.get('playlist_name', ''), 'completed'))
        self.conn.commit()

    def add_playlist(self, url, name, total):
        c = self.conn.execute(
            'INSERT INTO playlists (url,name,total_videos,downloaded,download_date) VALUES (?,?,?,0,?)',
            (url, name, total, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()
        return c.lastrowid

    def get_stats(self):
        c = self.conn.cursor()
        total = c.execute('SELECT COUNT(*) FROM downloads').fetchone()[0]
        total_size = c.execute('SELECT SUM(file_size) FROM downloads').fetchone()[0] or 0
        formats = dict(c.execute('SELECT format,COUNT(*) FROM downloads GROUP BY format').fetchall())
        total_pl = c.execute('SELECT COUNT(*) FROM playlists').fetchone()[0]
        return {'total': total, 'total_size': total_size, 'formats': formats, 'playlists': total_pl}

    def get_history(self, limit=200):
        return self.conn.execute(
            'SELECT download_date,title,format,quality,playlist_name FROM downloads ORDER BY download_date DESC LIMIT ?',
            (limit,)).fetchall()

    def get_playlists(self):
        return self.conn.execute(
            'SELECT id,name,total_videos,downloaded,download_date FROM playlists ORDER BY download_date DESC'
        ).fetchall()

    def add_tiktok_download(self, data):
        self.conn.execute(
            '''INSERT INTO tiktok_downloads
            (url, video_id, username, title, file_path, file_size, download_date, thumbnail, status)
            VALUES (?,?,?,?,?,?,?,?,?)''',
            (data['url'], data['video_id'], data['username'], data['title'],
             data['file_path'], data['file_size'], data['download_date'],
             data.get('thumbnail', ''), 'completed'))
        self.conn.commit()

    def get_tiktok_history(self, limit=200):
        return self.conn.execute(
            'SELECT download_date, username, title, video_id, file_size FROM tiktok_downloads ORDER BY download_date DESC LIMIT ?',
            (limit,)).fetchall()

    def get_tiktok_stats(self):
        c = self.conn.cursor()
        total = c.execute('SELECT COUNT(*) FROM tiktok_downloads').fetchone()[0]
        total_size = c.execute('SELECT SUM(file_size) FROM tiktok_downloads').fetchone()[0] or 0
        return {'total': total, 'total_size': total_size}

    def clear_history(self):
        self.conn.execute('DELETE FROM downloads')
        self.conn.execute('DELETE FROM playlists')
        self.conn.execute('DELETE FROM tiktok_downloads')
        self.conn.commit()




class TikTokWorker(QThread):
    settings = {}
    log      = pyqtSignal(str)
    progress = pyqtSignal(int)
    done     = pyqtSignal(bool, str, dict)

    def __init__(self, url, download_path):
        super().__init__()
        self.url           = url.strip()
        self.download_path = download_path

    def _extract_video_id(self, url):
        patterns = [
            r'/video/(\d+)',
            r'/v/(\d+)',
            r'video/(\d+)',
        ]
        for pat in patterns:
            m = re.search(pat, url)
            if m:
                return m.group(1)
        return None

    def _resolve_short_url(self, url):
        try:
            req = urllib.request.Request(url, method='HEAD',
                headers={'User-Agent': 'Mozilla/5.0'})
            req.add_header('User-Agent', 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36')
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.geturl()
        except Exception as e:
            self.log.emit(f"  ⚠ URL çözümleme hatası: {str(e)[:60]}")
            return None

    def _fetch_tiktok_info(self, url):
        api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}"
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Referer': 'https://www.tikwm.com/'
        }
        req = urllib.request.Request(api_url, headers=headers)
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode('utf-8'))

        if data.get('code') != 0 or not data.get('data'):
            raise ValueError(f"API Hatası: {data.get('msg', 'Bilinmeyen hata')}")
        return data['data']

    def _download_file(self, url, filepath):
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': '*/*',
            'Referer': 'https://www.tikwm.com/'
        }
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=60) as resp:
            total_size = int(resp.headers.get('content-length', 0))
            downloaded = 0
            chunk_size = 8192
            with open(filepath, 'wb') as f:
                while True:
                    chunk = resp.read(chunk_size)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if total_size > 0:
                        pct = int(downloaded / total_size * 80) + 20
                        self.progress.emit(min(pct, 95))
        return os.path.getsize(filepath)

    def download_tiktok_profile(self, url, current_path):
        import urllib.request, urllib.parse, json, re, os, time
        try:
            m = re.search(r'tiktok\.com/@([\w.-]+)', url)
            if not m: raise ValueError("TikTok kullanıcı adı bulunamadı.")
            username = m.group(1)
            
            api_url = f"https://www.tikwm.com/api/user/posts?unique_id={username}&count={self.playlist_end}"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            if data.get('code') != 0 or not data.get('data') or not data['data'].get('videos'):
                raise ValueError("Profildeki videolar çekilemedi veya profil gizli.")
                
            videos = data['data']['videos']
            self.total = len(videos)
            self.progress.emit(f"@{username}", 0, f"{len(videos)} video bulundu, indiriliyor...")
            
            for i, vdata in enumerate(videos, 1):
                video_id = vdata.get('video_id', f"vid_{i}")
                title = vdata.get('title', f"TikTok_{i}")
                dl_url = vdata.get('play')
                if not dl_url: continue
                
                safe_title = re.sub(r'[^\w\s-]', '', title)[:30].strip()
                filename = str(current_path / f"[@{username}]_{safe_title}_{video_id}.mp4")
                
                self.progress.emit(f"Video {i}/{len(videos)}", 10, "indiriliyor")
                
                try:
                    vreq = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(vreq, timeout=60) as vresp:
                        total_size = int(vresp.headers.get('content-length', 0))
                        downloaded = 0
                        with open(filename, 'wb') as vf:
                            while True:
                                chunk = vresp.read(8192)
                                if not chunk: break
                                vf.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    pct = int(downloaded / total_size * 100)
                                    if pct % 10 == 0:
                                        self.progress.emit(f"Video {i}/{len(videos)}", pct, "indiriliyor")
                    self.completed += 1
                except Exception as e:
                    self.failed += 1
                
                pct = int((self.completed + self.failed) / self.total * 100)
                self.progress.emit("İlerleme", pct, f"{self.completed} tamam, {self.failed} hata")
                time.sleep(0.5) # rate limit protection
                
            return {'success': True, 'title': f"@{username} Profili", 'file_path': str(current_path), 'url': url}
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'url': url, 'title': 'Profil Hatası'}
            
    def run(self):
        self.log.emit("♪ TikTok analiz ediliyor…")
        self.log.emit(f"  URL: {self.url[:65]}")
        self.progress.emit(5)

        try:
            video_id = self._extract_video_id(self.url)
            if not video_id and ('vm.tiktok.com' in self.url or 'vt.tiktok.com' in self.url):
                self.log.emit("  Kısa link tespit edildi, çözülüyor…")
                resolved = self._resolve_short_url(self.url)
                if resolved:
                    self.url = resolved
                    video_id = self._extract_video_id(self.url)
                    self.log.emit(f"  Çözümlenen: {self.url[:65]}")

            if not video_id:
                self.done.emit(False, "Video ID çıkarılamadı!\nGeçerli bir TikTok linki girin.", {})
                return

            self.log.emit(f"  Video ID: {video_id}")
            self.progress.emit(15)
            self.log.emit("  TikWM API'den bilgi çekiliyor…")
            video_data = self._fetch_tiktok_info(self.url)
            self.progress.emit(25)

            title = video_data.get('title', 'TikTok Video')
            username = video_data.get('author', {}).get('unique_id', 'unknown')
            create_time = video_data.get('create_time', 0)
            thumbnail = video_data.get('cover', '')
            download_url = video_data.get('hdplay') or video_data.get('play', '')

            if not download_url:
                self.done.emit(False, "Watermark'sız video linki bulunamadı!", {})
                return

            self.log.emit(f"  ✓ Video bulundu: {title[:50]}")
            self.log.emit(f"  Kullanıcı: @{username}")
            self.progress.emit(30)

            Path(self.download_path).mkdir(parents=True, exist_ok=True)
            safe_title = re.sub(r'[^\w\s-]', '', title)[:40].strip()
            filename = f"[@{username}]_{safe_title}_{video_id}.mp4"
            filepath = str(Path(self.download_path) / filename)

            self.log.emit(f"  İndiriliyor: {filename[:50]}")
            self.progress.emit(35)
            file_size = self._download_file(download_url, filepath)
            self.progress.emit(100)

            result = {
                'url': self.url,
                'video_id': video_id,
                'username': username,
                'title': title,
                'file_path': filepath,
                'file_size': file_size,
                'thumbnail': thumbnail,
                'create_time': create_time
            }

            mb = file_size / (1024 * 1024)
            msg = f"✓ İndirme tamamlandı!\n\n📹 {title[:50]}\n👤 @{username}\n📦 {mb:.2f} MB\n📁 {filepath}"
            self.done.emit(True, msg, result)

        except Exception as ex:
            self.done.emit(False, f"TikTok indirme hatası:\n{str(ex)[:200]}", {})




class DownloadWorker(QThread):
    settings = {}
    progress        = pyqtSignal(str, int, str)
    single_finished = pyqtSignal(dict)
    all_finished    = pyqtSignal(bool, str)

    def __init__(self, urls, format_type, quality, download_path,
                 is_playlist=False, playlist_name="", noplaylist=True, playlist_end=0):
        super().__init__()
        self.urls          = urls if isinstance(urls, list) else [urls]
        self.format_type   = format_type
        self.quality       = quality
        self.download_path = Path(download_path)
        self.is_playlist   = is_playlist
        self.playlist_name = playlist_name
        self.noplaylist    = noplaylist
        self.playlist_end  = playlist_end
        self.total         = len(self.urls)
        self.completed = self.failed = 0

    def make_hook(self, index):
        def hook(d):
            if d['status'] == 'downloading':
                try:
                    pct = float(d.get('_percent_str', '0%').strip('%'))
                    title = Path(d.get('filename', f'Video {index}')).stem[:50]
                    self.progress.emit(title, int(pct), "indiriliyor")
                except Exception:
                    pass
            elif d['status'] == 'finished':
                self.progress.emit("", 100, "birleştiriliyor…")
        return hook

    def download_single(self, url, index):
        try:
            current_path = self.download_path
            if self.is_playlist and self.playlist_name:
                current_path = self.download_path / self.playlist_name
            current_path.mkdir(parents=True, exist_ok=True)
            
            if "tiktok.com" in url:
                import urllib.request, urllib.parse, json, re, os
                
                if self.playlist_end > 0 and '@' in url and '/video/' not in url:
                    # TikTok Profil Indirme
                    return self.download_tiktok_profile(url, current_path)
                    
                if 'vm.tiktok.com' in url or 'vt.tiktok.com' in url:
                    req = urllib.request.Request(url, method='HEAD', headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        url = resp.geturl()
                        
                m = re.search(r'/(?:video|v)/(\d+)', url)
                if not m: raise ValueError("TikTok Video ID bulunamadı.")
                video_id = m.group(1)
                
                api_url = f"https://www.tikwm.com/api/?url={urllib.parse.quote(url)}"
                req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
                with urllib.request.urlopen(req, timeout=20) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                if data.get('code') != 0 or not data.get('data'):
                    raise ValueError(data.get('msg', 'API Hatası'))
                    
                vdata = data['data']
                title = vdata.get('title', f'TikTok_{index}')
                username = vdata.get('author', {}).get('unique_id', 'unknown')
                dl_url = vdata.get('hdplay') or vdata.get('play')
                if not dl_url: raise ValueError("Video linki bulunamadı.")
                
                safe_title = re.sub(r'[^\w\s-]', '', title)[:40].strip()
                filename = str(current_path / f"[@{username}]_{safe_title}_{video_id}.mp4")
                
                self.progress.emit(title[:50], 10, "indiriliyor")
                req = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=60) as resp:
                    total_size = int(resp.headers.get('content-length', 0))
                    downloaded = 0
                    with open(filename, 'wb') as f:
                        while True:
                            chunk = resp.read(8192)
                            if not chunk: break
                            f.write(chunk)
                            downloaded += len(chunk)
                            if total_size > 0:
                                pct = int(downloaded / total_size * 100)
                                if pct % 5 == 0:  # Update UI less frequently
                                    self.progress.emit(title[:50], pct, "indiriliyor")
                                    
                result = {
                    'title': title, 'duration': 0, 'file_path': filename,
                    'file_size': os.path.getsize(filename), 'url': url, 'success': True, 'has_audio': True
                }
                self.single_finished.emit(result)
                return result

            if self.format_type == "mp3":
                bitrate = self.quality
                ydl_opts = {
                    'format': 'bestaudio[ext=m4a]/bestaudio/best',
                    'outtmpl': str(current_path / '%(title)s.%(ext)s'),
                    'ffmpeg_location': ffmpeg_path,
                    'quiet': True, 'no_warnings': True,
                    'noplaylist': self.noplaylist,
                    'playlistend': self.playlist_end if self.playlist_end > 0 else None,
                    'progress_hooks': [self.make_hook(index)],
                    'postprocessors': [{
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': bitrate,
                    }],
                    'postprocessor_args': {
                        'FFmpegExtractAudio': ['-ar', '44100', '-ac', '2', '-b:a', f'{bitrate}k']
                    }
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    title    = info.get('title', f'video_{index}')
                    duration = info.get('duration', 0)
                    filename = ydl.prepare_filename(info)
                    for old_ext in ('.webm', '.m4a', '.opus', '.ogg', '.mp4'):
                        filename = filename.replace(old_ext, '.mp3')
                    file_size = Path(filename).stat().st_size if Path(filename).exists() else 0
                result = {
                    'title': title, 'duration': duration, 'file_path': filename,
                    'file_size': file_size, 'url': url, 'success': True, 'has_audio': True
                }
                self.single_finished.emit(result)
                return result

            else:  # MP4 (Genel video, Instagram, Twitter vb.)
                with yt_dlp.YoutubeDL({'quiet': True, 'no_warnings': True, 'noplaylist': self.noplaylist,
                    'playlistend': self.playlist_end if self.playlist_end > 0 else None}) as ydl:
                    info     = ydl.extract_info(url, download=False)
                    title    = info.get('title', f'video_{index}')
                    duration = info.get('duration', 0)

                target_h = int(self.quality.replace('p', '').strip())
                # Instagram, Twitter vb. platformlar için karmaşık formatlarda çökmeyi engelleyen, hapsetme.py ile aynı string
                fmt_code = (
                    f"bestvideo[vcodec^=avc][height<={target_h}]+bestaudio[acodec^=mp4a]/"
                    f"bestvideo[vcodec^=avc][height<={target_h}]+bestaudio/"
                    f"best[height<={target_h}][ext=mp4]/best[height<={target_h}]/best"
                )

                self.progress.emit(title, 10, "medya analizi tamamlandı, format ayarlanıyor")

                ydl_opts = {
                    'format': fmt_code,
                    'outtmpl': str(current_path / '%(title)s.%(ext)s'),
                    'merge_output_format': 'mp4',
                    'ffmpeg_location': ffmpeg_path,
                    'quiet': True, 'no_warnings': True,
                    'noplaylist': self.noplaylist,
                    'playlistend': self.playlist_end if self.playlist_end > 0 else None,
                    'progress_hooks': [self.make_hook(index)],
                    'postprocessors': [
                        {'key': 'FFmpegVideoConvertor', 'preferedformat': 'mp4'},
                        {'key': 'FFmpegMetadata', 'add_metadata': True},
                    ],
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    ydl.download([url])
                    filename = ydl.prepare_filename(info)
                    if not filename.endswith('.mp4'):
                        filename = filename.rsplit('.', 1)[0] + '.mp4'
                    if not Path(filename).exists():
                        base = filename.rsplit('.', 1)[0]
                        for ext in ('.mp4', '.mkv', '.webm', '.mov'):
                            if Path(base + ext).exists():
                                filename = base + ext
                                break
                    file_size = Path(filename).stat().st_size if Path(filename).exists() else 0

                result = {
                    'title': title, 'duration': duration, 'file_path': filename,
                    'file_size': file_size, 'url': url, 'success': True,
                    'has_audio': True
                }
                self.single_finished.emit(result)
                return result

        except Exception as e:
            result = {'title': f'Hata_{index}', 'success': False,
                      'error': str(e), 'url': url}
            self.single_finished.emit(result)
            return result

    def download_tiktok_profile(self, url, current_path):
        import urllib.request, urllib.parse, json, re, os, time
        try:
            m = re.search(r'tiktok\.com/@([\w.-]+)', url)
            if not m: raise ValueError("TikTok kullanıcı adı bulunamadı.")
            username = m.group(1)
            
            api_url = f"https://www.tikwm.com/api/user/posts?unique_id={username}&count={self.playlist_end}"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            if data.get('code') != 0 or not data.get('data') or not data['data'].get('videos'):
                raise ValueError("Profildeki videolar çekilemedi veya profil gizli.")
                
            videos = data['data']['videos']
            self.total = len(videos)
            self.progress.emit(f"@{username}", 0, f"{len(videos)} video bulundu, indiriliyor...")
            
            for i, vdata in enumerate(videos, 1):
                video_id = vdata.get('video_id', f"vid_{i}")
                title = vdata.get('title', f"TikTok_{i}")
                dl_url = vdata.get('play')
                if not dl_url: continue
                
                safe_title = re.sub(r'[^\w\s-]', '', title)[:30].strip()
                filename = str(current_path / f"[@{username}]_{safe_title}_{video_id}.mp4")
                
                self.progress.emit(f"Video {i}/{len(videos)}", 10, "indiriliyor")
                
                try:
                    vreq = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(vreq, timeout=60) as vresp:
                        total_size = int(vresp.headers.get('content-length', 0))
                        downloaded = 0
                        with open(filename, 'wb') as vf:
                            while True:
                                chunk = vresp.read(8192)
                                if not chunk: break
                                vf.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    pct = int(downloaded / total_size * 100)
                                    if pct % 10 == 0:
                                        self.progress.emit(f"Video {i}/{len(videos)}", pct, "indiriliyor")
                    self.completed += 1
                except Exception as e:
                    self.failed += 1
                
                pct = int((self.completed + self.failed) / self.total * 100)
                self.progress.emit("İlerleme", pct, f"{self.completed} tamam, {self.failed} hata")
                time.sleep(0.5) # rate limit protection
                
            return {'success': True, 'title': f"@{username} Profili", 'file_path': str(current_path), 'url': url}
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'url': url, 'title': 'Profil Hatası'}
            
    def run(self):
        self.progress.emit("Başlatılıyor", 0, f"Toplam {self.total} video")
        for i, url in enumerate(self.urls, 1):
            self.progress.emit(f"Video {i}/{self.total}", 0, "başlatılıyor")
            result = self.download_single(url, i)
            if result.get('success'):
                self.completed += 1
            else:
                self.failed += 1
            pct = int((self.completed + self.failed) / self.total * 100)
            self.progress.emit("İlerleme", pct, f"{self.completed} tamamlandı, {self.failed} hata")

        summary = f"✓ {self.completed}/{self.total} video başarıyla indirildi!"
        if self.failed:
            summary += f"\n⚠ {self.failed} video indirilemedi!"
        self.all_finished.emit(self.failed == 0, summary)




class ExtensionRequestHandler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200, "ok")
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        if self.path == '/download':
            content_length = int(self.headers['Content-Length'])
            post_data = self.rfile.read(content_length)
            try:
                data = json.loads(post_data.decode('utf-8'))
                url = data.get('url')
                action = data.get('action', 'DOWNLOAD')
                count = int(data.get('count', 0))
                if url or action == "DOWNLOAD_ALL":
                    self.server.worker.download_requested.emit(url or "", action, count)
                    self.send_response(200)
                    self.send_header('Access-Control-Allow-Origin', '*')
                    self.send_header('Content-type', 'application/json')
                    self.end_headers()
                    self.wfile.write(json.dumps({"status": "success", "message": "İşlem başarılı"}).encode('utf-8'))
                    return
            except Exception as e:
                pass
            
            self.send_response(400)
            self.send_header('Access-Control-Allow-Origin', '*')
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": "Geçersiz istek"}).encode('utf-8'))

    def log_message(self, format, *args):
        pass # Konsolu kirletmemesi için

class LocalServerWorker(QThread):
    download_requested = pyqtSignal(str, str, int)

    error_signal = pyqtSignal(str)

    def download_tiktok_profile(self, url, current_path):
        import urllib.request, urllib.parse, json, re, os, time
        try:
            m = re.search(r'tiktok\.com/@([\w.-]+)', url)
            if not m: raise ValueError("TikTok kullanıcı adı bulunamadı.")
            username = m.group(1)
            
            api_url = f"https://www.tikwm.com/api/user/posts?unique_id={username}&count={self.playlist_end}"
            req = urllib.request.Request(api_url, headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/json'})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            
            if data.get('code') != 0 or not data.get('data') or not data['data'].get('videos'):
                raise ValueError("Profildeki videolar çekilemedi veya profil gizli.")
                
            videos = data['data']['videos']
            self.total = len(videos)
            self.progress.emit(f"@{username}", 0, f"{len(videos)} video bulundu, indiriliyor...")
            
            for i, vdata in enumerate(videos, 1):
                video_id = vdata.get('video_id', f"vid_{i}")
                title = vdata.get('title', f"TikTok_{i}")
                dl_url = vdata.get('play')
                if not dl_url: continue
                
                safe_title = re.sub(r'[^\w\s-]', '', title)[:30].strip()
                filename = str(current_path / f"[@{username}]_{safe_title}_{video_id}.mp4")
                
                self.progress.emit(f"Video {i}/{len(videos)}", 10, "indiriliyor")
                
                try:
                    vreq = urllib.request.Request(dl_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(vreq, timeout=60) as vresp:
                        total_size = int(vresp.headers.get('content-length', 0))
                        downloaded = 0
                        with open(filename, 'wb') as vf:
                            while True:
                                chunk = vresp.read(8192)
                                if not chunk: break
                                vf.write(chunk)
                                downloaded += len(chunk)
                                if total_size > 0:
                                    pct = int(downloaded / total_size * 100)
                                    if pct % 10 == 0:
                                        self.progress.emit(f"Video {i}/{len(videos)}", pct, "indiriliyor")
                    self.completed += 1
                except Exception as e:
                    self.failed += 1
                
                pct = int((self.completed + self.failed) / self.total * 100)
                self.progress.emit("İlerleme", pct, f"{self.completed} tamam, {self.failed} hata")
                time.sleep(0.5) # rate limit protection
                
            return {'success': True, 'title': f"@{username} Profili", 'file_path': str(current_path), 'url': url}
            
        except Exception as e:
            return {'success': False, 'error': str(e), 'url': url, 'title': 'Profil Hatası'}
            
    def run(self):
        server_address = ('127.0.0.1', 12090)
        try:
            httpd = HTTPServer(server_address, ExtensionRequestHandler)
            httpd.worker = self
            httpd.serve_forever()
        except Exception as e:
            self.error_signal.emit(f"HATA: Port 12090 kullanılamıyor. Arka planda çalışan başka bir ALİDWD olabilir! Lütfen sağ alt köşeden eski uygulamayı kapatın. ({e})")






# ============================================================
#  ALİDWD - TEMİZ VE SADE ARAYÜZ
# ============================================================

LANGUAGES = {
    "Türkçe": {
        "title": "ALİDWD - Medya İndirici",
        "tab_download": "İndirme",
        "tab_language": "Dil Seçenekleri",
        "grp_links": "Medya Linkleri",
        "placeholder_links": "İndirmek istediğiniz URL'yi buraya yapıştırın (YouTube, Instagram, X, TikTok vb.).\n\nHer satıra bir link yazarak toplu indirme de yapabilirsiniz.",
        "grp_settings": "Ayarlar",
        "lbl_format": "Format:",
        "fmt_mp4": "MP4 (Video + Ses)",
        "fmt_mp3": "MP3 (Sadece Ses)",
        "lbl_quality": "Kalite / Bitrate:",
        "lbl_path": "Kaydetme Yeri:",
        "btn_browse": "Gözat",
        "lbl_ask": "İndirmeden Önce Sor:",
        "chk_ask": "Eklentiden gelince sor",
        "lbl_dark": "Koyu Mod:",
        "chk_dark": "Aktif",
        "btn_download": "▶ İNDİRMEYİ BAŞLAT",
        "log_placeholder": "İşlem geçmişi burada görünecektir...",
        "download_started": "İndirici başlatılıyor...",
        "general_download": "Genel indirici başlatılıyor",
        "err_no_link": "Lütfen en az bir link girin!",
        "err_copy": "Video linki kopyalanamadı! Lütfen manuel kopyalayıp yapıştırın.",
        "downloading": "⏳ İNDİRİLİYOR...",
        "select_folder": "İndirme Klasörü Seç",
        "success": "başarıyla indirildi.",
        "error": "Hata",
        "done": "İşlem Tamam",
        "lang_info": "Uygulama dilini buradan değiştirebilirsiniz:",
        "btn_restart": "Yeniden Başlat"
    },
    "English": {
        "title": "ALİDWD - Media Downloader",
        "tab_download": "Download",
        "tab_language": "Language Options",
        "grp_links": "Media Links",
        "placeholder_links": "Paste the URL you want to download here (YouTube, Instagram, X, TikTok etc.).\n\nYou can also batch download by writing one link per line.",
        "grp_settings": "Settings",
        "lbl_format": "Format:",
        "fmt_mp4": "MP4 (Video + Audio)",
        "fmt_mp3": "MP3 (Audio Only)",
        "lbl_quality": "Quality / Bitrate:",
        "lbl_path": "Save Location:",
        "btn_browse": "Browse",
        "lbl_ask": "Ask Before Download:",
        "chk_ask": "Ask when received from extension",
        "lbl_dark": "Dark Mode:",
        "chk_dark": "Active",
        "btn_download": "▶ START DOWNLOAD",
        "log_placeholder": "Operation history will appear here...",
        "download_started": "Downloader is starting...",
        "general_download": "General downloader is starting",
        "err_no_link": "Please enter at least one link!",
        "err_copy": "Video link could not be copied! Please copy and paste manually.",
        "downloading": "⏳ DOWNLOADING...",
        "select_folder": "Select Download Folder",
        "success": "downloaded successfully.",
        "error": "Error",
        "done": "Process Complete",
        "lang_info": "You can change the application language here:",
        "btn_restart": "Restart"
    },
    "Deutsch": {
        "title": "ALİDWD - Medien-Downloader",
        "tab_download": "Herunterladen",
        "tab_language": "Sprache",
        "grp_links": "Medien-Links",
        "placeholder_links": "Fügen Sie hier die URL ein (YouTube, Instagram, X, TikTok usw.).\n\nEin Link pro Zeile für Batch-Download.",
        "grp_settings": "Einstellungen",
        "lbl_format": "Format:",
        "fmt_mp4": "MP4 (Video + Audio)",
        "fmt_mp3": "MP3 (Nur Audio)",
        "lbl_quality": "Qualität / Bitrate:",
        "lbl_path": "Speicherort:",
        "btn_browse": "Durchsuchen",
        "lbl_ask": "Vor Download fragen:",
        "chk_ask": "Fragen, wenn von Erweiterung gesendet",
        "lbl_dark": "Dunkler Modus:",
        "chk_dark": "Aktiv",
        "btn_download": "▶ DOWNLOAD STARTEN",
        "log_placeholder": "Der Betriebsverlauf wird hier angezeigt...",
        "download_started": "Downloader wird gestartet...",
        "general_download": "Allgemeiner Downloader wird gestartet",
        "err_no_link": "Bitte geben Sie mindestens einen Link ein!",
        "err_copy": "Videolink konnte nicht kopiert werden!",
        "downloading": "⏳ HERUNTERLADEN...",
        "select_folder": "Download-Ordner auswählen",
        "success": "erfolgreich heruntergeladen.",
        "error": "Fehler",
        "done": "Vorgang Abgeschlossen",
        "lang_info": "Hier können Sie die Sprache der Anwendung ändern:",
        "btn_restart": "Neustart"
    },
    "Español": {
        "title": "ALİDWD - Descargador de Medios",
        "tab_download": "Descargar",
        "tab_language": "Idioma",
        "grp_links": "Enlaces de Medios",
        "placeholder_links": "Pegue la URL que desea descargar aquí (YouTube, Instagram, X, TikTok, etc.).\n\nUn enlace por línea para descarga por lotes.",
        "grp_settings": "Ajustes",
        "lbl_format": "Formato:",
        "fmt_mp4": "MP4 (Video + Audio)",
        "fmt_mp3": "MP3 (Solo Audio)",
        "lbl_quality": "Calidad / Tasa de bits:",
        "lbl_path": "Ubicación:",
        "btn_browse": "Navegar",
        "lbl_ask": "Preguntar antes:",
        "chk_ask": "Preguntar al recibir de extensión",
        "lbl_dark": "Modo Oscuro:",
        "chk_dark": "Activo",
        "btn_download": "▶ INICIAR DESCARGA",
        "log_placeholder": "El historial de operaciones aparecerá aquí...",
        "download_started": "Iniciando descargador...",
        "general_download": "Iniciando descargador general",
        "err_no_link": "¡Por favor, introduzca al menos un enlace!",
        "err_copy": "¡No se pudo copiar el enlace del video!",
        "downloading": "⏳ DESCARGANDO...",
        "select_folder": "Seleccione la carpeta de descarga",
        "success": "descargado con éxito.",
        "error": "Error",
        "done": "Proceso Completado",
        "lang_info": "Puede cambiar el idioma de la aplicación aquí:",
        "btn_restart": "Reiniciar"
    },
    "Français": {
        "title": "ALİDWD - Téléchargeur de Médias",
        "tab_download": "Télécharger",
        "tab_language": "Langue",
        "grp_links": "Liens Médias",
        "placeholder_links": "Collez l\'URL ici (YouTube, Instagram, X, TikTok, etc.).\n\nUn lien par ligne pour le téléchargement par lots.",
        "grp_settings": "Paramètres",
        "lbl_format": "Format:",
        "fmt_mp4": "MP4 (Vidéo + Audio)",
        "fmt_mp3": "MP3 (Audio Seulement)",
        "lbl_quality": "Qualité / Débit:",
        "lbl_path": "Emplacement:",
        "btn_browse": "Parcourir",
        "lbl_ask": "Demander avant:",
        "chk_ask": "Demander lors de la réception",
        "lbl_dark": "Mode Sombre:",
        "chk_dark": "Actif",
        "btn_download": "▶ DÉMARRER LE TÉLÉCHARGEMENT",
        "log_placeholder": "L\'historique apparaîtra ici...",
        "download_started": "Démarrage du téléchargeur...",
        "general_download": "Démarrage du téléchargeur général",
        "err_no_link": "Veuillez entrer au moins un lien!",
        "err_copy": "Le lien vidéo n\'a pas pu être copié!",
        "downloading": "⏳ TÉLÉCHARGEMENT...",
        "select_folder": "Sélectionner le dossier",
        "success": "téléchargé avec succès.",
        "error": "Erreur",
        "done": "Processus Terminé",
        "lang_info": "Vous pouvez changer la langue de l\'application ici:"
    },
    "Русский": {
        "title": "ALİDWD - Загрузчик медиа",
        "tab_download": "Скачать",
        "tab_language": "Язык",
        "grp_links": "Медиа ссылки",
        "placeholder_links": "Вставьте URL-адрес здесь (YouTube, Instagram, X, TikTok и т.д.).\n\nОдна ссылка на строку для пакетной загрузки.",
        "grp_settings": "Настройки",
        "lbl_format": "Формат:",
        "fmt_mp4": "MP4 (Видео + Аудио)",
        "fmt_mp3": "MP3 (Только Аудио)",
        "lbl_quality": "Качество / Битрейт:",
        "lbl_path": "Место сохранения:",
        "btn_browse": "Обзор",
        "lbl_ask": "Спрашивать:",
        "chk_ask": "Спрашивать при получении от расширения",
        "lbl_dark": "Темный режим:",
        "chk_dark": "Активен",
        "btn_download": "▶ НАЧАТЬ ЗАГРУЗКУ",
        "log_placeholder": "Здесь появится история операций...",
        "download_started": "Загрузчик запускается...",
        "general_download": "Запуск общего загрузчика",
        "err_no_link": "Пожалуйста, введите хотя бы одну ссылку!",
        "err_copy": "Не удалось скопировать ссылку на видео!",
        "downloading": "⏳ ЗАГРУЗКА...",
        "select_folder": "Выберите папку для загрузки",
        "success": "успешно загружено.",
        "error": "Ошибка",
        "done": "Процесс завершен",
        "lang_info": "Здесь вы можете изменить язык приложения:",
        "btn_restart": "Перезапустить"
    }
}


class DownloadCompleteDialog(QDialog):
    def __init__(self, title, message, file_path=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setMinimumWidth(400)
        self.file_path = file_path
        
        # Apply dark modern theme for this dialog if possible, or inherit
        self.setStyleSheet("""
            QDialog { background-color: #1E1E2E; color: #CDD6F4; font-family: "Segoe UI"; }
            QLabel { color: #CDD6F4; font-size: 14px; }
            QPushButton { background-color: #89B4FA; color: #11111B; font-weight: bold; padding: 8px 16px; border-radius: 6px; }
            QPushButton:hover { background-color: #B4BEFE; }
            QPushButton#folderBtn { background-color: #A6E3A1; color: #11111B; }
            QPushButton#folderBtn:hover { background-color: #94E2D5; }
        """)

        layout = QVBoxLayout(self)
        
        lbl = QLabel(message)
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        
        if self.file_path:
            folder_btn = QPushButton("Klasöre Git")
            folder_btn.setObjectName("folderBtn")
            folder_btn.clicked.connect(self.open_folder)
            btn_layout.addWidget(folder_btn)
            
        ok_btn = QPushButton("Tamam")
        ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(ok_btn)
        
        layout.addLayout(btn_layout)
        
    def open_folder(self):
        import subprocess
        import os
        if self.file_path and os.path.exists(self.file_path):
            try:
                # Select the file in explorer
                subprocess.Popen(r'explorer /select,"{}"'.format(os.path.abspath(self.file_path)))
            except Exception as e:
                print("Klasör açılırken hata:", e)
        self.accept()


class AliDwdApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.db = UltraDatabase()
        self.settings = self._load_settings()
        self.current_worker = None
        
        self._init_ui()
        
        # Yerel Sunucuyu Başlat (Eklenti için)
        self.local_server = LocalServerWorker()
        self.local_server.app_settings = self.settings
        self.local_server.download_requested.connect(self._handle_extension_download)
        self.local_server.error_signal.connect(lambda msg: QMessageBox.critical(self, "Port Hatası", msg) if self.isVisible() else None)
        self.local_server.start()

        # Sistem Tepsisi (System Tray) Ayarları
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(QStyle.SP_ArrowDown))
        
        tray_menu = QMenu()
        show_action = QAction("Göster / Show", self)
        show_action.triggered.connect(self.showNormal)
        quit_action = QAction("Çıkış / Exit", self)
        quit_action.triggered.connect(self._force_quit)
        
        tray_menu.addAction(show_action)
        tray_menu.addAction(quit_action)
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        self.tray_icon.activated.connect(self._tray_activated)

    def _tray_activated(self, reason):
        if reason == QSystemTrayIcon.DoubleClick or reason == QSystemTrayIcon.Trigger:
            self.showNormal()
            self.activateWindow()

    def closeEvent(self, event):
        # Pencereyi kapatınca tepsiye küçült, uygulamayı kapatma
        event.ignore()
        self.hide()
        self.tray_icon.showMessage(
            "ALİDWD",
            "Uygulama arka planda çalışmaya devam ediyor.",
            QSystemTrayIcon.Information,
            2000
        )

    def _force_quit(self):
        # Tamamen çıkış yap
        QApplication.quit()

    def _load_settings(self):
        from pathlib import Path
        import json
        p = Path("alidwd_settings.json")
        if p.exists():
            try:
                return json.loads(p.read_text('utf-8'))
            except:
                pass
        desktop = Path.home() / "Desktop"
        if not desktop.exists():
            desktop = Path.home() / "Masaüstü"
        if not desktop.exists():
            desktop = Path.home()
        return {'download_path': str(desktop / "ALIDWD")}

    def _save_settings(self):
        from pathlib import Path
        import json
        Path("alidwd_settings.json").write_text(json.dumps(self.settings, indent=2), 'utf-8')

    def _handle_extension_download(self, url, action="DOWNLOAD"):
        if action == "DOWNLOAD_ALL":
            self.showNormal()
            self.activateWindow()
            self.raise_()
            self._start_download()
            return

        if url == "USE_CLIPBOARD":
            import time
            time.sleep(0.3)
            clip_text = QApplication.clipboard().text()
            if not clip_text or ("http" not in clip_text and "tiktok" not in clip_text):
                # We should show the window if error happens
                self.showNormal()
                self.activateWindow()
                self.raise_()
                QMessageBox.warning(self, LANGUAGES.get(self.settings.get("language", "Türkçe"))["error"], LANGUAGES.get(self.settings.get("language", "Türkçe"))["err_copy"])
                return
            url = clip_text

        if action == "QUEUE":
            current_text = self.url_input.toPlainText().strip()
            if current_text:
                self.url_input.setText(current_text + "\n" + url)
            else:
                self.url_input.setText(url)
            
            # Count
            lines = [u for u in self.url_input.toPlainText().split('\n') if u.strip()]
            self.tray_icon.showMessage("ALİDWD", f"Sıraya eklendi! (Toplam: {len(lines)} video)", QSystemTrayIcon.Information, 2000)
            return

        self.url_input.setText(url)
        
        if self.settings.get('ask_before_download', False):
            # Only show and focus the window if we are asking before download
            self.showNormal()
            self.setWindowState(self.windowState() & ~Qt.WindowMinimized | Qt.WindowActive)
            self.activateWindow()
            self.raise_()
            
            self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
            self.show()
            self.setWindowFlags(self.windowFlags() & ~Qt.WindowStaysOnTopHint)
            self.show()
            pass
        else:
            # Download silently in background
            self._start_download()


    def _init_ui(self):
        self.setWindowTitle("ALİDWD - Medya İndirici")
        self.setMinimumSize(800, 600)
        
        # Tema Uygula
        self._apply_theme()

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Başlık
        self.title_lbl = QLabel("ALİDWD")
        self.title_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #0056B3; margin-bottom: 10px;")
        self.title_lbl.setAlignment(Qt.AlignCenter)
        main_layout.addWidget(self.title_lbl)

        # Sekmeler
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)
        
        # -- SEKM 1: GENEL İNDİRME --
        download_tab = QWidget()
        dl_lay = QVBoxLayout(download_tab)
        dl_lay.setContentsMargins(15, 15, 15, 15)
        dl_lay.setSpacing(15)
        
        # Link Girişi
        self.url_grp = QGroupBox("Medya Linkleri")
        url_lay = QVBoxLayout(self.url_grp)
        self.url_input = QTextEdit()
        self.url_input.setMaximumHeight(80)
        url_lay.addWidget(self.url_input)
        dl_lay.addWidget(self.url_grp)

        # Ayarlar
        self.cfg_grp = QGroupBox("Ayarlar")
        cfg_lay = QGridLayout(self.cfg_grp)
        cfg_lay.setContentsMargins(15, 20, 15, 15)
        cfg_lay.setVerticalSpacing(15)

        self.lbl_format = QLabel("Format:")
        cfg_lay.addWidget(self.lbl_format, 0, 0)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["MP4", "MP3"])
        self.format_combo.currentIndexChanged.connect(self._on_format_changed)
        cfg_lay.addWidget(self.format_combo, 0, 1)

        self.lbl_quality = QLabel("Kalite / Bitrate:")
        cfg_lay.addWidget(self.lbl_quality, 0, 2)
        self.quality_combo = QComboBox()
        self.quality_combo.addItems(["360p", "480p", "720p", "1080p", "1440p", "2160p (4K)"])
        self.quality_combo.setCurrentText("1080p")
        cfg_lay.addWidget(self.quality_combo, 0, 3)
        
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(["128 kbps", "192 kbps", "320 kbps"])
        self.bitrate_combo.setCurrentIndex(1)
        self.bitrate_combo.setVisible(False)
        cfg_lay.addWidget(self.bitrate_combo, 0, 3)

        self.lbl_path = QLabel("Kaydetme Yeri:")
        cfg_lay.addWidget(self.lbl_path, 1, 0)
        self.path_input = QLineEdit(self.settings.get('download_path', ''))
        cfg_lay.addWidget(self.path_input, 1, 1, 1, 2)
        self.browse_btn = QPushButton("Gözat")
        self.browse_btn.clicked.connect(self._browse_folder)
        cfg_lay.addWidget(self.browse_btn, 1, 3)

        self.lbl_ask = QLabel("İndirmeden Önce Sor:")
        cfg_lay.addWidget(self.lbl_ask, 2, 0)
        self.ask_before_chk = QCheckBox("Eklentiden gelince sor")
        self.ask_before_chk.setChecked(self.settings.get('ask_before_download', False))
        self.ask_before_chk.stateChanged.connect(self._on_ask_before_changed)
        cfg_lay.addWidget(self.ask_before_chk, 2, 1)

        self.lbl_dark = QLabel("Koyu Mod:")
        cfg_lay.addWidget(self.lbl_dark, 2, 2)
        self.dark_mode_chk = QCheckBox("Aktif")
        self.dark_mode_chk.setChecked(self.settings.get('dark_mode', False))
        self.dark_mode_chk.stateChanged.connect(self._on_dark_mode_changed)
        cfg_lay.addWidget(self.dark_mode_chk, 2, 3)

        dl_lay.addWidget(self.cfg_grp)

        # Durum Çubuğu
        self.progress_bar = QProgressBar()
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(20)
        dl_lay.addWidget(self.progress_bar)
        
        self.status_log = QTextEdit()
        self.status_log.setReadOnly(True)
        self.status_log.setStyleSheet("background-color: #F8F9FA; font-family: Consolas, monospace; font-size: 12px;")
        dl_lay.addWidget(self.status_log)

        # İndir Butonu
        self.download_btn = QPushButton("▶ İNDİRMEYİ BAŞLAT")
        self.download_btn.setStyleSheet("font-size: 16px; padding: 15px; background-color: #28A745; border-radius: 8px;")
        self.download_btn.clicked.connect(self._start_download)
        dl_lay.addWidget(self.download_btn)
        
        self.tabs.addTab(download_tab, "İndirme")
        
        # -- SEKM 2: KÜTÜPHANE --
        self.history_tab = QWidget()
        history_lay = QVBoxLayout(self.history_tab)
        
        self.history_table = QTableWidget(0, 5)
        self.history_table.setHorizontalHeaderLabels(["ID", "Platform", "Başlık", "Tarih", "İşlem"])
        self.history_table.horizontalHeader().setStretchLastSection(True)
        self.history_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.history_table.setEditTriggers(QTableWidget.NoEditTriggers)
        history_lay.addWidget(self.history_table)
        
        btn_refresh = QPushButton("Geçmişi Yenile")
        btn_refresh.clicked.connect(self.load_history)
        history_lay.addWidget(btn_refresh)
        
        self.tabs.addTab(self.history_tab, "Kütüphane")
        self.load_history()

        # -- SEKM 3: AYARLAR --
        settings_tab = QWidget()
        set_lay = QVBoxLayout(settings_tab)
        
        group_lang = QGroupBox("Dil ve Sistem")
        g_lay1 = QVBoxLayout(group_lang)
        self.lang_combo = QComboBox()
        self.lang_combo.addItems(list(LANGUAGES.keys()))
        self.lang_combo.setCurrentText(self.settings.get('language', 'Türkçe'))
        self.lang_combo.currentTextChanged.connect(self._on_language_changed)
        g_lay1.addWidget(self.lang_combo)
        self.restart_btn = QPushButton("Uygulamayı Yeniden Başlat")
        self.restart_btn.clicked.connect(self._restart_app)
        g_lay1.addWidget(self.restart_btn)
        
        self.startup_chk = QCheckBox("Bilgisayar açıldığında otomatik başlat")
        self.startup_chk.setChecked(self.settings.get("run_on_startup", False))
        self.startup_chk.stateChanged.connect(self._change_startup)
        g_lay1.addWidget(self.startup_chk)
        
        set_lay.addWidget(group_lang)
        
        group_folder = QGroupBox("Akıllı Klasörleme Sistemi")
        g_lay2 = QVBoxLayout(group_folder)
        self.folder_combo = QComboBox()
        self.folder_combo.addItems(["Yok", "Platforma Göre", "Detaylı (Platform + Kullanıcı)"])
        self.folder_combo.setCurrentText(self.settings.get("folder_mode", "Yok"))
        self.folder_combo.currentTextChanged.connect(self._change_folder_mode)
        g_lay2.addWidget(self.folder_combo)
        set_lay.addWidget(group_folder)
        
        group_shortcut = QGroupBox("Hızlı İndirme Kısayolu (Chrome'da geçerli)")
        g_lay3 = QVBoxLayout(group_shortcut)
        self.shortcut_combo = QComboBox()
        self.shortcut_combo.addItems(["Yok", "d", "s", "a", "x"])
        self.shortcut_combo.setCurrentText(self.settings.get("shortcut", "Yok"))
        self.shortcut_combo.currentTextChanged.connect(self._change_shortcut)
        g_lay3.addWidget(self.shortcut_combo)
        set_lay.addWidget(group_shortcut)
        
        set_lay.addStretch()
        self.tabs.addTab(settings_tab, "Ayarlar")

        # Initial translation
        self._retranslate_ui()

    def _retranslate_ui(self):
        lang = self.settings.get('language', 'Türkçe')
        t = LANGUAGES.get(lang, LANGUAGES['Türkçe'])
        
        self.setWindowTitle(t['title'])
        self.tabs.setTabText(0, t['tab_download'])
        self.tabs.setTabText(1, "Kütüphane")
        self.tabs.setTabText(2, "Ayarlar")
        
        self.url_grp.setTitle(t['grp_links'])
        self.url_input.setPlaceholderText(t['placeholder_links'])
        
        if self.download_btn.isEnabled():
            self.download_btn.setText(t['btn_download'])
        else:
            self.download_btn.setText(t['downloading'])
            
        if hasattr(self, 'lang_info'):
            pass # removed lang_info
        if hasattr(self, 'restart_btn'):
            self.restart_btn.setText(t.get('restart', "Yeniden Başlat"))
            
        self.cfg_grp.setTitle(t['grp_settings'])
        self.lbl_format.setText(t['lbl_format'])
        
        # Update combo items keeping the current index
        idx_format = self.format_combo.currentIndex()
        self.format_combo.blockSignals(True)
        self.format_combo.setItemText(0, t['fmt_mp4'])
        self.format_combo.setItemText(1, t['fmt_mp3'])
        self.format_combo.blockSignals(False)
        
        self.lbl_quality.setText(t['lbl_quality'])
        self.lbl_path.setText(t['lbl_path'])
        self.browse_btn.setText(t['btn_browse'])
        
        self.lbl_ask.setText(t['lbl_ask'])
        self.ask_before_chk.setText(t['chk_ask'])
        
        self.lbl_dark.setText(t['lbl_dark'])
        self.dark_mode_chk.setText(t['chk_dark'])
        
        # Status log and buttons
        self.status_log.setPlaceholderText(t['log_placeholder'])
        if self.download_btn.isEnabled():
            self.download_btn.setText(t['btn_download'])
        else:
            self.download_btn.setText(t['downloading'])
            
        pass # removed lang_info
        if hasattr(self, 'restart_btn'):
            self.restart_btn.setText(t.get('btn_restart', 'Yeniden Başlat'))


    def set_run_on_startup(self, enable):
        import winreg, sys, os
        key = winreg.HKEY_CURRENT_USER
        key_path = r"Software\Microsoft\Windows\CurrentVersion\Run"
        app_name = "ALIDWD_Downloader"
        try:
            registry_key = winreg.OpenKey(key, key_path, 0, winreg.KEY_ALL_ACCESS)
            if enable:
                if getattr(sys, 'frozen', False):
                    exe_path = sys.executable
                else:
                    exe_path = sys.executable + ' "' + os.path.abspath(sys.argv[0]) + '"'
                winreg.SetValueEx(registry_key, app_name, 0, winreg.REG_SZ, f'"{exe_path}"')
            else:
                try:
                    winreg.DeleteValue(registry_key, app_name)
                except FileNotFoundError:
                    pass
            winreg.CloseKey(registry_key)
        except Exception as e:
            print("Startup error:", e)

    def _change_startup(self, state):
        is_enabled = state == Qt.Checked
        self.settings['run_on_startup'] = is_enabled
        self._save_settings()
        self.set_run_on_startup(is_enabled)

    def _change_folder_mode(self, mode):
        self.settings['folder_mode'] = mode
        self._save_settings()

    def _change_shortcut(self, key):
        self.settings['shortcut'] = key
        self._save_settings()
        if hasattr(self, 'local_server'):
            self.local_server.app_settings['shortcut'] = key

    def load_history(self):
        try:
            c = self.db.conn.cursor()
            c.execute("SELECT id, platform, title, download_date, file_path FROM downloads ORDER BY id DESC LIMIT 50")
            rows = c.fetchall()
            self.history_table.setRowCount(0)
            for row in rows:
                r = self.history_table.rowCount()
                self.history_table.insertRow(r)
                self.history_table.setItem(r, 0, QTableWidgetItem(str(row[0])))
                self.history_table.setItem(r, 1, QTableWidgetItem(row[1]))
                self.history_table.setItem(r, 2, QTableWidgetItem(row[2]))
                self.history_table.setItem(r, 3, QTableWidgetItem(row[3]))
                
                btn_open = QPushButton("Klasörü Aç")
                btn_open.clicked.connect(lambda _, p=row[4]: self.open_folder(p))
                self.history_table.setCellWidget(r, 4, btn_open)
        except Exception as e:
            print("History load error:", e)

    def open_folder(self, path):
        import subprocess, os, sys
        if os.path.exists(path):
            if sys.platform == "win32":
                subprocess.Popen(f'explorer /select,"{path}"')

    def save_download_to_db(self, data):
        try:
            import datetime
            date_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            c = self.db.conn.cursor()
            c.execute("INSERT INTO downloads (url, title, platform, file_path, download_date) VALUES (?, ?, ?, ?, ?)",
                      (data.get('url'), data.get('title'), data.get('platform', 'Other'), data.get('file_path'), date_str))
            self.db.conn.commit()
            self.load_history()
        except Exception as e:
            print("DB Save error:", e)

    def _on_language_changed(self, lang):
        self.settings['language'] = lang
        self._save_settings()

    def _apply_theme(self):
        is_dark = self.settings.get('dark_mode', False)
        if is_dark:
            self.setStyleSheet("""
                QMainWindow, QWidget { background-color: #1E1E2E; color: #CDD6F4; font-family: "Segoe UI", Arial, sans-serif; font-size: 13px; }
                QGroupBox { border: 1px solid #45475A; border-radius: 6px; margin-top: 10px; font-weight: bold; background-color: #181825; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; color: #89B4FA; }
                QTextEdit, QLineEdit, QComboBox { border: 1px solid #45475A; border-radius: 4px; padding: 6px; background-color: #313244; color: #CDD6F4; }
                QTextEdit:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #89B4FA; }
                QPushButton { background-color: #89B4FA; color: #11111B; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; }
                QPushButton:hover { background-color: #B4BEFE; }
                QPushButton:disabled { background-color: #45475A; color: #A6ADC8; }
                QProgressBar { border: 1px solid #45475A; border-radius: 4px; text-align: center; background-color: #313244; color: white; font-weight: bold; }
                QProgressBar::chunk { background-color: #A6E3A1; border-radius: 3px; }
                QTabWidget::pane { border: 1px solid #45475A; border-radius: 6px; background: #181825; }
                QTabBar::tab { background: #313244; border: 1px solid #45475A; border-bottom: none; padding: 8px 16px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; color: #CDD6F4;}
                QTabBar::tab:selected { background: #181825; font-weight: bold; border-bottom: 1px solid #181825; color: #89B4FA; }
            """)
            if hasattr(self, 'title_lbl'):
                self.title_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #89B4FA; margin-bottom: 10px;")
            if hasattr(self, 'status_log'):
                self.status_log.setStyleSheet("background-color: #1E1E2E; color: #A6ADC8; font-family: Consolas, monospace; font-size: 12px;")
        else:
            self.setStyleSheet("""
                QMainWindow, QWidget { background-color: #F0F2F5; color: #1C1E21; font-family: "Segoe UI", Arial, sans-serif; font-size: 13px; }
                QGroupBox { border: 1px solid #D0D5DB; border-radius: 6px; margin-top: 10px; font-weight: bold; background-color: #FFFFFF; }
                QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px 0 5px; color: #0056B3; }
                QTextEdit, QLineEdit, QComboBox { border: 1px solid #C0C4CC; border-radius: 4px; padding: 6px; background-color: #FFFFFF; color: #1C1E21; }
                QTextEdit:focus, QLineEdit:focus, QComboBox:focus { border: 1px solid #0056B3; }
                QPushButton { background-color: #0056B3; color: white; border: none; border-radius: 4px; padding: 8px 16px; font-weight: bold; }
                QPushButton:hover { background-color: #004494; }
                QPushButton:disabled { background-color: #A0AAB5; color: white; }
                QProgressBar { border: 1px solid #C0C4CC; border-radius: 4px; text-align: center; background-color: #E9ECEF; color: black; font-weight: bold; }
                QProgressBar::chunk { background-color: #28A745; border-radius: 3px; }
                QTabWidget::pane { border: 1px solid #D0D5DB; border-radius: 6px; background: #FFFFFF; }
                QTabBar::tab { background: #E9ECEF; border: 1px solid #D0D5DB; border-bottom: none; padding: 8px 16px; border-top-left-radius: 4px; border-top-right-radius: 4px; margin-right: 2px; color: #1C1E21; }
                QTabBar::tab:selected { background: #FFFFFF; font-weight: bold; border-bottom: 1px solid #FFFFFF; color: #0056B3; }
            """)
            if hasattr(self, 'title_lbl'):
                self.title_lbl.setStyleSheet("font-size: 24px; font-weight: bold; color: #0056B3; margin-bottom: 10px;")
            if hasattr(self, 'status_log'):
                self.status_log.setStyleSheet("background-color: #F8F9FA; color: #1C1E21; font-family: Consolas, monospace; font-size: 12px;")

    def _on_ask_before_changed(self, state):
        self.settings['ask_before_download'] = (state == Qt.Checked)
        self._save_settings()

    def _on_dark_mode_changed(self, state):
        self.settings['dark_mode'] = (state == Qt.Checked)
        self._save_settings()
        self._apply_theme()

    def _on_format_changed(self, idx):
        is_mp4 = (idx == 0)
        self.quality_combo.setVisible(is_mp4)
        self.bitrate_combo.setVisible(not is_mp4)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, LANGUAGES.get(self.settings.get("language", "Türkçe"))["select_folder"])
        if folder:
            self.path_input.setText(folder)
            self.settings['download_path'] = folder
            self._save_settings()


    def _start_download(self, action='DOWNLOAD', count=0):
        urls_text = self.url_input.toPlainText().strip()
        if not urls_text:
            QMessageBox.warning(self, LANGUAGES.get(self.settings.get("language", "Türkçe"))["error"], LANGUAGES.get(self.settings.get("language", "Türkçe"))["err_no_link"])
            return
            
        urls = [u.strip() for u in urls_text.split('\n') if u.strip()]
        
        format_idx = self.format_combo.currentIndex()
        format_type = "mp4" if format_idx == 0 else "mp3"
        quality = self.quality_combo.currentText().split()[0] if format_idx == 0 else self.bitrate_combo.currentText().split()[0]
        dl_path = self.path_input.text().strip()
        
        from pathlib import Path
        Path(dl_path).mkdir(parents=True, exist_ok=True)
        self.settings['download_path'] = dl_path
        self._save_settings()

        self.download_btn.setEnabled(False)
        self.download_btn.setText(LANGUAGES.get(self.settings.get("language", "Türkçe"))["downloading"])
        self.progress_bar.setValue(0)
        self.status_log.clear()
        
        # TikTok mu yoksa genel mi?
        if action == 'PROFILE_DOWNLOAD':
            self.status_log.append(f"Profil İndiriliyor (Hedef: {count} video)...")
            self.current_worker = DownloadWorker(
                urls, format_type, quality, dl_path,
                is_playlist=True, playlist_name="", noplaylist=False, playlist_end=count
            )
            self.current_worker.settings = self.settings
            self.current_worker.progress.connect(self._update_progress)
            self.current_worker.download_saved.connect(self.save_download_to_db)
            self.current_worker.single_finished.connect(self._on_video_done)
            self.current_worker.all_finished.connect(self._on_all_done)
            self.current_worker.start()
        elif len(urls) == 1 and "tiktok.com" in urls[0]:
            self.status_log.append(LANGUAGES.get(self.settings.get("language", "Türkçe"))["download_started"])
            self.current_worker = TikTokWorker(urls[0], dl_path)
            self.current_worker.settings = self.settings
            self.current_worker.log.connect(lambda m: self.status_log.append(m))
            self.current_worker.progress.connect(self.progress_bar.setValue)
            self.current_worker.download_saved.connect(self.save_download_to_db)
            self.current_worker.done.connect(self._on_tiktok_done)
            self.current_worker.start()
        else:
            lang_val = self.settings.get('language', 'Türkçe')
            gen_txt = LANGUAGES.get(lang_val, LANGUAGES['Türkçe'])['general_download']
            self.status_log.append(f"{gen_txt} ({len(urls)} video)...")
            self.current_worker = DownloadWorker(
                urls, format_type, quality, dl_path,
                is_playlist=False, playlist_name="", noplaylist=True
            )
            self.current_worker.settings = self.settings
            self.current_worker.progress.connect(self._update_progress)
            self.current_worker.download_saved.connect(self.save_download_to_db)
            self.current_worker.single_finished.connect(self._on_video_done)
            self.current_worker.all_finished.connect(self._on_all_done)
            self.current_worker.start()

    def _update_progress(self, title, percent, status):
        self.progress_bar.setValue(percent)
        if title:
            # Durum çubuğunda sürekli log birikmemesi için sadece yüzdeyi güncelleyebiliriz
            # Ama log'da göstermek istersek çok kalabalık olur. O yüzden pass
            pass

    def _on_video_done(self, result):
        if result.get('success'):
            mb = result.get('file_size', 0) / (1024 * 1024)
            self.status_log.append(f"✓ {result['title']} [{mb:.1f} MB] başarıyla indirildi.")
        else:
            self.status_log.append(f"✗ Hata: {result.get('error', 'Bilinmeyen Hata')} ({result.get('url')})")

    def _on_all_done(self, success, message):
        self.download_btn.setEnabled(True)
        self.download_btn.setText(LANGUAGES.get(self.settings.get("language", "Türkçe"))["btn_download"])
        self.progress_bar.setValue(100)
        self.status_log.append("\n" + "="*40 + "\n" + message)
        
        dl_path = self.settings.get('download_path', '')
        dlg = DownloadCompleteDialog(LANGUAGES.get(self.settings.get("language", "Türkçe"))["done"], message, file_path=dl_path, parent=self)
        dlg.exec_()

    def _on_tiktok_done(self, success, message, result):
        self.download_btn.setEnabled(True)
        self.download_btn.setText(LANGUAGES.get(self.settings.get("language", "Türkçe"))["btn_download"])
        self.progress_bar.setValue(100 if success else 0)
        self.status_log.append("\n" + "="*40 + "\n" + message)
        
        file_path = result.get('file_path') if result else None
        title = LANGUAGES.get(self.settings.get("language", "Türkçe"))["done"] if success else LANGUAGES.get(self.settings.get("language", "Türkçe"))["error"]
        
        dlg = DownloadCompleteDialog(title, message, file_path=file_path, parent=self)
        dlg.exec_()

    def _restart_app(self):
        import sys
        import os
        from PyQt5.QtWidgets import QApplication
        QApplication.quit()
        os.execl(sys.executable, sys.executable, *sys.argv)


def main():
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    window = AliDwdApp()
    window.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
