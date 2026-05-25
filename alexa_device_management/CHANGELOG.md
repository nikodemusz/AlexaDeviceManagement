# Changelog

## 0.6.3

- **Bugfix**: OAuth redirect_uri war nur ein relativer Pfad (z.B.
  `/api/hassio_ingress/.../auth/callback`) statt einer vollständigen absoluten
  URL (`https://domain.de/api/hassio_ingress/.../auth/callback`). Amazon LWA
  verlangt eine absolute URL und lehnte die relative URI mit dem Fehler
  "lwa-invalid-parameter-bad-redirect-uri-vendor" (400 Bad Request) ab.
  Die redirect_uri wird nun korrekt aus den Proxy-Headern (X-Forwarded-Proto,
  X-Forwarded-Host) zusammengesetzt.

## 0.6.2

- **Bugfix**: OAuth-Scope korrigiert – `alexa::all` (doppelter Doppelpunkt) war kein
  gültiger Amazon LWA Scope und führte zu einem 400 Bad Request Fehler
  ("lwa-invalid-parameter-bad-scope"). Korrekter Scope ist `alexa:all` (einfacher
  Doppelpunkt). Dieser Scope muss im Amazon Developer Console Security Profile
  unter "Allowed Scopes" aktiviert sein.

## 0.6.1

- **Bugfix**: OAuth-Scope korrigiert – `alexa::devices:all:read alexa::devices:all:write`
  war kein gültiger Amazon LWA Scope und führte zu einem 400 Bad Request Fehler.
  Ersetzt durch den korrekten Scope `alexa::all`.

## 0.6.0

- **Feature**: Integrierter OAuth2-Login direkt in der App – kein manuelles Kopieren
  eines Refresh-Tokens mehr nötig! Der Benutzer klickt "Mit Amazon anmelden",
  wird zu Amazon weitergeleitet, meldet sich dort an, und der Refresh-Token wird
  automatisch in der App gespeichert.
- **Feature**: Login/Logout UI mit Anleitung zur Einrichtung (Redirect-URI Anzeige).
- **Feature**: OAuth-Tokens werden persistent in `/data/oauth_tokens.json` gespeichert
  (unabhängig von der Add-on-Konfiguration).
- **Feature**: Callback-Seite mit Erfolgs-/Fehlermeldung nach Amazon-Login.
- **Verbesserung**: `refresh_token` in der Add-on-Konfiguration ist nun optional –
  der in-App Login-Flow wird bevorzugt.
- **Verbesserung**: CSRF-Schutz im OAuth-Flow via State-Parameter.

## 0.5.0

- **Feature**: Automatischer OAuth Token-Refresh im Hintergrund – das Access-Token
  wird automatisch 5 Minuten vor Ablauf erneuert, ohne dass ein API-Aufruf nötig ist.
- **Feature**: Persistenter Token-Cache – überlebt Add-on-Neustarts (gespeichert in `/data/token_cache.json`).
- **Feature**: Neuer API-Endpoint `GET /api/token-refresh-status` zeigt den Status des
  automatischen Refresh-Prozesses (aktiv, nächster Refresh, Fehler).
- **Feature**: UI-Statusanzeige für den automatischen Token-Refresh in der Toolbar.

## 0.4.0

- **Breaking**: Removed HA custom integration (`custom_components`). This is now a
  pure standalone HA OS add-on/app with its own web UI – no HA integration required.
- Removed `hacs.json` and all integration code (config_flow, websocket_api, panel, etc.)
- Removed `map: config:rw` – the app no longer writes to the HA config directory.
- The app is a self-contained web application accessible via HA ingress sidebar panel.

## 0.3.0

- Add Amazon Alexa authentication configuration (client_id, client_secret, refresh_token, region).
- Add ingress web UI to display Alexa devices.
- Web server powered by aiohttp serves a device overview panel.
- Configuration status shown in the UI (configured vs. not configured).

## 0.2.0

- Add Home Assistant App Installer support for Alexa Device Management.
