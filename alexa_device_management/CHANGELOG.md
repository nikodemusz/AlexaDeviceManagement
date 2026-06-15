# Changelog

## 0.8.14

- **Bugfix**: `server_app_entry.py` ersetzt die komplette `setup_routes()`-Funktion des Alexa-Login-Helfers jetzt robust zur Laufzeit. Dadurch können Dockerfile-Build-Patches und Runtime-Patches keine doppelte Wildcard-Route mehr erzeugen.
- **Bugfix**: Startabbruch durch doppelte Registrierung von `/auth/alexa-app/{tail:.*}` wurde beseitigt. Die Oberfläche ist dadurch wieder erreichbar.
- **Release Notes**: Diese Version korrigiert den Add-on-Start selbst. Ursache war eine Kombination aus Kompatibilitätsroute `/auth/alexa-openhab/...` und späterer Runtime-Normalisierung auf `/auth/alexa-app/...`.

## 0.8.13

- **Bugfix**: Alexa-Web-Login-Routen werden jetzt idempotent registriert. Dadurch startet das Add-on auch dann sauber, wenn `server.py` die Route bereits registriert hat und `server_patched.py` sie anschließend erneut einbinden würde.
- **Bugfix**: Der Startfehler `Added route will never be executed, method * is already registered` wurde beseitigt.
- **Release Notes**: Diese Version stabilisiert den HA-OS-Updatepfad nach den Login-Routen-Korrekturen und verhindert doppelte Wildcard-Registrierung für `/auth/alexa-openhab/...`.

## 0.8.12

- **Bugfix**: Der Runtime-Patch in `server_app_entry.py` sucht den Alexa-Web-Login-Handler jetzt robuster und ist nicht mehr von einem exakt formatierten Quelltextblock abhängig.
- **Bugfix**: Der Startfehler `Could not patch handle_alexa_web_login redirect handler` wurde beseitigt.
- **Release Notes**: Diese Version macht den Start-Wrapper toleranter gegenüber bereits korrigierten oder leicht anders formatierten Login-Handlern.

## 0.8.11

- **Bugfix**: Der Build-Patch registriert den Alexa-Web-Login-Proxy jetzt auch dann, wenn der HA-App-Runner direkt `server.py` startet statt den gepatchten Entry-Wrapper zu verwenden.
- **Bugfix**: `/auth/login` startet jetzt den Alexa-Web-Session-Login-Assistenten statt des alten Amazon-LWA/OAuth-Flows.
- **Bugfix**: Die Route `/auth/alexa-openhab/start` wird dadurch im direkten `server.py`-Startpfad verfügbar und liefert nicht mehr `404: Not Found`.
- **Release Notes**: Diese Version korrigiert den Login-Start über Home-Assistant-Ingress, damit das Amazon/Alexa-Web-Login-Frontend wieder erreicht wird.

## 0.8.10

- **Bugfix**: Die Web-UI startet den Alexa-Login jetzt per direkter Browser-Navigation zu `/auth/login` statt über `fetch()` mit anschließendem `window.open(...)`.
- **Bugfix**: Dadurch bleibt der Login-Start ein echter Benutzer-Klick und wird von iOS/Safari/Home-Assistant-Ingress nicht mehr als verzögertes Popup behandelt.
- **Release Notes**: Diese Version vereinfacht den Loginpfad. Der Server übernimmt die komplette Redirect-Kette von `/auth/login` über `/auth/alexa-app/start` bis zur Amazon-Loginseite.

## 0.8.9

- **Bugfix**: Aktive Alexa-Login-Route von der irreführenden OpenHAB-Bezeichnung auf `/auth/alexa-app/...` umgestellt.
- **Bugfix**: Neuer Start-Entry `server_app_entry.py` verwendet host-aware Forwarding, damit Amazon-Login-Pfade den Zielhost enthalten können, z. B. `/FORWARD/www.amazon.de/...`.
- **Release Notes**: Diese Version bereinigt die aktive Login-Route und korrigiert die Weiterleitung für Amazon-App-Login-Pfade mit explizitem Zielhost.

## 0.8.8

- **Bugfix**: Der Alexa-Web-Login erzeugt die App-Registrierungs-URL jetzt abhängig von der Amazon-Domain. Für `amazon.de` wird dadurch die deutsche Amazon-Domain und `de_DE` als Sprache verwendet.
- **Release Notes**: Diese Version korrigiert eine fehlerhafte Amazon-Ziel-URL, die trotz korrektem Home-Assistant-Ingress-Proxy auf der Amazon-Seite "Suchst du etwas?" landen konnte.

## 0.8.7

- **Bugfix**: Der Alexa-Web-Login-Proxy kodiert OpenID-Query-Parameter vor dem Weiterleiten an Amazon explizit erneut mit `urllib.parse.urlencode(...)`. Das ist robuster, wenn Home Assistant Ingress oder aiohttp den Query-String bereits dekodiert an das Add-on übergeben.
- **Release Notes**: Diese Version korrigiert weiterhin den Amazon-404-Fehler "Suchst du etwas?" beim App-Registrierungs-Login, indem verschachtelte URL-Parameter wie `openid.return_to` wieder Amazon-kompatibel kodiert werden.

## 0.8.6

- **Bugfix**: Der Alexa-Web-Login-Proxy leitet Amazon-OpenID-Parameter jetzt mit dem rohen Query-String aus `request.raw_path` weiter. Dadurch werden verschachtelte URL-Parameter wie `openid.return_to` nicht mehr vor dem Weiterreichen an Amazon dekodiert.
- **Release Notes**: Diese Version korrigiert die zweite Stelle im Ingress-Proxy, an der Amazon-Login-URLs beschädigt werden konnten und dadurch auf der Amazon-404-Seite "Suchst du etwas?" landeten.

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
