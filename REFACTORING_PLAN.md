# Refactoring Plan: PlexCore Aufteilung

## Aktuelle Situation
- `plex_core.py`: **1630 Zeilen** - zu groß, viele Verantwortlichkeiten
- 3 Klassen: `StreamDetailsView`, `KillStreamModal`, `PlexCore`
- Viele verschiedene Verantwortlichkeiten in einer Datei

## Analyse der Verantwortlichkeiten

### 1. **Config Management** (~100 Zeilen)
- `_auto_migrate_config()` - Auto-Migration JSON → YAML
- `_load_config()` - Config laden
- `_load_user_mapping()` - User Mapping laden
- `_load_message_id()` / `_save_message_id()` - Message ID Management

### 2. **Plex Connection & Server Info** (~150 Zeilen)
- `connect_to_plex()` - Plex Verbindung
- `get_server_info()` - Server Status
- `calculate_uptime()` - Uptime Berechnung
- `get_offline_info()` - Offline Status

### 3. **Library Management** (~100 Zeilen)
- `get_library_stats()` - Library Statistiken
- `_build_section_stats()` - Section Stats bauen
- Caching Logic

### 4. **Stream Processing** (~400 Zeilen)
- `get_active_streams()` - Aktive Streams
- `format_stream_info()` - Stream Formatierung
- `_format_time()` - Zeit Formatierung
- `_get_formatted_title()` - Titel Formatierung
- `get_transcoding_details()` - Transcoding Details
- `get_stream_thumbnail_file()` - Thumbnail Download

### 5. **Tautulli Integration** (~150 Zeilen)
- `fetch_tautulli_session()` - Tautulli Session Daten
- `get_tautulli_thumbnail()` - Tautulli Thumbnail

### 6. **Discord UI Components** (~750 Zeilen)
- `StreamDetailsView` - Stream Detail Buttons/View
- `KillStreamModal` - Kill Stream Modal

### 7. **Dashboard Management** (~300 Zeilen)
- `update_dashboard()` - Dashboard Update Task
- `create_dashboard_embed()` - Embed Erstellung
- `_add_embed_fields()` - Embed Fields hinzufügen
- `_update_dashboard_message()` - Message Update
- `_calculate_total_size()` - Download Size Berechnung

### 8. **Status Management** (~50 Zeilen)
- `update_status()` - Bot Status Update Task

## Vorschlag: Aufteilung in Module

### Struktur:
```
cogs/
├── plex_core.py          # Haupt-Cog (Orchestrator, ~200 Zeilen)
├── config_manager.py     # Config Management (~150 Zeilen)
├── plex_connection.py    # Plex Connection & Server Info (~200 Zeilen)
├── library_manager.py    # Library Stats & Management (~150 Zeilen)
├── stream_processor.py   # Stream Formatierung & Processing (~400 Zeilen)
├── tautulli_client.py    # Tautulli Integration (~200 Zeilen)
├── dashboard_builder.py  # Dashboard Embed Building (~300 Zeilen)
└── ui/
    ├── __init__.py
    ├── stream_details_view.py  # StreamDetailsView (~550 Zeilen)
    └── kill_stream_modal.py     # KillStreamModal (~200 Zeilen)
```

## Detaillierter Plan

### 1. `config_manager.py`
**Verantwortlichkeiten:**
- Auto-Migration (JSON → YAML)
- Config Loading (YAML/JSON fallback)
- User Mapping Loading
- Message ID Management

**Klassen:**
- `ConfigManager` - Singleton oder statische Methoden

**Abhängigkeiten:**
- Keine direkten Bot/Cog Abhängigkeiten
- Kann von überall verwendet werden

### 2. `plex_connection.py`
**Verantwortlichkeiten:**
- Plex Server Verbindung
- Server Status Abfrage
- Uptime Berechnung
- Offline Status Handling

**Klassen:**
- `PlexConnection` - Managed Plex Connection

**Abhängigkeiten:**
- Config (für URLs/Tokens)
- Logger

### 3. `library_manager.py`
**Verantwortlichkeiten:**
- Library Statistiken
- Section Stats Building
- Caching Logic

**Klassen:**
- `LibraryManager` - Library Stats Management

**Abhängigkeiten:**
- PlexConnection
- Config

### 4. `stream_processor.py`
**Verantwortlichkeiten:**
- Stream Formatierung
- Stream Info Extraction
- Transcoding Details
- Thumbnail Handling
- Time/Title Formatierung

**Klassen:**
- `StreamProcessor` - Stream Processing Logic

