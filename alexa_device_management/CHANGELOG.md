# Changelog

## 0.8.5

- **Bugfix**: Alexa-Web-Login erhält den Amazon-OpenID-Query-String jetzt URL-kodiert. Dadurch landet der Login nicht mehr auf einer Amazon-404-Seite wie "Suchst du etwas?".
- **Release Notes**: Diese Version korrigiert den Weiterleitungsaufbau im Home-Assistant-Ingress-Proxy für den Amazon-App-Registrierungs-Login.

## 0.8.4

- **Bugfix**: Startfehler durch fehlende öffnende Triple-Quote in `alexa_openhab_login.py` abgefangen. Der sichere Entry-Wrapper lädt das Login-Modul jetzt mit einer kleinen Quelltext-Korrektur vor.
- **Bugfix**: Startfehler durch ein versehentliches `)f` in `server_patched.py` wird weiterhin beim Start korrigiert.

## 0.8.3

- **Bugfix**: Add-on-Startskript auf den sicheren `server_patched_entry.py` Entry-Wrapper umgestellt, damit der Alexa-Web-Login trotz kleiner Syntax-Artefakte startbar bleibt.

## 0.8.2

- **Wartung**: Add-on-Version erhöht, damit Home Assistant Repository-Updates zuverlässig erkennt.

## 0.8.1

- **Wartung**: Add-on-Version erhöht, damit Home Assistant die neue Build-Version anbietet.

## 0.8.0
- **Feature** Umsetellen auf Amazon Web Login

## 0.7.0

- **Feature**: Neue Info-Ansicht in der Web-UI ergänzt. Sie zeigt nun die
  installierte App-Version, Alexa-Region, Verbindungsstatus und die Anzahl der
  geladenen Geräte.
- **Feature**: Der aktuell angemeldete Amazon-Benutzer wird in der Übersicht
  angezeigt, damit sofort ersichtlich ist, welches Konto verbunden ist.
- **Verbesserung**: Für neue Logins wird zusätzlich der Amazon-Profil-Scope
  angefordert, damit Kontoinformationen zuverlässig geladen und gespeichert
  werden können.

## 0.6.8

- **Bugfix**: Geräteabruf robuster gemacht, damit im Amazon-Konto registrierte
  Homeautomation-Geräte zuverlässig geladen werden. Es werden jetzt beide Alexa
  Endpoints (`GET /v2/devices` und `GET /v2/appliances`) abgefragt.
- **Verbesserung**: Geräte-Normalisierung erweitert, damit unterschiedliche
  Antwortformate der Alexa API (z.B. `appliances`/`devices`, `actions`/`capabilities`)
  korrekt in der UI dargestellt werden.

## 0.6.7

- **Feature**: Vollständige Auflistung der Homeautomation-Geräte über die Alexa
  API (`GET /v2/appliances`) mit Pagination (`nextToken`), damit alle Geräte
  geladen werden.
- **Verbesserung**: Amazon Appliance-Daten werden für die UI normalisiert
  (Name, Typ, Erreichbarkeit, Raum, Fähigkeiten), damit die Geräteliste
  konsistent dargestellt wird.

## 0.6.6

- **Bugfix**: Amazon Login wird im Home Assistant Ingress nicht mehr im Iframe
  geöffnet, sondern in einem neuen Tab. Dadurch greift `X-Frame-Options: DENY`
  der Amazon-Loginseite nicht mehr.
- **Verbesserung**: Popup-Blocker-Erkennung mit klickbarem Fallback-Link ergänzt.
- **Verbesserung**: Hinweis für Benutzer ergänzt, dass die Amazon-Anmeldeseite in
  einem neuen Tab geöffnet wurde.

## 0.6.5

- **Bugfix**: EU OAuth-Autorisierungs-Endpoint aktualisiert. Amazon leitet
  `www.amazon.co.uk/ap/oa` nun auf `eu.account.amazon.com` weiter, welches
  die Verbindung ablehnte. Der Endpoint wurde direkt auf
  `https://eu.account.amazon.com/ap/oa` geändert.

## 0.6.4

- **Bugfix**: OAuth redirect_uri verwendete das Schema aus dem `X-Forwarded-Proto`
  Header, welcher in manchen Konfigurationen `http` statt `https` lieferte.
  Die redirect_uri wird nun immer mit `https://` generiert, da Amazon LWA
  ausschließlich HTTPS-URLs akzeptiert.

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
- Configuration status shown in the UI (configured vs. not configured).

## 0.2.0

- Add Home Assistant App Installer support for Alexa Device Management.
