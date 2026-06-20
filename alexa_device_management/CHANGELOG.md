# Changelog

## 0.8.21

- **Cleanup**: Alte LWA-/OAuth-Konfigurationswerte aus `config.yaml` entfernt: `client_id`, `client_secret`, `refresh_token`, `alexa_cookie`, `alexa_csrf`.
- **Cleanup**: `AUTHENTICATION.md` ersetzt. Die Dokumentation beschreibt jetzt den geplanten Cookie-/Proxy-Login nach openHAB-Vorbild statt des verworfenen Amazon-Developer-Console-/OAuth-Wegs.
- **Cleanup**: `server.py` enthält keinen alten Login-with-Amazon-/Token-Refresh-Code mehr, sondern nur noch einen Legacy-Shim auf den aktuellen Startpfad.
- **Hinweis**: Der eigentliche Cookie-Proxy-Login ist damit noch nicht fertig implementiert. Diese Version bereinigt bewusst die Projektbasis, damit die nächste Implementierung nicht mehr vom falschen LWA-Pfad überlagert wird.

## 0.8.18

- **Bugfix**: Der Alexa-App-Login erzwingt für `openid.ns.oa2` wieder Amazons kanonischen Namespace `http://www.amazon.com/ap/ext/oauth/2`, auch wenn der eigentliche Login über `www.amazon.de` läuft.
- **Bugfix**: Dadurch landet der Login-Proxy nicht mehr auf Amazons generischer 404-Seite „Suchst du etwas?“, wenn `/auth/alexa-app/FORWARD/www.amazon.de/ap/signin?...` über Home-Assistant-Ingress geöffnet wird.
- **Release Notes**: Diese Version korrigiert die OpenID-Parametererzeugung für den regionalen Amazon-Login. Die Retail-Domain bleibt deutsch, nur der OpenID-Extension-Namespace bleibt Amazon-kompatibel global.

## 0.8.15

- **Bugfix**: Der Alexa-Web/App-Login ist jetzt strikt von der alten LWA/API-Key-Konfiguration (`client_id`, `client_secret`, `refresh_token`) getrennt.
- **Bugfix**: Eine vorhandene alte LWA-Konfiguration markiert die App nicht mehr als „verbunden“ und versteckt dadurch nicht mehr den Alexa-Web-Login.
- **Bugfix**: Ohne gültige Alexa-Web-Session wird nicht mehr auf den alten Alexa-API-Tokenpfad zurückgefallen. Stattdessen meldet die API klar, dass der Alexa-Web-Login verbunden werden muss.
- **Release Notes**: Diese Version korrigiert den Konflikt zwischen der früheren Amazon-LWA-Loginmethode und dem neuen Alexa-Web/App-Login. Der HA-OS-Updatepfad kann dadurch alte Konfigurationswerte behalten, ohne den neuen Login zu blockieren.

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

- **Feature**: Neue Info-Ansicht in der Web-UI ergänzt.

## 0.6.8 und älter

- Frühere Experimente mit OAuth/LWA und Alexa-API-Endpunkten. Diese Historie ist für die neue Cookie-/Proxy-Richtung nicht mehr maßgeblich.