**Abhängigkeiten:**
- PlexConnection
- LibraryManager (für Emojis)
- Config (User Mapping)

### 5. `tautulli_client.py`
**Verantwortlichkeiten:**
- Tautulli API Calls
- Session Data Fetching
- Thumbnail Fetching

**Klassen:**
- `TautulliClient` - Tautulli API Client

**Abhängigkeiten:**
- Config (URLs/Keys)
- aiohttp

### 6. `dashboard_builder.py`
**Verantwortlichkeiten:**
- Embed Erstellung
- Field Management
- Message Update Logic
- Download Size Calculation

**Klassen:**
- `DashboardBuilder` - Embed Building

**Abhängigkeiten:**
- Discord.py
- StreamProcessor
- LibraryManager
- SABnzbd/Uptime Cogs (via Bot)

### 7. `ui/stream_details_view.py`
**Verantwortlichkeiten:**
- Stream Detail Buttons
- Stream Detail Embeds
- Button Callbacks

**Klassen:**
- `StreamDetailsView` - Discord UI View

**Abhängigkeiten:**
- PlexCore (für Datenzugriff)
- TautulliClient
- StreamProcessor

### 8. `ui/kill_stream_modal.py`
**Verantwortlichkeiten:**
- Kill Stream Modal
- Stream Killing Logic

**Klassen:**
- `KillStreamModal` - Discord UI Modal

**Abhängigkeiten:**
- PlexCore (für Tautulli)
- TautulliClient

### 9. `plex_core.py` (Refactored)
**Verantwortlichkeiten:**
- Orchestrierung aller Module
- Task Management (update_status, update_dashboard)
- Bot Integration
- Cog Setup

**Klassen:**
- `PlexCore` - Haupt-Cog (schlank, ~200 Zeilen)

**Abhängigkeiten:**
- Alle anderen Module
- Discord Bot

## Vorteile dieser Struktur

1. **Separation of Concerns**: Jedes Modul hat eine klare Verantwortlichkeit
2. **Testbarkeit**: Module können einzeln getestet werden
3. **Wartbarkeit**: Änderungen sind lokalisiert
4. **Erweiterbarkeit**: Neue Features können einfach hinzugefügt werden
5. **Wiederverwendbarkeit**: Module können in anderen Cogs verwendet werden

## Migration Strategy

### Phase 1: Vorbereitung
1. ✅ Aktuellen Stand committen
2. Backup erstellen
3. Tests dokumentieren (falls vorhanden)

### Phase 2: Module erstellen (Bottom-Up)
1. `config_manager.py` - Keine Bot-Abhängigkeiten
2. `plex_connection.py` - Basis für alles andere
3. `library_manager.py` - Nutzt PlexConnection
4. `stream_processor.py` - Nutzt LibraryManager
5. `tautulli_client.py` - Unabhängig
6. `dashboard_builder.py` - Nutzt alle vorherigen
7. `ui/` Module - Nutzen PlexCore

### Phase 3: Refactoring
1. `plex_core.py` refactoren
2. Imports anpassen
3. Tests durchführen

### Phase 4: Cleanup
1. Alte Code-Kommentare entfernen
2. Type Hints verbessern
3. Dokumentation aktualisieren

## Zukünftige Integrationen einplanen

### Mögliche Erweiterungen:
- **Radarr/Sonarr Integration** - Kann `config_manager` nutzen
- **Overseerr Integration** - Kann `plex_connection` nutzen
- **Webhook Support** - Kann `dashboard_builder` erweitern
- **Multiple Plex Servers** - `plex_connection` kann erweitert werden
- **Analytics** - Neues Modul `analytics.py`

### Design-Prinzipien:
- **Dependency Injection**: Module bekommen Abhängigkeiten über Constructor
- **Interface Segregation**: Kleine, fokussierte Interfaces
- **Single Responsibility**: Jedes Modul eine klare Aufgabe
- **Open/Closed**: Erweiterbar ohne Modifikation

## Risiken & Mitigation

### Risiko 1: Breaking Changes
- **Mitigation**: Schrittweise Migration, Backward Compatibility

### Risiko 2: Zirkuläre Abhängigkeiten
- **Mitigation**: Klare Dependency-Hierarchie, Interfaces

### Risiko 3: Performance
- **Mitigation**: Profiling, Caching beibehalten

## Nächste Schritte

1. ✅ Plan erstellen
2. ⏳ Plan reviewen
3. ⏳ Phase 1: Committen
4. ⏳ Phase 2: Module erstellen
5. ⏳ Phase 3: Refactoring
6. ⏳ Phase 4: Cleanup
