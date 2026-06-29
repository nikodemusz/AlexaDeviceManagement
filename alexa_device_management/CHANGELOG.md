# Changelog

## 1.1.14

- **Debug**: Zweiter Button „💥 Delete-Probe (DELETE!)" in der Debug-Seite — ruft `/api/delete-probe?id=…&delete=1` auf (mit korrektem `&`). Bisher musste der User die URL manuell anpassen, was dazu führte dass `?delete=1` fälschlicherweise an die UUID angehängt wurde.

## 1.1.13

- **Bugfix**: Delete für reine v3-Smart-Home-Geräte (openHAB3, keine `legacyAppliance`) probiert jetzt 5 Kandidaten-Endpoints in Reihenfolge und stoppt beim ersten erfolgreichen 2xx: `/api/phoenix/entity/`, `/api/smarthome/v2/entities/`, `/api/smarthome/v1/presentation/entities/`, `/api/phoenix/appliance/`, `/api/phoenix/registration/`. Phoenix v2 behandelte DELETE mit unbekannter UUID als No-Op (immer 200), deshalb galt das Gerät als gelöscht aber tauchte beim Neuladen wieder auf.
- **Debug**: `delete_probe` GET-Proben auf alle 4 v3-Kandidaten-Endpoints hinzugefügt (Abschnitt `v3_get_probes`).
- **Debug**: `delete_probe?id=…&delete=1` versucht jetzt DELETE auf alle 5 Kandidaten und prüft danach ob das Gerät noch in behaviors/entities vorhanden ist (`device_still_exists_after_delete`).

## 1.1.12

- **Bugfix**: Delete für Smart-Home-Geräte (z.B. openHAB) verwendet jetzt die `legacyAppliance.applianceId` (Format `AAA_…`) als Phoenix-Schlüssel, wenn vorhanden — statt der UUID aus der behaviors/entities-API. Phoenix (Alexa Smart Home v2) kennt die v3-UUIDs nicht und hat DELETE deshalb als No-Op behandelt.

## 1.1.11

- **Debug**: Delete-Probe erweitert — zeigt jetzt alle rohen Felder aus behaviors/entities (inkl. `legacyAppliance`), testet GET auf drei URL-Formate (`/api/phoenix/appliance/`, `/api/smarthome/appliance/`, `amzn1.alexa.endpoint.`-Präfix) und listet die ersten Einträge von `/api/phoenix/appliance` (ohne ID) um das interne ID-Format zu erkennen.

## 1.1.10

- **Debug**: Neuer Endpoint `/api/delete-probe?id={uuid}` und Button „🔬 Delete-Probe" in der Debug-Seite. Zeigt: (1) Was Phoenix über das Gerät an dieser UUID weiß (GET), (2) Was der DELETE-Aufruf tatsächlich zurückgibt (Status + Body), (3) Ob das Gerät danach noch in der behaviors/entities-Liste vorhanden ist — damit kann man diagnostizieren ob die Löschung auf API-Ebene wirkt oder der HA-Skill das Gerät sofort wieder hinzufügt.

## 1.1.9

- **Bugfix**: Nach dem Löschen eines Geräts funktioniert die Filterung wieder korrekt. Ursache war ein Index-Versatz: wenn ein Eintrag aus `_allDevices` entfernt wurde, verschoben sich alle Indizes, `applyFilters()` las danach falsche Geräte. Behoben durch seriell-basiertes Lookup (`_deviceBySerial`-Map) statt Array-Index.
- **Bugfix**: Fehlermeldungen beim Bulk-Delete zeigen jetzt Gerätename und vollständigen Fehlertext pro Gerät (z.B. `• Echo Wohnzimmer: HTTP 403: …`). Zeilenumbrüche werden im Alert korrekt dargestellt.
- **Bugfix**: Gerätename wird jetzt im Request und Response mitgeschickt, damit Fehlernachrichten nachvollziehbar sind.

## 1.1.8

