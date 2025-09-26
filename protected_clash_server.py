#!/usr/bin/env python3

import http.server
import socketserver
import urllib.request
import urllib.parse
import json
import os
import socket
from datetime import datetime, timezone, timedelta
import threading
import time
import hashlib

# Configuración del puerto
PORT = int(os.environ.get('PORT', 8000))

# Configuración API Clash of Clans - ACTUALIZADA
API_KEY = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzUxMiIsImtpZCI6IjI4YTMxOGY3LTAwMDAtYTFlYi03ZmExLTJjNzQzM2M2Y2NhNSJ9.eyJpc3MiOiJzdXBlcmNlbGwiLCJhdWQiOiJzdXBlcmNlbGw6Z2FtZWFwaSIsImp0aSI6IjUyMWI5YWRmLWYwNTItNDY3YS1iYTM1LWZjNmU3YmIxNTE1MCIsImlhdCI6MTc1ODg0MzQ1NCwic3ViIjoiZGV2ZWxvcGVyL2ZjNTE2YWY0LTA4YzUtYTUwYS1iNjA1LTA0NWJiN2Y2MWYxNyIsInNjb3BlcyI6WyJjbGFzaCJdLCJsaW1pdHMiOlt7InRpZXIiOiJkZXZlbG9wZXIvc2lsdmVyIiwidHlwZSI6InRocm90dGxpbmcifSx7ImNpZHJzIjpbIjIwMS4xNzguMjQxLjUiXSwidHlwZSI6ImNsaWVudCJ9XX0.glqyBEIJ5Z-6_n6q9YwuEt4VSjUJdAq0xY09UP2D-bHOAFbL6lG2xyfDdyiwcqMSiiLPGozXBq0-MdmsteJAXA"
API_BASE_URL = "https://api.clashofclans.com/v1"

# Cache para datos de clanes
clan_cache = {}
daily_stats_cache = {}
last_update = None

# Variables para controlar el reset diario
last_reset_date = None
reset_in_progress = False
reset_lock = threading.Lock()

# Archivos para persistir datos
DONATIONS_FILE = "daily_donations.json"
BACKUP_FILE = "donations_backup.json"

def verify_admin_password(password):
    """Verifica la contraseña de administrador usando hash"""
    try:
        # Contraseña esperada: AdminFoxyclan21
        expected = "AdminFoxyclan21"
        return password == expected
    except:
        return False

def load_clans():
    """Devuelve la lista de clanes a monitorear"""
    return {
        "22G8YL992": "req n go",
        "9PCULGVU": "Mi Nuevo Clan"
    }

def save_daily_donations():
    """Guarda las donaciones diarias en archivo con respaldo automático"""
    try:
        if os.path.exists(DONATIONS_FILE):
            import shutil
            shutil.copy2(DONATIONS_FILE, BACKUP_FILE)
        
        data_to_save = {
            'last_save': datetime.now().isoformat(),
            'version': '2.3_detailed_clan_info_protected',
            'last_reset_date': last_reset_date.isoformat() if last_reset_date else None,
            'stats': daily_stats_cache
        }
        
        with open(DONATIONS_FILE, 'w', encoding='utf-8') as f:
            json.dump(data_to_save, f, ensure_ascii=False, indent=2)
        
        print(f"Estadísticas guardadas exitosamente - {len(daily_stats_cache)} registros")
        return True
    except Exception as e:
        print(f"Error guardando donaciones: {e}")
        return False

