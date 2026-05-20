# AlexaDeviceManagement

Grundgerüst einer Home-Assistant-Integration, um Amazon-Alexa-Geräte über eine eigene GUI zu verwalten.

## Struktur

```text
custom_components/alexa_device_management/
├── __init__.py
├── config_flow.py
├── const.py
├── manager.py
├── manifest.json
├── panel.py
├── services.yaml
└── www/
    └── alexa-device-management.js
```

## Enthalten

- Home-Assistant Custom Integration (`alexa_device_management`)
- Konfigurationsfluss (UI)
- Platzhalter-Service-Definitionen für Geräte auflisten/löschen
- Eigenes Panel mit einfacher GUI als Web Component

## Nächste Schritte

- Alexa API-Anbindung in `manager.py` implementieren (OAuth/Token-Handling)
- Service-Handler registrieren und mit `manager.py` verbinden
- GUI erweitern (Geräteliste, Lösch-Dialog, Statusmeldungen)
- Optional: Tests für Service- und API-Logik ergänzen