- **Bugfix**: Delete für Smart-Home-Geräte verwendet jetzt den korrekten Endpoint `DELETE /api/phoenix/appliance/{id}` (ohne `/v1/`). Der `/v1/`-Pfad ist veraltet und lieferte immer HTTP 400 zurück.

## 1.1.7

- **Bugfix**: Delete für Smart-Home-Geräte sendet `Content-Type: application/json` jetzt nur noch wenn auch ein Request-Body vorhanden ist — leere `Content-Type`-Header haben die Phoenix-API mit HTTP 400 abbrechen lassen.
- **Bugfix**: Delete probiert jetzt 4 Varianten in Reihenfolge: Phoenix-Endpoints jeweils ohne Body und mit JSON-Body `{"entityId": ..., "entityType": "APPLIANCE"}`, damit alle möglichen API-Erwartungen abgedeckt werden.
  - `DELETE /api/phoenix/v1/deviceTyping/{id}` (kein Body)
  - `DELETE /api/phoenix/v1/appliance/{id}` (kein Body)
  - `DELETE /api/phoenix/v1/deviceTyping/{id}` (mit JSON-Body)
  - `DELETE /api/phoenix/v1/appliance/{id}` (mit JSON-Body)

## 1.1.6

- **Bugfix**: Delete probiert jetzt 4 Endpoints in Reihenfolge und meldet bei Misserfolg den genauen HTTP-Status jedes Versuchs — hilft den richtigen Endpoint zu identifizieren.
  - `DELETE /api/behaviors/entities/{id}?skillId=amzn1.ask.1p.smarthome`
  - `DELETE /api/behaviors/entities/{id}`
  - `DELETE /api/phoenix/v1/deviceTyping/{id}`
  - `DELETE /api/phoenix/v1/appliance/{id}`

## 1.1.5

- **UX**: Debug-Seite komplett für Mobile überarbeitet — keine feste Seitenleiste mehr, Endpunkt-Buttons wrappen als Kacheln, Output-Bereich scrollt vollständig.
- **Feature**: „📋 Kopieren"-Button in der Debug-Seite kopiert die komplette JSON-Antwort in die Zwischenablage.

## 1.1.4

- **Bugfix**: Delete für Smart-Home-Geräte versucht jetzt zuerst `/api/behaviors/entities/{entityId}` (gleicher Namespace wie Geräteabruf), fällt auf `/api/phoenix/v1/appliance/{applianceId}` zurück wenn der erste Versuch fehlschlägt.
- **Debug**: `/api/devices-debug` zeigt jetzt alle ID-Felder (`id`, `entityId`, `applianceId`, `legacyAppliance.applianceId`) für die ersten 5 Smart-Home-Geräte zur Diagnose.

## 1.1.3

- **Bugfix**: Delete für Smart-Home-Geräte verwendet jetzt die `legacyAppliance.applianceId` statt der `entityId` — die Phoenix-API erwartet das klassische Appliance-Format, nicht die Behaviors-Entity-ID.
- **Bugfix**: Geräte-IDs werden beim DELETE-Aufruf URL-kodiert (behebt HTTP 400 bei IDs mit Sonderzeichen).

## 1.1.2