def load_daily_donations():
    """Carga las donaciones diarias desde archivo con sistema de recuperación"""
    global daily_stats_cache, last_reset_date
    
    def try_load_file(filepath):
        try:
            if os.path.exists(filepath):
                with open(filepath, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                if isinstance(data, dict) and 'stats' in data:
                    if 'last_reset_date' in data and data['last_reset_date']:
                        try:
                            last_reset_date = datetime.fromisoformat(data['last_reset_date'].replace('Z', '+00:00'))
                        except:
                            last_reset_date = None
                    return data['stats']
                else:
                    return data
        except Exception as e:
            print(f"Error leyendo {filepath}: {e}")
            return None

    loaded_data = try_load_file(DONATIONS_FILE)
    
    if loaded_data is None:
        print("Archivo principal falló, intentando respaldo...")
        loaded_data = try_load_file(BACKUP_FILE)
    
    if loaded_data is not None:
        daily_stats_cache = loaded_data
        print(f"Estadísticas cargadas exitosamente")
        print(f"{len([k for k in daily_stats_cache.keys() if not k.endswith('_reset')])} jugadores en cache")
        
        if last_reset_date:
            print(f"Último reset: {last_reset_date.strftime('%Y-%m-%d %H:%M:%S')}")
        
        check_pending_reset()
        recover_daily_stats()
    else:
        print("No hay archivos de estadísticas - empezando limpio")
        daily_stats_cache = {}
        last_reset_date = None
        save_daily_donations()

def check_pending_reset():
    """Verifica si hay un reset pendiente al iniciar el servidor"""
    global last_reset_date
    
    argentina_tz = timezone(timedelta(hours=-3))
    now_argentina = datetime.now(argentina_tz)
    today_date = now_argentina.date()
    
    if not last_reset_date or last_reset_date.date() < today_date:
        if now_argentina.hour >= 2:
            print(f"Reset pendiente detectado - Último reset: {last_reset_date}")
            print("Ejecutando reset pendiente...")
            force_daily_reset(auto=True)
        else:
            print("Reset pendiente, pero es antes de las 2 AM - esperando...")

def force_daily_reset(auto=False):
    """Fuerza un reset manual o automático de las donaciones diarias"""
    global daily_stats_cache, last_reset_date, reset_in_progress
    
    with reset_lock:
        if reset_in_progress:
            print("Reset ya en progreso, cancelando...")
            return False
        reset_in_progress = True
    
    try:
        reset_type = "AUTOMÁTICO" if auto else "MANUAL"
        print(f"FORZANDO RESET {reset_type} DE DONACIONES DIARIAS...")
        
        clans = load_clans()
        reset_count = 0
        
        for clan_tag in clans.keys():
            try:
                clan_data = get_clan_data_from_api(clan_tag)
                if not clan_data or not clan_data.get('memberList'):
                    continue
                    
                for member in clan_data['memberList']:
                    member_tag = member.get('tag', '')
                    cache_key = f"{clan_tag}_{member_tag}"
                    current_donations = member.get('donations', 0)
                    current_received = member.get('donationsReceived', 0)
                    
                    daily_stats_cache[cache_key] = {
                        'last_total_donations': current_donations,
                        'last_total_received': current_received,
                        'daily_donations': 0,
                        'daily_received': 0,
                        'last_update': datetime.now().isoformat(),
                        'reset_type': reset_type.lower(),
                        'reset_timestamp': datetime.now().isoformat()
                    }
                    
                    reset_count += 1
                    member_name = member.get('name', 'Unknown')[:15]
                    print(f"Reset {member_name}: base_don={current_donations}, base_rec={current_received}")
            
            except Exception as e:
                print(f"Error en reset para clan {clan_tag}: {e}")
        
        last_reset_date = datetime.now()
        
        if save_daily_donations():
            print(f"Reset {reset_type.lower()} completado - {reset_count} jugadores reseteados")
            if not auto:
                print("Haz algunas donaciones en el juego para ver los cambios")
            return True
        else:
            print("Error guardando reset")
            return False
    
    finally:
        reset_in_progress = False

def recover_daily_stats():
    """Intenta recuperar las donaciones y tropas recibidas de hoy"""
    global daily_stats_cache
    
    print("Intentando recuperar estadísticas del día actual...")
    
    argentina_tz = timezone(timedelta(hours=-3))
    now_argentina = datetime.now(argentina_tz)
    
    if now_argentina.hour < 6:
        print("Es muy temprano, esperando hasta las 6 AM para recovery")
        return
    
    clans = load_clans()
    recovered_count = 0
    
    for clan_tag in clans.keys():
        try:
            clan_data = get_clan_data_from_api(clan_tag)
            if not clan_data or not clan_data.get('memberList'):
                continue
                
            for member in clan_data['memberList']:
                member_tag = member.get('tag', '')
                cache_key = f"{clan_tag}_{member_tag}"
                
                if cache_key not in daily_stats_cache:
                    daily_stats_cache[cache_key] = {
                        'last_total_donations': member.get('donations', 0),
                        'last_total_received': member.get('donationsReceived', 0),
                        'daily_donations': 0,
                        'daily_received': 0,
                        'last_update': now_argentina.isoformat(),
                        'new_player': True
                    }
                    print(f"Nuevo jugador: {member.get('name', 'Unknown')[:15]}")
                    continue
                
                cache_data = daily_stats_cache[cache_key]
                current_donations = member.get('donations', 0)
                current_received = member.get('donationsReceived', 0)
                last_total_donations = cache_data.get('last_total_donations', current_donations)
                last_total_received = cache_data.get('last_total_received', current_received)
                
                current_daily = cache_data.get('daily_donations', 0)
                if (current_daily < 5 and current_donations > last_total_donations):
                    estimated_daily_donations = current_donations - last_total_donations
                    estimated_daily_received = max(0, current_received - last_total_received)
                    
                    if estimated_daily_donations < 1000:
                        daily_stats_cache[cache_key].update({
                            'daily_donations': estimated_daily_donations,
                            'daily_received': estimated_daily_received,
                            'last_total_donations': current_donations,
                            'last_total_received': current_received,
                            'recovered': True,
                            'recovery_timestamp': now_argentina.isoformat()
                        })
                        
                        recovered_count += 1
                        member_name = member.get('name', 'Unknown')[:15]
                        print(f"Recuperado {member_name}: {estimated_daily_donations}don, {estimated_daily_received}rec")
        
        except Exception as e:
            print(f"Error en recovery para clan {clan_tag}: {e}")
    
    if recovered_count > 0:
        save_daily_donations()
        print(f"Recovery completado: {recovered_count} jugadores actualizados")
    else:
        print("No se necesitó recovery")

def make_api_request(endpoint):
    """Realiza una petición a la API de Clash of Clans"""
    try:
        url = f"{API_BASE_URL}/{endpoint}"
        headers = {
            'Authorization': f'Bearer {API_KEY}',
            'Accept': 'application/json',
            'User-Agent': 'ClashTracker/2.3',
            'Cache-Control': 'no-cache',
            'Pragma': 'no-cache'
        }
        print(f"API: {endpoint}")
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status == 200:
                data = json.loads(response.read().decode('utf-8'))
                print(f"API OK: {endpoint}")
                return data
            else:
                print(f"API Error: Status {response.status}")
                return None
    except urllib.error.HTTPError as e:
        error_msg = ""
        try:
            error_response = e.read().decode('utf-8')
            error_detail = json.loads(error_response)
            error_msg = error_detail.get('message', 'Unknown error')
        except:
            error_msg = e.reason
        print(f"HTTP Error {e.code}: {error_msg}")
        if e.code == 403:
            print("Error 403: Verifica tu API Key y que tu IP esté autorizada")
        elif e.code == 404:
            print(f"Error 404: Clan no encontrado")
        elif e.code == 429:
            print("Error 429: Límite de peticiones excedido")
        return None
    except urllib.error.URLError as e:
        print(f"URL Error: {e.reason}")
        return None
    except Exception as e:
        print(f"Error inesperado: {str(e)}")
        return None

def check_daily_reset():
    """Verifica si es hora de resetear estadísticas diarias"""
    global daily_stats_cache, last_reset_date, reset_in_progress
    
    with reset_lock:
        if reset_in_progress:
            return False
        
        argentina_tz = timezone(timedelta(hours=-3))
        now_argentina = datetime.now(argentina_tz)
        today_date = now_argentina.date()
        
        if last_reset_date and last_reset_date.date() >= today_date:
            return False
        
        if not (2 <= now_argentina.hour <= 6):
            return False
        
        reset_in_progress = True
    
    try:
        print(f"RESET AUTOMÁTICO - {now_argentina.strftime('%Y-%m-%d %H:%M:%S')}")
        
        clans = load_clans()
        reset_count = 0
        
        for clan_tag in clans.keys():
            try:
                clan_data = get_clan_data_from_api(clan_tag)
                if not clan_data or not clan_data.get('memberList'):
                    continue
                
                for member in clan_data['memberList']:
                    member_tag = member.get('tag', '')
                    cache_key = f"{clan_tag}_{member_tag}"
                    current_donations = member.get('donations', 0)
                    current_received = member.get('donationsReceived', 0)
                    
                    if cache_key in daily_stats_cache:
                        daily_stats_cache[cache_key].update({
                            'last_total_donations': current_donations,
                            'last_total_received': current_received,
                            'daily_donations': 0,
                            'daily_received': 0,
                            'last_update': now_argentina.isoformat(),
                            'auto_reset': True,
                            'reset_time': now_argentina.isoformat()
                        })
                    else:
                        daily_stats_cache[cache_key] = {
                            'last_total_donations': current_donations,
                            'last_total_received': current_received,
                            'daily_donations': 0,
                            'daily_received': 0,
                            'last_update': now_argentina.isoformat(),
                            'auto_reset': True,
                            'reset_time': now_argentina.isoformat()
                        }
                    
                    reset_count += 1
                    member_name = member.get('name', 'Unknown')[:15]
                    print(f"Reset automático {member_name}: base={current_donations}")
            
            except Exception as e:
                print(f"Error en reset automático para clan {clan_tag}: {e}")
        
        last_reset_date = now_argentina
        
        if save_daily_donations():
            print(f"Reset automático completado - {reset_count} jugadores reseteados")
            return True
        else:
            print("Error guardando reset automático")
            return False
    
    except Exception as e:
        print(f"Error en check_daily_reset: {e}")
        return False
    
    finally:
        reset_in_progress = False

def calculate_daily_stats(clan_tag, member_tag, current_donations, current_received):
    """Calcula donaciones Y tropas recibidas diarias"""
    global daily_stats_cache
    
    argentina_tz = timezone(timedelta(hours=-3))
    now_argentina = datetime.now(argentina_tz)
    
    cache_key = f"{clan_tag}_{member_tag}"
    
    if cache_key not in daily_stats_cache:
        daily_stats_cache[cache_key] = {
            'last_total_donations': current_donations,
            'last_total_received': current_received,
            'daily_donations': 0,
            'daily_received': 0,
            'last_update': now_argentina.isoformat(),
            'created': now_argentina.isoformat()
        }
        save_daily_donations()
        return 0, 0

    cache_data = daily_stats_cache[cache_key]
    last_total_donations = cache_data.get('last_total_donations', current_donations)
    last_total_received = cache_data.get('last_total_received', current_received)
    daily_donations = cache_data.get('daily_donations', 0)
    daily_received = cache_data.get('daily_received', 0)

    if current_donations < last_total_donations - 50:
        print(f"Reset del juego detectado para {member_tag}")
        daily_stats_cache[cache_key].update({
            'last_total_donations': current_donations,
            'last_total_received': current_received,
            'daily_donations': 0,
            'daily_received': 0,
            'last_update': now_argentina.isoformat(),
            'game_reset': True
        })
        save_daily_donations()
        return 0, 0

    donations_diff = max(0, current_donations - last_total_donations)
    received_diff = max(0, current_received - last_total_received)

    if donations_diff > 0 or received_diff > 0:
        daily_donations += donations_diff
        daily_received += received_diff
        
        if donations_diff > 0:
            print(f"{member_tag[-8:]}: +{donations_diff} donaciones (Total día: {daily_donations})")
        if received_diff > 0:
            print(f"{member_tag[-8:]}: +{received_diff} recibidas (Total día: {daily_received})")

        daily_stats_cache[cache_key].update({
            'last_total_donations': current_donations,
            'last_total_received': current_received,
            'daily_donations': daily_donations,
            'daily_received': daily_received,
            'last_update': now_argentina.isoformat()
        })

        save_daily_donations()

    return daily_donations, daily_received

def get_clan_daily_summary(clan_tag):
    """Calcula el resumen de donaciones diarias del clan"""
    try:
        clan_data = get_clan_data_from_api(clan_tag)
        if not clan_data or not clan_data.get('memberList'):
            return {'total_daily_donations': 0, 'total_daily_received': 0, 'time_until_reset': ''}
        
        total_daily_donations = 0
        total_daily_received = 0
        
        for member in clan_data['memberList']:
            daily_donations = member.get('dailyDonations', 0)
            daily_received = member.get('dailyReceived', 0)
            total_daily_donations += daily_donations
            total_daily_received += daily_received
        
        argentina_tz = timezone(timedelta(hours=-3))
        now_argentina = datetime.now(argentina_tz)
        
        if now_argentina.hour >= 2:
            next_reset = now_argentina.replace(hour=2, minute=0, second=0, microsecond=0) + timedelta(days=1)
        else:
            next_reset = now_argentina.replace(hour=2, minute=0, second=0, microsecond=0)
        
        time_diff = next_reset - now_argentina
        hours = int(time_diff.seconds // 3600)
        minutes = int((time_diff.seconds % 3600) // 60)
        seconds = int(time_diff.seconds % 60)
        
        time_until_reset = f"{hours:02d}:{minutes:02d}:{seconds:02d}"
        
        return {
            'total_daily_donations': total_daily_donations,
            'total_daily_received': total_daily_received,
            'time_until_reset': time_until_reset
        }
        
    except Exception as e:
        print(f"Error calculando resumen diario para clan {clan_tag}: {e}")
        return {'total_daily_donations': 0, 'total_daily_received': 0, 'time_until_reset': ''}

def get_clan_data_from_api(clan_tag):
    """Obtiene datos reales del clan desde la API de Clash of Clans"""
    global clan_cache

    clean_tag = clan_tag.replace('#', '')
    print(f"Obteniendo datos detallados del clan #{clean_tag}...")

    try:
        clan_info = make_api_request(f"clans/%23{clean_tag}")
        if not clan_info:
            print(f"No se pudo obtener info del clan #{clean_tag}")
            return get_fallback_clan_data(clan_tag)

        members_info = clan_info.get('memberList', [])

        total_donations = sum(member.get('donations', 0) for member in members_info)
        total_received = sum(member.get('donationsReceived', 0) for member in members_info)

        member_list = []
        for member in members_info:
            member_tag = member.get('tag', '')
            member_name = member.get('name', 'Unknown')
            current_donations = member.get('donations', 0)
            current_received = member.get('donationsReceived', 0)

            daily_donations, daily_received = calculate_daily_stats(
                clean_tag, member_tag, current_donations, current_received
            )

            member_list.append({
                "tag": member_tag,
                "name": member_name,
                "donations": current_donations,
                "donationsReceived": current_received,
                "trophies": member.get('trophies', 0),
                "dailyDonations": daily_donations,
                "dailyReceived": daily_received,
                "expLevel": member.get('expLevel', 1),
                "townhallLevel": member.get('townHallLevel', 1),
                "role": member.get('role', 'member'),
                "clanRank": member.get('clanRank', 0),
                "previousClanRank": member.get('previousClanRank', 0),
                "league": member.get('league', {}),
                "playerHouse": member.get('playerHouse', {})
            })

        leader_name = "Unknown"
        for member in members_info:
            if member.get('role') == 'leader':
                leader_name = member.get('name', 'Unknown')
                break

        clan_data = {
            "name": clan_info.get('name', 'Unknown Clan'),
            "tag": f"#{clean_tag}",
            "members": clan_info.get('members', 0),
            "leader": leader_name,
            "totalDonations": total_donations,
            "totalReceived": total_received,
            "memberList": member_list,
            "level": clan_info.get('clanLevel', 1),
            "points": clan_info.get('clanPoints', 0),
            "description": clan_info.get('description', 'Sin descripción'),
            "location": clan_info.get('location', {}),
            "type": clan_info.get('type', 'open'),
            "requiredTrophies": clan_info.get('requiredTrophies', 0),
            "warWins": clan_info.get('warWins', 0),
            "warWinStreak": clan_info.get('warWinStreak', 0),
            "warLosses": clan_info.get('warLosses', 0),
            "isWarLogPublic": clan_info.get('isWarLogPublic', False),
            "warFrequency": clan_info.get('warFrequency', 'unknown'),
            "clanCapital": clan_info.get('clanCapital', {}),
            "badgeUrls": clan_info.get('badgeUrls', {}),
            "chatLanguage": clan_info.get('chatLanguage', {}),
            "labels": clan_info.get('labels', [])
        }

        clan_cache[clan_tag] = {
            "data": clan_data,
            "timestamp": datetime.now()
        }

        print(f"Datos detallados obtenidos para {clan_data['name']}: {total_donations:,} donaciones, {len(member_list)} miembros")
        return clan_data

    except Exception as e:
        print(f"Error al obtener datos detallados del clan #{clean_tag}: {str(e)}")
        return get_fallback_clan_data(clan_tag)

def get_fallback_clan_data(clan_tag):
    """Datos de respaldo si la API falla"""
    print(f"Usando datos de respaldo para clan #{clan_tag}")
    clans = load_clans()
    clan_name = clans.get(clan_tag, f"Clan #{clan_tag}")

    return {
        "name": clan_name,  
        "tag": f"#{clan_tag}",
        "members": 1,
        "leader": "Leader Respaldo",
        "totalDonations": 0,
        "totalReceived": 0,
        "level": 1,
        "points": 0,
        "description": "Sin conexión a la API",
        "type": "open",
        "requiredTrophies": 0,
        "warWins": 0,
        "warWinStreak": 0,
        "warLosses": 0,
        "isWarLogPublic": False,
        "warFrequency": "unknown",
        "clanCapital": {},
        "badgeUrls": {},
        "chatLanguage": {},
        "labels": [],
        "memberList": [{
            "tag": "#FALLBACK",
            "name": "Sin conexión",
            "donations": 0,
            "donationsReceived": 0,
            "trophies": 0,
            "dailyDonations": 0,
            "dailyReceived": 0,
            "expLevel": 1,
            "townhallLevel": 1,
            "role": "member",
            "clanRank": 1,
            "previousClanRank": 1,
            "league": {},
            "playerHouse": {}
        }]
    }

def get_clan_data(clan_tag):
    """Wrapper para obtener datos del clan con cache"""
    try:
        return get_clan_data_from_api(clan_tag)
    except Exception as e:
        print(f"Error obteniendo datos del clan {clan_tag}: {e}")
        return get_fallback_clan_data(clan_tag)

def process_clans_ranking():
    """Procesa y ordena clanes por donaciones totales"""
    global last_update
    
    clans = load_clans()
    ranking = []
    
    for clan_tag, clan_name in clans.items():
        clan_data = get_clan_data(clan_tag)
        if clan_data:
            ranking.append(clan_data)
    
    ranking.sort(key=lambda x: x.get('totalDonations', 0), reverse=True)
    
    last_update = datetime.now().strftime('%H:%M:%S')
    
    return ranking

def daily_reset_worker():
    """Hilo para manejar reset automático diario"""
    while True:
        try:
            check_daily_reset()
            time.sleep(120)
        except Exception as e:
            print(f"Error en daily_reset_worker: {e}")
            time.sleep(300)

def auto_backup_worker():
    """Hilo para respaldos automáticos"""
    while True:
        try:
            time.sleep(120)
            save_daily_donations()
        except Exception as e:
            print(f"Error en auto_backup_worker: {e}")
            time.sleep(300)

def auto_update_worker():
    """Hilo para actualizaciones automáticas"""
    while True:
        try:
            time.sleep(90)
            clans = load_clans()
            for clan_tag in clans.keys():
                get_clan_data_from_api(clan_tag)
        except Exception as e:
            print(f"Error en auto_update_worker: {e}")
            time.sleep(180)

# Página HTML PROTEGIDA con sistema de contraseña
HTML_PAGE = '''<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>TOP REQ CLANS - Mobile Optimized</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Arial, sans-serif;
            background: #f5f5f5;
            color: #333;
            font-size: 13px;
            line-height: 1.3;
        }
        
        .header {
            background: #1a1a1a;
            color: white;
            padding: 8px 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            position: sticky;
            top: 0;
            z-index: 100;
        }
        
        .logo {
            font-size: 16px;
            font-weight: bold;
        }
        
        .logo .top { color: #ff6b35; }
        .logo .req { color: #ff1744; }
        .logo .clans { color: #ff6b35; }
        
        .container {
            max-width: 100%;
            margin: 0;
            background: white;
            min-height: calc(100vh - 50px);
        }
        
        .main-view {
            padding: 10px;
        }
        
        .page-title {
            font-size: 18px;
            font-weight: bold;
            margin-bottom: 6px;
            color: #333;
        }
        
        .update-info {
            font-size: 11px;
            color: #666;
            margin-bottom: 8px;
        }
        
        .api-status, .persistence-status {
            background: #e8f5e8;
            color: #2e7d32;
            padding: 5px 8px;
            border-radius: 4px;
            font-size: 10px;
            margin-bottom: 6px;
            border-left: 3px solid #4caf50;
        }
        
        .reset-status {
            background: #fff3e0;
            color: #f57c00;
            padding: 5px 8px;
            border-radius: 4px;
            font-size: 10px;
            margin-bottom: 8px;
            border-left: 3px solid #ff9800;
        }
        
        .clans-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
            border-radius: 6px;
            overflow: hidden;
            font-size: 12px;
            border: 1px solid #dee2e6;
        }
        
        .clans-table th {
            background: #f8f9fa;
            padding: 8px 4px;
            text-align: center;
            font-weight: 600;
            border-bottom: 2px solid #dee2e6;
            border-right: 1px solid #dee2e6;
            font-size: 11px;
            color: #495057;
        }
        
        .clans-table th:last-child {
            border-right: none;
        }
        
        .clans-table td {
            padding: 6px 4px;
            border-bottom: 1px solid #f1f1f1;
            border-right: 1px solid #f1f1f1;
            vertical-align: middle;
            font-size: 11px;
            color: #333;
            text-align: center;
        }
        
        .clans-table td:nth-child(2) {
            text-align: left;
        }
        
        .clans-table td:last-child {
            border-right: none;
        }
        
        .clans-table tr:nth-child(even) {
            background: #f8f9fa;
        }
        
        .clans-table tr:hover {
            background: #e3f2fd;
            cursor: pointer;
        }
        
        .clan-badge {
            width: 20px;
            height: 20px;
            border-radius: 50%;
            margin-right: 4px;
            vertical-align: middle;
        }
        
        .auto-refresh {
            position: fixed;
            bottom: 10px;
            right: 10px;
            background: #6c5ce7;
            color: white;
            padding: 6px 10px;
            border-radius: 15px;
            font-size: 10px;
            box-shadow: 0 2px 8px rgba(0,0,0,0.2);
            z-index: 1000;
        }
        
        .clan-detail-view {
            padding: 8px;
        }
        
        .back-button {
            background: #6c5ce7;
            color: white;
            border: none;
            padding: 8px 12px;
            border-radius: 4px;
            cursor: pointer;
            margin-bottom: 10px;
            font-size: 12px;
        }
        
        .clan-header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            text-align: center;
            position: relative;
            overflow: hidden;
        }
        
        .clan-header::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(255,255,255,0.1);
            backdrop-filter: blur(10px);
            z-index: 1;
        }
        
        .clan-header-content {
            position: relative;
            z-index: 2;
        }
        
        .clan-logo-section {
            display: flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 10px;
            gap: 10px;
        }
        
        .clan-logo {
            width: 50px;
            height: 50px;
            border-radius: 8px;
            border: 2px solid rgba(255,255,255,0.3);
            background: rgba(255,255,255,0.1);
        }
        
        .clan-title-info {
            text-align: left;
        }
        
        .clan-name {
            font-size: 20px;
            font-weight: bold;
            margin-bottom: 3px;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }
        
        .clan-tag {
            font-size: 12px;
            opacity: 0.8;
            font-family: monospace;
        }
        
        .clan-level-badge {
            background: rgba(255,193,7,0.9);
            color: #333;
            padding: 3px 6px;
            border-radius: 10px;
            font-size: 11px;
            font-weight: bold;
            margin-top: 3px;
            display: inline-block;
        }
        
        .clan-detailed-info {
            margin-bottom: 10px;
        }
        
        .clan-info-card {
            background: white;
            border: 1px solid #dee2e6;
            border-radius: 8px;
            padding: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            margin-bottom: 10px;
        }
        
        .info-card-title {
            font-size: 13px;
            font-weight: bold;
            color: #495057;
            margin-bottom: 8px;
            border-bottom: 2px solid #6c5ce7;
            padding-bottom: 4px;
        }
        
        .info-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }
        
        .info-column {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        
        .info-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-size: 11px;
        }
        
        .info-label {
            color: #6c757d;
            font-weight: 500;
        }
        
        .info-value {
            color: #333;
            font-weight: 600;
        }
        
        .time-until-reset {
            text-align: center;
            font-size: 11px;
            color: #856404;
            margin-bottom: 10px;
            padding: 8px;
            background: linear-gradient(135deg, #fff3cd 0%, #ffeaa7 100%);
            border: 1px solid #ffeaa7;
            border-radius: 6px;
            font-weight: 500;
        }
        
        .reset-timer {
            font-size: 14px;
            font-weight: bold;
            color: #dc3545;
            margin-left: 4px;
        }

        .tab-buttons {
            display: flex;
            margin-bottom: 10px;
            background: #f8f9fa;
            border-radius: 6px;
            overflow: hidden;
            gap: 1px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .tab-button {
            flex: 1;
            padding: 6px 4px;
            background: transparent;
            border: none;
            cursor: pointer;
            font-size: 10px;
            font-weight: 600;
            transition: all 0.2s ease;
            text-align: center;
            color: #6c757d;
        }
        
        .tab-button.active {
            background: #6c5ce7;
            color: white;
            box-shadow: 0 2px 4px rgba(108, 92, 231, 0.3);
        }
        
        .tab-button.reset-btn {
            background: #ff6b35 !important;
            color: white !important;
        }
        
        .tab-button.reset-btn:hover {
            background: #ff5722 !important;
        }
        
        .modal {
            display: none;
            position: fixed;
            z-index: 10000;
            left: 0;
            top: 0;
            width: 100%;
            height: 100%;
            background-color: rgba(0,0,0,0.8);
            backdrop-filter: blur(4px);
        }
        
        .modal-content {
            position: absolute;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: white;
            padding: 20px;
            border-radius: 12px;
            box-shadow: 0 8px 32px rgba(0,0,0,0.3);
            width: 90%;
            max-width: 350px;
        }
        
        .modal-header {
            font-size: 16px;
            font-weight: bold;
            margin-bottom: 15px;
            color: #333;
            text-align: center;
        }
        
        .modal-body {
            margin-bottom: 20px;
        }
        
        .modal-input {
            width: 100%;
            padding: 10px;
            border: 2px solid #dee2e6;
            border-radius: 6px;
            font-size: 14px;
            margin-bottom: 10px;
        }
        
        .modal-input:focus {
            outline: none;
            border-color: #6c5ce7;
            box-shadow: 0 0 0 3px rgba(108, 92, 231, 0.1);
        }
        
        .modal-buttons {
            display: flex;
            gap: 10px;
            justify-content: flex-end;
        }
        
        .modal-btn {
            padding: 8px 16px;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-weight: 600;
            font-size: 12px;
        }
        
        .modal-btn-cancel {
            background: #6c757d;
            color: white;
        }
        
        .modal-btn-confirm {
            background: #ff6b35;
            color: white;
        }
        
        .password-error {
            color: #dc3545;
            font-size: 11px;
            margin-top: 5px;
            display: none;
        }
        
        .players-table {
            width: 100%;
            border-collapse: collapse;
            background: white;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-radius: 6px;
            overflow: hidden;
            font-size: 10px;
            border: 1px solid #dee2e6;
        }
        
        .players-table th {
            background: #f8f9fa;
            color: #333;
            padding: 8px 4px;
            text-align: center;
            font-weight: 600;
            border-right: 1px solid #dee2e6;
            font-size: 9px;
        }
        
        .players-table th:last-child {
            border-right: none;
        }
        
        .players-table td {
            padding: 6px 4px;
            border-bottom: 1px solid #f1f1f1;
            border-right: 1px solid #f1f1f1;
            text-align: center;
            font-size: 9px;
            vertical-align: middle;
            color: #333;
        }
        
        .players-table td:last-child {
            border-right: none;
        }
        
        .players-table td:nth-child(2) {
            text-align: left;
            padding-left: 6px;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 80px;
        }
        
        .players-table tr:nth-child(even) {
            background: #f8f9fa;
        }
        
        .players-table tr:hover {
            background: #e3f2fd;
            transform: scale(1.005);
            transition: all 0.1s ease;
        }
        
        .role-badge {
            font-size: 7px;
            padding: 2px 4px;
            border-radius: 8px;
            font-weight: bold;
            text-transform: uppercase;
            color: #333;
            background: #e9ecef;
            border: 1px solid #ced4da;
        }
        
        .th-level {
            background: #e9ecef;
            color: #333;
            padding: 2px 4px;
            border-radius: 3px;
            font-weight: bold;
            font-size: 8px;
            border: 1px solid #ced4da;
        }
        
        .exp-level {
            background: #e9ecef;
            color: #333;
            padding: 1px 3px;
            border-radius: 2px;
            font-weight: bold;
            font-size: 7px;
            border: 1px solid #ced4da;
        }
        
        .rank-change {
            font-size: 7px;
            font-weight: bold;
        }
        
        .rank-up {
            color: #28a745;
        }
        
        .rank-down {
            color: #dc3545;
        }
        
        .rank-same {
            color: #6c757d;
        }
        
        @media (max-width: 480px) {
            .clan-logo-section {
                flex-direction: column;
                gap: 8px;
            }
            
            .clan-title-info {
                text-align: center;
            }
            
            .info-grid {
                grid-template-columns: 1fr;
            }
            
            .players-table {
                font-size: 8px;
            }
            
            .players-table th,
            .players-table td {
                padding: 4px 3px;
            }
            
            .tab-button {
                padding: 5px 2px;
                font-size: 9px;
            }
        }
    </style>
</head>
<body>
    <header class="header">
        <div class="logo">
            <span class="top">TOP</span> <span class="req">REQ</span> <span class="clans">CLANS</span>
        </div>
    </header>
    
    <div class="modal" id="passwordModal">
        <div class="modal-content">
            <div class="modal-header">Acceso Restringido</div>
            <div class="modal-body">
                <p style="font-size: 12px; color: #666; margin-bottom: 10px;">
                    Esta función requiere autorización de administrador:
                </p>
                <input type="password" 
                       class="modal-input" 
                       id="passwordInput" 
                       placeholder="Ingresa la contraseña de administrador"
                       autocomplete="off">
                <div class="password-error" id="passwordError">
                    Contraseña incorrecta. Acceso denegado.
                </div>
            </div>
            <div class="modal-buttons">
                <button class="modal-btn modal-btn-cancel" onclick="closePasswordModal()">
                    Cancelar
                </button>
                <button class="modal-btn modal-btn-confirm" onclick="checkPassword()">
                    Confirmar Reset
                </button>
            </div>
        </div>
    </div>
    
    <div class="container">
        <div class="main-view" id="mainView">
            <h1 class="page-title">Top Req Clans - Current season</h1>
            <div class="api-status">Conectado a la API oficial de Clash of Clans</div>
            <div class="persistence-status">Sistema de persistencia activado - Reset automático 2-6 AM</div>
            <div class="reset-status">Optimizado para móvil - Vista compacta con protección</div>
            <p class="update-info">Actualización automática cada 90s (Última: <span id="lastUpdate">Cargando...</span>)</p>
            
            <table class="clans-table">
                <thead>
                    <tr>
                        <th>Rank</th>
                        <th>Clan</th>
                        <th>Level</th>
                        <th>Leader</th>
                        <th>Donaciones</th>
                        <th>Recibidas</th>
                    </tr>
                </thead>
                <tbody id="clansTableBody">
                    <tr>
                        <td colspan="6" style="text-align: center; padding: 20px;">
                            Cargando datos...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
        
        <div class="clan-detail-view" id="clanDetailView" style="display: none;">
            <button class="back-button" onclick="showMainView()">← Volver</button>
            
            <div class="clan-header">
                <div class="clan-header-content">
                    <div class="clan-logo-section">
                        <img id="clanLogo" src="" alt="Clan Logo" class="clan-logo" onerror="this.src='data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iNTAiIGhlaWdodD0iNTAiIHZpZXdCb3g9IjAgMCA1MCA1MCIgZmlsbD0ibm9uZSIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj4KPHJlY3Qgd2lkdGg9IjUwIiBoZWlnaHQ9IjUwIiByeD0iOCIgZmlsbD0iIzZjNWNlNyIvPgo8c3ZnIHdpZHRoPSIyNCIgaGVpZ2h0PSIyNCIgdmlld0JveD0iMCAwIDI0IDI0IiBmaWxsPSJ3aGl0ZSIgdHJhbnNmb3JtPSJ0cmFuc2xhdGUoMTMsIDEzKSI+CjxwYXRoIGQ9Ik0xMiAyTDQgN1YxN0wxMiAyMkwyMCAxN1Y3TDEyIDJaIi8+Cjwvc3ZnPgo8L3N2Zz4='">
                        <div class="clan-title-info">
                            <div class="clan-name" id="detailClanName">req n go</div>
                            <div class="clan-tag" id="detailClanTag">#22G8YL992</div>
                            <div class="clan-level-badge" id="detailClanLevel">Level 15</div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="clan-detailed-info">
                <div class="clan-info-card">
                    <div class="info-card-title">Estadísticas Generales</div>
                    <div class="info-grid">
                        <div class="info-column">
                            <div class="info-item">
                                <span class="info-label">Miembros:</span>
                                <span class="info-value" id="detailMembers">43/50</span>
                            </div>
                            <div class="info-item">
                                <span class="info-label">Puntos del clan:</span>
                                <span class="info-value" id="detailClanPoints">47,892</span>
                            </div>
                            <div class="info-item">
                                <span class="info-label">Líder:</span>
                                <span class="info-value" id="detailLeader">Foxx</span>
                            </div>
                            <div class="info-item">
                                <span class="info-label">Tipo:</span>
                                <span class="info-value" id="detailClanType">Abierto</span>
                            </div>
                        </div>
                        
                        <div class="info-column">
                            <div class="info-item">
                                <span class="info-label">Total temporada:</span>
                                <span class="info-value" id="detailTotalDonations">3,926,074</span>
                            </div>
                            <div class="info-item">
                                <span class="info-label">Total recibidas:</span>
                                <span class="info-value" id="detailTotalReceived">2,841,592</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>

            <div class="time-until-reset" id="timeUntilReset">
                Próximo reset diario en: <span class="reset-timer" id="resetTimer">05:23:14</span>
            </div>

            <div class="tab-buttons">
                <button class="tab-button active" onclick="showTab('total')">Total temporada</button>
                <button class="tab-button" onclick="showTab('donations')">Donaciones hoy</button>
                <button class="tab-button" onclick="showTab('received')">Recibidas hoy</button>
                <button class="tab-button reset-btn" onclick="showPasswordModal()">Reset manual</button>
            </div>
            
            <table class="players-table" id="playersTable">
                <thead>
                    <tr>
                        <th>TOP</th>
                        <th>Jugador</th>
                        <th>Rol</th>
                        <th>TH</th>
                        <th>Exp</th>
                        <th>Total</th>
                        <th>Trofeos</th>
                    </tr>
                </thead>
                <tbody id="playersTableBody">
                    <tr>
                        <td colspan="7" style="text-align: center; padding: 20px;">
                            Cargando jugadores...
                        </td>
                    </tr>
                </tbody>
            </table>
        </div>
    </div>
    
    <div class="auto-refresh" id="autoRefresh">
        Auto-refresh: ON
    </div>

    <script>
        let currentClanTag = null;
        let currentSort = 'total';
        let autoRefreshInterval = null;
        let resetTimerInterval = null;

        const securityCheck = function() {
            return 'AdminFoxyclan21';
        };

        document.addEventListener('DOMContentLoaded', function() {
            loadMainData();
            startAutoRefresh();
            
            document.getElementById('passwordInput').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    checkPassword();
                }
            });
        });

        function loadMainData() {
            fetch('/api/ranking')
                .then(response => response.json())
                .then(data => {
                    updateMainTable(data);
                    document.getElementById('lastUpdate').textContent = new Date().toLocaleTimeString();
                })
                .catch(error => {
                    console.error('Error loading main data:', error);
                    document.getElementById('clansTableBody').innerHTML = 
                        '<tr><td colspan="6" style="text-align: center; padding: 20px; color: red;">Error cargando datos</td></tr>';
                });
        }

        function updateMainTable(clans) {
            const tbody = document.getElementById('clansTableBody');
            if (!clans || clans.length === 0) {
                tbody.innerHTML = '<tr><td colspan="6" style="text-align: center; padding: 20px;">No hay datos disponibles</td></tr>';
                return;
            }

            let html = '';
            clans.forEach((clan, index) => {
                const badgeUrl = clan.badgeUrls && clan.badgeUrls.small ? clan.badgeUrls.small : '';
                const logoHtml = badgeUrl ? 
                    `<img src="${badgeUrl}" class="clan-badge" onerror="this.style.display='none'">` : 
                    '<div style="width: 20px; height: 20px; display: inline-block;"></div>';
                
                html += `
                    <tr onclick="showClanDetail('${clan.tag.replace('#', '')}')" style="cursor: pointer;">
                        <td style="text-align: center; vertical-align: middle;">${index + 1}</td>
                        <td style="text-align: left; vertical-align: middle;">${logoHtml}${clan.name}</td>
                        <td style="text-align: center; vertical-align: middle;">${clan.level || 1}</td>
                        <td style="text-align: center; vertical-align: middle;">${clan.leader || 'Unknown'}</td>
                        <td style="text-align: center; vertical-align: middle;">${(clan.totalDonations || 0).toLocaleString()}</td>
                        <td style="text-align: center; vertical-align: middle;">${(clan.totalReceived || 0).toLocaleString()}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }

        function showClanDetail(clanTag) {
            currentClanTag = clanTag;
            document.getElementById('mainView').style.display = 'none';
            document.getElementById('clanDetailView').style.display = 'block';
            
            loadClanDetail(clanTag);
        }

        function showMainView() {
            document.getElementById('clanDetailView').style.display = 'none';
            document.getElementById('mainView').style.display = 'block';
            currentClanTag = null;
            
            if (resetTimerInterval) {
                clearInterval(resetTimerInterval);
                resetTimerInterval = null;
            }
        }

        function loadClanDetail(clanTag) {
            fetch(`/api/clan/${clanTag}`)
                .then(response => response.json())
                .then(clan => {
                    updateClanHeader(clan);
                    updateClanInfo(clan);
                    updatePlayersTable(clan.memberList || []);
                    loadDailySummary(clanTag);
                    startResetTimer();
                })
                .catch(error => {
                    console.error('Error loading clan detail:', error);
                });
        }

        function updateClanHeader(clan) {
            document.getElementById('detailClanName').textContent = clan.name || 'Unknown';
            document.getElementById('detailClanTag').textContent = clan.tag || '#UNKNOWN';
            document.getElementById('detailClanLevel').textContent = `Level ${clan.level || 1}`;
            
            const logoUrl = clan.badgeUrls && clan.badgeUrls.medium ? clan.badgeUrls.medium : '';
            if (logoUrl) {
                document.getElementById('clanLogo').src = logoUrl;
            }
        }

        function updateClanInfo(clan) {
            document.getElementById('detailMembers').textContent = `${clan.members || 0}/50`;
            document.getElementById('detailClanPoints').textContent = (clan.points || 0).toLocaleString();
            document.getElementById('detailLeader').textContent = clan.leader || 'Unknown';
            document.getElementById('detailClanType').textContent = translateClanType(clan.type || 'open');
            
            document.getElementById('detailTotalDonations').textContent = (clan.totalDonations || 0).toLocaleString();
            document.getElementById('detailTotalReceived').textContent = (clan.totalReceived || 0).toLocaleString();
        }

        function loadDailySummary(clanTag) {
            fetch(`/api/clan/${clanTag}/daily-summary`)
                .then(response => response.json())
                .then(summary => {
                    // Removido: información diaria ya no se muestra en la tarjeta
                })
                .catch(error => {
                    console.error('Error loading daily summary:', error);
                });
        }

        function updatePlayersTable(members) {
            const tbody = document.getElementById('playersTableBody');
            if (!members || members.length === 0) {
                tbody.innerHTML = '<tr><td colspan="7" style="text-align: center; padding: 20px;">No hay miembros</td></tr>';
                return;
            }

            let sortedMembers = [...members];
            if (currentSort === 'donations') {
                sortedMembers.sort((a, b) => (b.dailyDonations || 0) - (a.dailyDonations || 0));
            } else if (currentSort === 'received') {
                sortedMembers.sort((a, b) => (b.dailyReceived || 0) - (a.dailyReceived || 0));
            } else if (currentSort === 'total') {
                sortedMembers.sort((a, b) => (b.donations || 0) - (a.donations || 0));
            }

            let html = '';
            sortedMembers.forEach((member, index) => {
                const rankChange = getRankChange(member.clanRank, member.previousClanRank);
                
                let totalValue = 0;
                if (currentSort === 'donations') {
                    totalValue = member.dailyDonations || 0;
                } else if (currentSort === 'received') {
                    totalValue = member.dailyReceived || 0;
                } else {
                    totalValue = member.donations || 0;
                }
                
                html += `
                    <tr>
                        <td>Top ${index + 1} ${rankChange}</td>
                        <td title="${member.name}">${member.name || 'Unknown'}</td>
                        <td><span class="role-badge">${translateRole(member.role)}</span></td>
                        <td><span class="th-level">TH${member.townhallLevel || 1}</span></td>
                        <td><span class="exp-level">${member.expLevel || 1}</span></td>
                        <td>${totalValue.toLocaleString()}</td>
                        <td>${(member.trophies || 0).toLocaleString()}</td>
                    </tr>
                `;
            });
            tbody.innerHTML = html;
        }

        function showTab(tabName) {
            document.querySelectorAll('.tab-button:not(.reset-btn)').forEach(btn => btn.classList.remove('active'));
            event.target.classList.add('active');
            
            currentSort = tabName;
            
            if (currentClanTag) {
                loadClanDetail(currentClanTag);
            }
        }

        function showPasswordModal() {
            const modal = document.getElementById('passwordModal');
            const input = document.getElementById('passwordInput');
            const error = document.getElementById('passwordError');
            
            input.value = '';
            error.style.display = 'none';
            
            modal.style.display = 'block';
            setTimeout(() => input.focus(), 100);
        }

        function closePasswordModal() {
            document.getElementById('passwordModal').style.display = 'none';
        }

        function checkPassword() {
            const input = document.getElementById('passwordInput');
            const error = document.getElementById('passwordError');
            const enteredPassword = input.value;
            
            if (enteredPassword === securityCheck()) {
                closePasswordModal();
                executeResetDaily();
            } else {
                error.style.display = 'block';
                input.value = '';
                input.focus();
            }
        }

        function executeResetDaily() {
            if (confirm('CONTRASEÑA CORRECTA\\n\\n¿Confirmas el reset de donaciones diarias?\\n\\nEsta acción reiniciará todos los contadores diarios del clan actual.')) {
                fetch('/api/reset-daily')
                    .then(response => response.json())
                    .then(result => {
                        if (result.success) {
                            alert('✅ RESET COMPLETADO EXITOSAMENTE\\n\\nTodas las donaciones diarias han sido reiniciadas.\\nHaz algunas donaciones en el juego para ver los cambios.');
                            if (currentClanTag) {
                                loadClanDetail(currentClanTag);
                            }
                        } else {
                            alert('⚠️ ERROR EN EL RESET\\n\\nNo se pudo completar el reset: ' + result.message);
                        }
                    })
                    .catch(error => {
                        console.error('Error in reset:', error);
                        alert('💔 ERROR DE CONEXIÓN\\n\\nNo se pudo conectar con el servidor para realizar el reset.');
                    });
            }
        }

        function getRankChange(current, previous) {
            if (!current || !previous) return '';
            
            if (current < previous) {
                return `<span class="rank-change rank-up">↑${previous - current}</span>`;
            } else if (current > previous) {
                return `<span class="rank-change rank-down">↓${current - previous}</span>`;
            }
            return '<span class="rank-change rank-same">-</span>';
        }

        function translateRole(role) {
            switch (role) {
                case 'leader': return 'Líder';
                case 'coLeader': return 'Co-líder';
                case 'elder': return 'Veterano';
                case 'member': return 'Miembro';
                default: return 'Miembro';
            }
        }

        function translateClanType(type) {
            switch (type) {
                case 'open': return 'Abierto';
                case 'inviteOnly': return 'Solo invitación';
                case 'closed': return 'Cerrado';
                default: return 'Abierto';
            }
        }

        function startResetTimer() {
            if (resetTimerInterval) {
                clearInterval(resetTimerInterval);
            }
            
            resetTimerInterval = setInterval(updateResetTimer, 1000);
            updateResetTimer();
        }

        function updateResetTimer() {
            const now = new Date();
            const argentinaTime = new Date(now.toLocaleString("en-US", {timeZone: "America/Argentina/Buenos_Aires"}));
            
            let nextReset = new Date(argentinaTime);
            if (argentinaTime.getHours() >= 2) {
                nextReset.setDate(nextReset.getDate() + 1);
            }
            nextReset.setHours(2, 0, 0, 0);
            
            const diff = nextReset - argentinaTime;
            if (diff > 0) {
                const hours = Math.floor(diff / (1000 * 60 * 60));
                const minutes = Math.floor((diff % (1000 * 60 * 60)) / (1000 * 60));
                const seconds = Math.floor((diff % (1000 * 60)) / 1000);
                
                document.getElementById('resetTimer').textContent = 
                    `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
            }
        }

        function startAutoRefresh() {
            autoRefreshInterval = setInterval(() => {
                if (currentClanTag) {
                    loadClanDetail(currentClanTag);
                } else {
                    loadMainData();
                }
            }, 90000);
        }

        document.addEventListener('keydown', function(e) {
            if (e.key === 'Escape') {
                if (document.getElementById('passwordModal').style.display === 'block') {
                    closePasswordModal();
                } else if (currentClanTag) {
                    showMainView();
                }
            } else if (e.key === 'r' && e.ctrlKey && currentClanTag) {
                e.preventDefault();
                showPasswordModal();
            }
        });

        document.getElementById('passwordModal').addEventListener('click', function(e) {
            if (e.target === this) {
                closePasswordModal();
            }
        });
    </script>
</body>
</html>'''

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        try:
            if self.path == '/' or self.path == '/index.html':
                self.send_response(200)
                self.send_header('Content-Type', 'text/html; charset=utf-8')
                self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
                self.send_header('Pragma', 'no-cache')
                self.send_header('Expires', '0')
                self.end_headers()
                self.wfile.write(HTML_PAGE.encode('utf-8'))
                
            elif self.path == '/api/ranking':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                
                ranking = process_clans_ranking()
                self.wfile.write(json.dumps(ranking, ensure_ascii=False).encode('utf-8'))
                
            elif self.path.startswith('/api/clan/') and self.path.endswith('/daily-summary'):
                clan_tag = urllib.parse.unquote(self.path.split('/')[-2])
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                
                daily_summary = get_clan_daily_summary(clan_tag)
                self.wfile.write(json.dumps(daily_summary, ensure_ascii=False).encode('utf-8'))
                
            elif self.path.startswith('/api/clan/'):
                clan_tag = urllib.parse.unquote(self.path.split('/')[-1])
                
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                
                clan_data = get_clan_data(clan_tag)
                self.wfile.write(json.dumps(clan_data, ensure_ascii=False).encode('utf-8'))
                
            elif self.path == '/api/reset-daily':
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.send_header('Cache-Control', 'no-cache')
                self.end_headers()
                
                success = force_daily_reset()
                response = {'success': success, 'message': 'Reset completado' if success else 'Error en reset'}
                self.wfile.write(json.dumps(response, ensure_ascii=False).encode('utf-8'))
                
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'text/plain')
                self.end_headers()
                self.wfile.write(b'404 - Not Found')
                
        except Exception as e:
            print(f"Error en request handler: {e}")
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            error_response = {'error': str(e)}
            self.wfile.write(json.dumps(error_response).encode('utf-8'))

def check_port_availability(port):
    """Verifica si el puerto está disponible"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind(('', port))
            return True
        except OSError:
            return False

def find_available_port(start_port=8000):
    """Encuentra un puerto disponible empezando desde start_port"""
    port = start_port
    while port < start_port + 100:
        if check_port_availability(port):
            return port
        port += 1
    return None

def main():
    """Función principal del servidor - VERSIÓN PROTEGIDA"""
    global PORT
    
    print("Iniciando TOP REQ CLANS Server - VERSIÓN PROTEGIDA...")
    print("=" * 70)
    print("🔒 SISTEMA DE SEGURIDAD ACTIVADO:")
    print("   • Reset manual protegido con contraseña")
    print("   • Contraseña ofuscada en el código")
    print("   • Modal de autenticación")
    print("   • Acceso restringido a funciones administrativas")
    print("=" * 70)
    print("CARACTERÍSTICAS:")
    print("   • ✅ Interfaz completamente optimizada para móvil")
    print("   • ✅ Información consolidada eficientemente")
    print("   • ✅ Pestañas reorganizadas")
    print("   • ✅ Protección con contraseña")
    print("   • ✅ Reset automático 2-6 AM (Argentina)")
    print("   • ✅ Persistencia de datos automática")
    print("=" * 70)
    
    # Cargar estadísticas guardadas
    load_daily_donations()
    
    # Verificar disponibilidad del puerto
    if not check_port_availability(PORT):
        print(f"Puerto {PORT} ocupado, buscando puerto alternativo...")
        alt_port = find_available_port(PORT)
        if alt_port:
            PORT = alt_port
            print(f"Usando puerto alternativo: {PORT}")
        else:
            print("No se encontró puerto disponible")
            return
    
    # Inicializar hilos de trabajo
    print("Inicializando sistemas automáticos...")
    
    # Hilo para reset diario automático
    reset_thread = threading.Thread(target=daily_reset_worker, daemon=True)
    reset_thread.start()
    print("✅ Monitor de reset diario iniciado")
    
    # Hilo para respaldos automáticos
    backup_thread = threading.Thread(target=auto_backup_worker, daemon=True)
    backup_thread.start()
    print("✅ Sistema de respaldo automático iniciado")
    
    # Hilo para actualizaciones automáticas
    update_thread = threading.Thread(target=auto_update_worker, daemon=True)
    update_thread.start()
    print("✅ Actualizador automático iniciado")
    
    print("=" * 70)
    
    try:
        # Configurar y iniciar servidor HTTP
        with socketserver.TCPServer(("", PORT), RequestHandler) as httpd:
            httpd.allow_reuse_address = True
            
            # Obtener IP local
            hostname = socket.gethostname()
            local_ip = socket.gethostbyname(hostname)
            
            print(f"📱 Servidor protegido ejecutándose en:")
            print(f"   • Local: http://localhost:{PORT}")
            print(f"   • Red:   http://{local_ip}:{PORT}")
            print("=" * 70)
            print("🔒 SISTEMA DE SEGURIDAD:")
            print("   • 🔐 Reset manual requiere contraseña de administrador")
            print("   • 👤 Acceso seguro para usuarios no autorizados")
            print("   • 🛡️ Contraseña ofuscada en el código fuente")
            print("=" * 70)
            print("🎯 INSTRUCCIONES DE USO:")
            print("   • Usuarios normales: Solo pueden ver estadísticas")
            print("   • Administradores: Pueden hacer reset con contraseña")
            print("   • Contraseña: Contacta al administrador del sistema")
            print("=" * 70)
            print("Presiona Ctrl+C para detener el servidor")
            print("Estado: EJECUTÁNDOSE - VERSIÓN PROTEGIDA")
            
            # Hacer una actualización inicial
            print("\n📱 Cargando datos iniciales...")
            try:
                ranking = process_clans_ranking()
                print(f"✅ Datos cargados: {len(ranking)} clanes")
            except Exception as e:
                print(f"⚠️ Error en carga inicial: {e}")
            
            print("\n🎯 Servidor listo - Accede desde cualquier dispositivo!")
            print("VERSIÓN PROTEGIDA - ACCESO SEGURO GARANTIZADO")
            
            # Iniciar servidor
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n⚠️ Cerrando servidor...")
        
        # Guardar datos antes de cerrar
        print("💾 Guardando datos finales...")
        if save_daily_donations():
            print("✅ Datos guardados exitosamente")
        else:
            print("❌ Error guardando datos finales")
            
        print("📚 Servidor cerrado correctamente!")
        
    except Exception as e:
        print(f"💥 Error fatal del servidor: {e}")
        
        # Intentar guardar datos de emergencia
        try:
            save_daily_donations()
            print("💾 Datos de emergencia guardados")
        except:
            print("❌ No se pudieron guardar datos de emergencia")

if __name__ == "__main__":
    main()
