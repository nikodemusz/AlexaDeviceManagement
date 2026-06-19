# Standalone Alexa Test App

Diese Test-App ist bewusst **keine Home-Assistant-App** und kein HA-OS-Add-on. Sie läuft als normaler aiohttp-Webserver und dient nur dazu, den Amazon/Alexa-App-Loginpfad ohne HA-Ingress, Panel-Iframe und HA-URL-Umschreibung zu prüfen.

## Zweck

Mit dieser App lässt sich testen, ob der Weg grundsätzlich funktioniert:

```text
Browser -> /auth/login -> /auth/alexa-app/start -> lokaler Amazon-Proxy -> Amazon Login -> /ap/maplanding -> lokale Session-Datei
```

Die App verwendet ausschließlich:

```text
/auth/alexa-app/...
```

Es werden keine `/auth/alexa-openhab/...` URLs erzeugt.

## Start lokal

Vom Repository-Root aus:

```bash
cd standalone_alexa_app
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
ALEXA_TEST_DATA_DIR="$PWD/data" python app.py
```

Dann im Browser öffnen:

```text
http://localhost:8099/
```

Für einen Test mit explizitem deutschen Alexa-Host:

```text
http://localhost:8099/?host=alexa.amazon.de
```

## Status prüfen

Nach erfolgreichem Login:

```text
http://localhost:8099/api/session
```

Die Session wird unterhalb von `standalone_alexa_app/data/` abgelegt, wenn die App wie oben gestartet wurde.

## Hinweise

- Diese App ist nur ein Testwerkzeug.
- Cookies, CSRF und Refresh-Token werden lokal gespeichert.
- Nicht öffentlich ins Internet stellen.
- Die App nutzt den vorhandenen Login-Helfer aus dem Add-on, patcht ihn zur Laufzeit aber auf reine HA-App-Routen um.