- **Bugfix**: Delete-Fehler zeigen jetzt den echten HTTP-Status-Code und Alexa-API-Antworttext an (statt nur „Bad Gateway").

## 1.1.1

- **Bugfix**: „Alle auswählen"-Checkbox berücksichtigt jetzt aktive Filter — bei aktivem Filter werden nur die sichtbaren Geräte selektiert, nicht alle. Der Checkbox-Status (checked / indeterminate) wird nach jedem Filterwechsel neu berechnet.

## 1.1.0

- **Feature**: Bulk-Delete — ausgewählte Geräte können gemeinsam gelöscht werden.
  - Sobald mindestens ein Gerät per Checkbox selektiert ist, erscheint der Button „🗑 Auswahl löschen" in der Tabellen-Toolbar.
  - Ein Bestätigungs-Dialog listet alle betroffenen Geräte auf, bevor die Aktion ausgeführt wird.
  - Echo-Geräte werden über `/api/devices-v2/device/{serial}` entfernt, Smart-Home-Geräte über `/api/phoenix/v1/appliance/{entityId}`.
  - Erfolgreich gelöschte Geräte verschwinden sofort aus der Tabelle; Fehler werden pro Gerät gemeldet.

## 1.0.0

- **Feature**: Filterzeile in der Gerätetabelle. Jede Spalte ist filterbar:
  - **Skill / Connector**: Dropdown mit allen vorhandenen Werten (distinct) — z.B. nur „Home Assistant" oder „openHAB Skill" anzeigen
  - **Typ**, **Raum**, **Quelle**: Dropdown mit distinct-Werten
  - **Online-Status**: Dropdown (Alle / Online / Offline)
  - **Name**, **Hersteller**: Freitextfilter
- Geräte-Counter zeigt an wie viele Geräte gefiltert sichtbar sind (z.B. „42 von 791 Geräten")

## 0.9.9

- **Bugfix**: Sidebar-Icon in Home Assistant wird jetzt korrekt angezeigt. `mdi:amazon-alexa` war in manchen HA-Versionen nicht verfügbar — ersetzt durch `mdi:speaker` (Lautsprecher-Icon, immer verfügbar).

## 0.9.8

- **Bugfix**: Skill/Connector-Feld zeigt jetzt korrekt den Connector-Namen (z.B. „Home Assistant", „openHAB Skill"). Der Wert wird aus dem `description`-Feld der Alexa-API geparst (`entity_id via Connector`).
- **Bugfix**: Hersteller-Feld zeigt jetzt die HA-Entity-ID (z.B. `switch.mariodruck_internetzugang`) statt leer zu bleiben.
- **Bugfix**: Online-Status für Smart-Home-Geräte nutzt jetzt `availability == "AVAILABLE"` (korrektes API-Feld).
- **Bugfix**: Gerätetyp wird jetzt aus `providerData.deviceType` gelesen (z.B. `SWITCH`, `ACTIVITY_TRIGGER`).
- **Bugfix**: Gerätename wird jetzt aus `displayName` gelesen statt aus `friendlyName` (das in dieser API-Antwort nicht existiert).

## 0.9.7

- **Feature**: Neue Debug-Seite unter `/debug` — alle API-Endpunkte per Klick aufrufbar, JSON-Antwort wird syntaxhervorgehoben angezeigt. Kein manuelles Token-Kopieren nötig.
- **Feature**: „🛠 Debug"-Button in der Hauptseite-Toolbar verlinkt direkt auf die Debug-Konsole.

## 0.9.6

- **Design**: Neues App-Icon und Logo — stilisierter Echo-Lautsprecher (grau auf weiß), passend zum Home-Assistant-Add-on-Stil. Mit Alexa-Ring, Grille-Linien und Basis.

## 0.9.5

- **Debug**: Neuer Endpunkt `/api/devices-debug` gibt die Rohdaten der ersten 3 Smart-Home-Geräte zurück. Damit lässt sich prüfen, in welchen API-Feldern Skill- und Hersteller-Informationen tatsächlich geliefert werden, um die Normalisierung gezielt anpassen zu können.

## 0.9.4

- **Feature**: Geräteliste jetzt als Tabelle statt Kachelansicht.
- **Feature**: Checkbox-Spalte mit „Alle auswählen"-Header und Auswahl-Counter – Vorbereitung für künftige Bulk-Operationen (Umbenennen, Löschen).
- **Feature**: Neue Spalte „Skill / Connector" zeigt den Alexa-Skill-Namen des Connectors (z.B. „openHAB Skill", „Home Assistant") getrennt vom Hersteller.
- **Verbesserung**: Hersteller-Spalte (`manufacturerName`) ist jetzt separat sichtbar und nicht mehr im `family`-Sammelfeld versteckt.
- **UI**: Online-Status als farbiger Punkt, Quell-Badge (🔵 Echo / 🏠 Smart Home) und farbige Zeilen-Akzente (Blau = Echo, Grün = Smart Home).

## 0.9.3

- **Feature**: Smart-Home-Geräte werden jetzt zusätzlich zu Echo-Geräten angezeigt. Lampen, Schalter, Steckdosen, Thermostate und alle anderen mit Alexa verbundenen Drittanbieter-Geräte erscheinen in der Geräteliste.
- **Verbesserung**: Geräteabfrage nutzt zwei Alexa-API-Endpunkte: `/api/devices-v2/device` (Echo-Geräte) und `/api/behaviors/entities?skillId=amzn1.ask.1p.smarthome` (Smart-Home-Geräte). Beide Quellen werden zusammengeführt und dedupliziert.
- **Verbesserung**: HTTP-Header bei Alexa-API-Anfragen auf Browser-User-Agent mit `Referer`/`Origin` umgestellt, wie es der Smart-Home-Endpunkt erwartet.
- **UI**: Jede Gerätekarte zeigt jetzt ein Badge `🏠 Smart Home` oder `🔵 Echo` sowie den Hersteller/Skill-Namen an.
- **UI**: Farbiger linker Rand zur visuellen Unterscheidung: Blau = Echo-Gerät, Grün = Smart-Home-Gerät.
- **Bugfix**: Versionsnummer in `server_clean.py` war auf 0.9.1 geblieben, obwohl `config.yaml` bereits 0.9.2 ausgewiesen hat. Beide sind jetzt synchron.

## 0.9.2

- **Bugfix**: Amazon-Login-Proxy schreibt nun mehr Amazon-Links, Formularziele und Asset-URLs auf den lokalen HA-Ingress-Proxy um.
- **Bugfix**: Relative `form action`, `href` und `src`-Ziele werden nicht mehr direkt gegen Amazon oder gegen den falschen Root-Pfad aufgelöst.
- **Verbesserung**: Zusätzliche Amazon-Asset-Hosts werden über den Proxy erreichbar gemacht, damit die Loginseite weniger unformatiert erscheint.
- **Release Notes**: Diese Version verbessert den sichtbaren Amazon-Login und die Formularweiterleitung. Falls die Seite weiterhin nicht sauber lädt, bitte Browser-DevTools/Netzwerkfehler oder Screenshot der Loginseite prüfen.

## 0.9.1

- **Bugfix**: `/auth/login` erhält unter Home-Assistant-Ingress den vollständigen Ingress-Prefix. Die Weiterleitung geht dadurch nicht mehr auf `/auth/alexa-app/start` am Domain-Root, sondern auf `/api/hassio_ingress/<token>/auth/alexa-app/start`.
- **Release Notes**: Diese Version korrigiert den Login-Start innerhalb von HA OS Ingress. Installieren, Repository neu laden und anschließend den Alexa-Login erneut starten.

## 0.9.0

- **Rewrite**: Aktiver Server auf `server_clean.py` umgestellt. Die alte Patch-/Runtime-Rewrite-Kette wird nicht mehr gestartet.
- **Feature**: Neuer Login-Mechanismus `oh_style_login.py`, orientiert am aktuellen openHAB Amazon Echo Control Binding.
- **Feature**: Login startet über Amazons App-Registration-Flow mit `www.amazon.com/ap/signin`, `maplanding`, `auth/register` und `/ap/exchangetoken`.
- **Cleanup**: Add-on-Konfiguration bereinigt. Alte Werte wie `client_id`, `client_secret`, `refresh_token`, `alexa_cookie`, `alexa_csrf` und `amazon_region` sind nicht mehr Bestandteil der aktiven Konfiguration.
- **Docs**: `OPENHAB_STYLE_LOGIN.md` ergänzt und den aktiven Loginweg dokumentiert.

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
