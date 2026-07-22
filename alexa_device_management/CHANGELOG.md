# Changelog

## 2.11.13-rc1

- **Fix Login (EU/DE-Accounts, Teil 2)**: Der in 2.11.12-rc1 eingeführte EU-Fallback schlug weiterhin fehl ("account not accessible on US or any EU Alexa marketplace"), weil `exchange_token` das übergebene `cookie_domain`-Argument nur für den `cookies`-Anfrage-Wrapper verwendete — das `domain`-Formularfeld und die Ziel-URL griffen weiterhin fest auf `state["retailDomain"]`/`state["retailUrl"]` (`amazon.com`) zurück. Dadurch wurden für `.amazon.de` angeforderte Cookies inkonsistent gegen den US-Exchange-Endpunkt ausgetauscht und von Amazon abgelehnt. `exchange_token` leitet Ziel-URL und `domain`-Feld jetzt korrekt aus dem übergebenen `cookie_domain` ab, sodass EU-Marktplätze tatsächlich eigene, gültige Cookies erhalten.

## 2.11.12-rc1

- **Fix Login (EU/DE-Accounts)**: Nach erfolgreichem Amazon-Login schlug der Callback mit `GET https://alexa.amazon.com/api/users/me failed (401)` fehl — bei deutschen (und anderen EU-) Accounts ist der Alexa-API-Endpunkt `alexa.amazon.de`, nicht `alexa.amazon.com`. `register_app` versucht nun bei 401 automatisch EU-Fallback-Domains (`amazon.de`, `.co.uk`, `.fr`, `.it`, `.es`) und verwendet den erfolgreichen Endpunkt für alle weiteren API-Aufrufe (inkl. `/api/endpoints`).

## 2.11.11-rc1

- **Fix**: `ValueError: not enough values to unpack` beim Login-Proxy behoben — `rewrite_html` hatte das Regex-Capture für den URL-Scheme (`https?`) vergessen, was bei jeder Amazon-Login-Seite einen 500-Fehler auslöste.
- **Fix**: Doppeltes Proxying von absoluten URLs behoben — nach dem Umschreiben von `https://host/path` durch `repl_absolute` traf die Relative-Pfad-Regel erneut zu und erzeugte doppelt-proxied URLs.

## 2.11.10-rc1

- **Fix Version**: `server_extended.py` (der tatsächliche Einstiegspunkt) zeigte noch `2.11.7-rc1`, weil es `server_clean.APP_VERSION` mit seinem eigenen Wert überschreibt. Auf `2.11.10-rc1` aktualisiert.
- **Fix Login (neuer Tab / 401 via Companion App)**: Login-Buttons öffnen keinen neuen Tab mehr (`target="_blank"` entfernt). Ein neues Fenster verliert die HA-Session bei Remote-/Nabu-Casa-Zugriff → 401. Login läuft jetzt im selben WebView.
- **Fix Login (Amazon-Fehlerseite lokal)**: Protokoll-relative URLs (`//host/path`) in Amazon-Login-Seiten werden jetzt durch den Proxy umgeschrieben. Vorher wurden `action="//www.amazon.com/ap/signin"`-Formularaktionen wegen `(?!/)` im Regex übersprungen, was dazu führte, dass der Browser direkt zu Amazon postete — Amazon sah eine nicht authentifizierte Anfrage und zeigte die „There was a problem"-Seite.
- **Fix Login (server_extended)**: `server_extended.py` importierte und installierte `alexa_login_rewrite_fix` (altes Patch-Modul das `oh_style_login.rewrite_html` durch eine Version mit `/auth/alexa-app/proxy/` Pfaden ersetzte) und registrierte eine eigene `/alexa-login` Route mit dem alten Proxy-Pfad — damit wurden alle Login-Fixes aus server_clean.py und oh_style_login.py effektiv überschrieben. Beide Overrides entfernt.

## 2.11.9-rc1

- **Fix Login (HA Companion App)**: Alle Login-Routen aus dem `/auth/`-Namespace verschoben. Die HA Companion App und der HA HTTP-Server interceptieren alle `/auth/*`-Pfade als eigene Auth-Endpunkte und gaben 401 zurück, bevor der Request das Add-on erreichte. Neue Pfade: `/alexa-login` (start), `/alexa-auth/...` (Proxy), `/api/auth-session`, `/api/logout`.

## 2.11.8-rc1

- **Fix Login**: `map-md`-Cookie enthielt eine veraltete hardcodierte App-Version (`2.2.443692`) statt der aktuellen `API_VERSION` — Amazon vergleicht diesen Wert intern.
- **Fix Login**: `API_VERSION` auf `2.2.623270.0` und `DI_OS_VERSION` auf `18.3.2` (iOS 18) aktualisiert — Amazon lehnt sehr alte iOS-Versionen für neue Gerät-Registrierungen zunehmend ab.
- **Fix Login**: `AMAZON_PROXY_HOSTS` um EU-Domains erweitert (`www.amazon.de`, `.co.uk`, `.fr`, `.it`, `.es`, `completion.amazon.de`, `fls-eu`, `unagi-eu`, `api.amazon.com`) — fehlende Hosts führten dazu dass Links im Login-Flow nicht durch den Proxy umgeleitet wurden.

## 2.11.5-rc1

- **Fix**: Der Amazon-Login verwendet wieder den historisch funktionierenden Proxy-Ablauf aus den frühen Versionen.
- **Fix**: Nur die URL-Erzeugung wurde angepasst: Browser-Weiterleitungen bleiben relativ im aktiven Home-Assistant-Ingress und verwenden niemals interne Hosts wie `homeassistant:8123`.
- **Cleanup**: Der zuletzt ergänzte vollständige Proxy-Ersatz wurde entfernt, da er den bewährten Login-Ablauf verändert und 500-Fehler ausgelöst hat.

## 2.11.3-rc1

- **Fix**: Der Amazon-Alexa-Login verwendet nicht mehr den unter Home-Assistant-Ingress problematischen Pfad `/auth/login`, sondern startet direkt über `/alexa-login`.
- **Fix**: Dadurch wird ein vorgelagerter `401 Unauthorized` vermieden, bevor der Request das Add-on erreicht.

## 2.8.3-rc1

- **Fix**: Die aktuelle HA→Alexa-Konfiguration wird beim Ausrollen jetzt direkt aus dem Editor an `/api/ha-export/deploy` gesendet.
- **Fix**: Das Schreiben von `alexa.yaml` hängt nicht mehr davon ab, ob der verzögerte Autosave bereits abgeschlossen wurde.
- **Fix**: Der veraltete Deployment-Aufruf ohne Request-Body wird abgefangen, damit keine leere oder veraltete persistente Konfiguration ausgerollt wird.
- **Diagnose**: Die Rückmeldung zeigt geschriebenen Pfad, Backup, Anzahl ausgewählter Entitäten und Ergebnis der Home-Assistant-Konfigurationsprüfung.

## 2.8.2-rc1

- **Fix**: Eine Request-Flut der Lifecycle-Prüfung wurde beseitigt. Zuvor löste praktisch jedes `input`- und `change`-Ereignis einen verzögerten Statusabruf aus; beim Tippen entstanden dadurch viele parallele Requests.
- **Performance**: Lifecycle-Abfragen werden jetzt dedupliziert, bei ausgeblendeter Seite ausgesetzt und nur noch bei Fokus, expliziten Statusänderungen sowie alle 60 Sekunden ausgeführt.
- **Performance**: Große Geräte- und Entity-Listen nutzen CSS-Containment und `content-visibility`, sodass außerhalb des sichtbaren Bereichs liegende Karten nicht sofort vollständig berechnet und gezeichnet werden.
- **Performance**: Die HA→Alexa-Konfigurationsseite belastet dadurch die gesamte Home-Assistant-Oberfläche deutlich weniger.

## 2.8.1-rc1

- **Performance**: Die HA→Alexa-Gerätekonfiguration reagiert jetzt unmittelbar auf Checkboxen, Namensfelder, Beschreibungen und Kategorien. Einzelne Änderungen lösen kein vollständiges Neurendern aller Geräte und Entitäten mehr aus.
- **Performance**: Neue zentrale Event-Verarbeitung per Event Delegation reduziert tausende einzelne Handler und vermeidet blockierende DOM-Arbeit während der Eingabe.
- **Autosave**: Änderungen werden mit 1 Sekunde Verzögerung gebündelt gespeichert. Die Serialisierung großer Konfigurationen erfolgt erst nach Ende der Eingabe und nicht mehr im unmittelbaren Eingabeereignis.
- **Autosave**: Beim Verlassen der Seite wird nur noch gespeichert, wenn tatsächlich ungespeicherte Änderungen vorhanden sind.

## 2.8.0-rc1

- **Architektur**: Persistenter ConfigStore als zentrale Datenquelle für die HA→Alexa-Konfiguration.
- **Cache**: Robuster Alexa-Gerätecache mit Migration, Diagnose und Hintergrundaktualisierung.
- **Export**: Deterministischer YAML-Generator mit atomischem Schreiben, Backups und Backup-Rotation.
- **Deployment**: Home-Assistant-Konfigurationsprüfung mit automatischem Rollback bei Fehlern.
- **UI**: Responsive Gerätekarten, Autosave, Bulk-Editor, Discovery-Vorschau und mobile Bedienung.
- **Prüfung**: Konsistenz-, Berechtigungs- und Lifecycle-Prüfungen für Deployment, Neustart und Alexa-Gerätesuche.
- **Qualität**: CI-Prüfungen für Python, JavaScript, Unit-Tests, App-Metadaten und Docker-Build.
- **Migration**: Automatische Übernahme bestehender 1.x-Konfigurationen und bestehender `alexa.yaml`-Auswahl.

## 1.5.0

- **Feature**: HA → Alexa Export-Manager erweitert: Geräte-Vorbereitung, Bulk-Aktionen und Vorschau der Alexa-Capabilities in der Export-Oberfläche (`/ha-export`).
- **Wartung**: Zusammenführung der UI-Verbesserungen aus 1.4.1 (immer sichtbarer Scrollbalken, Sticky-Tabellenkopf) mit dem Export-Manager.

## 1.4.1

- **UX**: Die Gerätetabelle scrollt jetzt in einem eigenen Bereich, der immer am unteren Bildschirmrand endet — der horizontale Scrollbalken ist dadurch jederzeit sichtbar, egal an welcher Stelle der Liste man sich befindet (vorher lag er erst ganz am Ende der Seite).
- **UX**: Spaltenüberschriften und Filterzeile bleiben beim vertikalen Scrollen durch die Geräteliste stehen (sticky) — inklusive „Alle auswählen"-Checkbox und Sortier-Pfeilen.
- **Fix**: Farbige Zeilen-Akzente (blau = Echo, grün = Smart Home) an das neue Tabellen-Layout angepasst.

## 1.4.0

- **Feature**: HA → Alexa Export-Manager (PR #41). Neue Seite `/ha-export` (Button „HA → Alexa" in der Toolbar) zum Konfigurieren, welche Home-Assistant-Geräte an Alexa exportiert werden, inklusive Import des bestehenden Alexa-YAML-Pakets, geprüftem Speichern der Konfiguration und Home-Assistant-Neustart aus der Oberfläche.

## 1.3.0

- **Feature**: Das Backend hält die Geräteliste jetzt selbst vor (Stale-While-Revalidate). Die Liste wird beim Add-on-Start einmal geladen, alle 15 Minuten im Hintergrund aufgefrischt und in `/data/devices_cache.json` gespeichert. Beim Öffnen der App erscheinen die Geräte dadurch sofort aus dem Zwischenspeicher, statt bei jedem Öffnen erst auf die Alexa-API zu warten.
- **Feature**: Ist der Zwischenspeicher älter als 60 Sekunden, wird er weiterhin sofort ausgeliefert und parallel im Hintergrund aktualisiert — die App bleibt schnell und die Daten aktuell.
- **Feature**: Löschen und Umbenennen pflegen den Zwischenspeicher direkt (gelöschte Geräte raus, umbenannte aktualisiert) — kein zusätzlicher Alexa-Abruf nötig, die Liste stimmt sofort.
- **UX**: Der „↻ Aktualisieren"-Button erzwingt jetzt einen frischen Abruf von Alexa (`?refresh=1`) und zeigt währenddessen „⏳ Lade…". Die Info-Karte zeigt an, wie alt der Zwischenspeicher ist („aktualisiert vor 3 min").
- **Robustheit**: Ein leeres Ergebnis durch einen vorübergehenden API-Fehler überschreibt einen vorhandenen guten Zwischenspeicher nicht mehr — die zuletzt bekannten Geräte bleiben erhalten.

## 1.2.6

- **Feature**: Bulk-Löschen läuft jetzt als serverseitiger Hintergrund-Job im Add-on statt im Browser. Der Vorgang läuft weiter, auch wenn die Seite geschlossen oder verlassen wird.
- **UX**: Beim Zurückkehren auf die Seite wird ein laufender Löschvorgang automatisch erkannt und der Live-Fortschritt (Zähler, Fortschrittstext, ausgegraute aktuelle Zeile, verschwindende Zeilen) nahtlos weiter angezeigt. Ist der Job in der Zwischenzeit fertig geworden, erscheint einmalig die Zusammenfassung.
- **API**: Neue Endpunkte `POST /api/devices/delete-job` (Start), `GET /api/devices/delete-job` (Status), `POST /api/devices/delete-job/cancel` (Abbruch). Der Job-Status wird nach `/data/delete_job.json` persistiert; wird das Add-on mitten im Job neu gestartet, wird der Job beim nächsten Statusabruf als „unterbrochen" gemeldet statt fälschlich als laufend.
- **Schutz**: Es kann immer nur ein Löschvorgang gleichzeitig laufen (HTTP 409 beim Startversuch eines zweiten); die Seite zeigt dann den Fortschritt des laufenden Jobs an.

## 1.2.5

- **UX**: Live-Fortschritt beim Bulk-Löschen. Die Geräte werden jetzt einzeln nacheinander gelöscht: Jede Zeile wird während des Löschens ausgegraut und verschwindet sofort nach Erfolg, der Gerätezähler in der Info-Karte zählt live herunter, und in der Tabellen-Toolbar läuft eine Fortschrittsanzeige mit („🗑 Lösche 3/17: Gerätename…").
- **UX**: Neuer Button „✕ Abbrechen" während des Löschvorgangs — stoppt nach dem aktuell laufenden Gerät. Bereits gelöschte Geräte bleiben gelöscht; die Zusammenfassung weist den Abbruch aus.
- **UX**: Fehler einzelner Geräte brechen den Vorgang nicht mehr ab; sie werden gesammelt und am Ende zusammengefasst gemeldet.

## 1.2.4

- **Performance**: Winner-Cache — die Mutation, die beim Löschen bzw. Umbenennen zuletzt nachweislich funktioniert hat, wird in `/data/api_hints.json` gespeichert und beim nächsten Mal direkt zuerst ausgeführt (mit Verifikation). Die volle Kandidaten-Leiter läuft nur noch, wenn der gespeicherte Weg nicht mehr funktioniert. Das Löschen weiterer Geräte ist dadurch deutlich schneller.
- **Performance**: Die abgeschaltete Phoenix-v2-API wird nach dem ersten 400/403/404 für die Prozess-Laufzeit gemerkt und nicht mehr bei jedem Gerät erneut angefragt.
- **UX**: Nach erfolgreichem Löschen oder Umbenennen wird die Geräteliste automatisch neu geladen — Gerätezähler in der Info-Karte und Filter-Zähler stimmen sofort, ohne manuellen Reload. Aktive Spaltenfilter und die Sortierung bleiben beim Auto-Refresh erhalten.

## 1.2.3

- **Feature**: Schema-gesteuertes Löschen/Umbenennen per GraphQL-Introspection. Die 1.2.2-Probe hat gezeigt, dass die Nexus-API lebt, aber ein anderes Schema hat als vermutet (`deleteEndpoint` existiert nicht, `LegacyIdentifiers` hat kein `legacyApplianceIdentifier`). Statt weiter Namen zu raten, fragt das Add-on jetzt das Schema zur Laufzeit ab (`__type`-Introspection): Es sucht alle Mutationen, deren Name nach Löschen (`delete|forget|remove|unlink|deregister` + `endpoint|appliance|device|entity`) bzw. Umbenennen (`rename|friendlyName|set/update…name`) aussieht, konstruiert den Aufruf automatisch aus den introspektierten Argument-Typen (inkl. Input-Objekten und Listen) und führt ihn aus — mit Sicherheitsnetz: Eine Mutation wird nur ausgeführt, wenn die Endpoint-ID (und beim Umbenennen der neue Name) nachweislich in die Variablen gebunden wurde; parameterlose „deleteAll"-artige Mutationen können so nie ausgelöst werden. Erfolg zählt weiterhin erst nach Verifikation gegen `behaviors/entities`.
- **Fix**: Die `endpoints`-Query verwendet nur noch Felder, die das Live-Schema laut Validierungsfehlern kennt (kein `latencyTolerance`, kein `legacyApplianceIdentifier`).
- **Debug**: Delete-Probe zeigt neu die Schema-Discovery: Anzahl und geräte-relevante Namen aller verfügbaren Mutationen (`graphql_mutations_device_related`), Felder von `LegacyIdentifiers` und `Endpoint` sowie pro versuchter Mutation die generierte Query und die Antwort.

## 1.2.2

- **Fix**: Umstellung auf die moderne GraphQL-API (`POST /nexus/v1/graphql`). Die Delete-Probe hat gezeigt, dass die komplette Phoenix-v2-API (`GET /api/phoenix*`) für migrierte Accounts nur noch HTTP 400 liefert — Amazon hat sie abgeschaltet; openHAB und alexa-remote2 mussten aus demselben Grund auf GraphQL umstellen. Löschen und Umbenennen lösen das Gerät jetzt zuerst über die GraphQL-`endpoints`-Query auf (liefert `legacyIdentifiers.legacyApplianceIdentifier.applianceId` im Format `SKILL_…`/`AAA_…`) und verwenden diese ID für `DELETE`/`PUT /api/phoenix/appliance/…`. Zusätzlich werden GraphQL-Mutationen (`deleteEndpoint`, `setFriendlyName`, `updateEndpoint`) als Kandidaten probiert. Wie immer gilt ein Versuch erst nach Verifikation gegen `behaviors/entities` als Erfolg.
- **Debug**: Delete-Probe zeigt neu `graphql_lookup`/`graphql_endpoint` — Status, Fehlermeldungen und den gefundenen Endpoint-Datensatz der GraphQL-API. Falls weiterhin kein Kandidat greift, zeigt diese Ausgabe exakt, welche Schema-Felder die API akzeptiert.

## 1.2.1

- **Fix**: Löschen von v3-Skill-Geräten (openHAB3) löst jetzt zuerst die echte Phoenix-`applianceId` auf. Phoenix führt Skill-Geräte intern unter einer eigenen ID (Format `SKILL_<base64>_<uuid>` bzw. `AAA_…`), nicht unter der behaviors-UUID — deshalb liefen alle bisherigen Kandidaten auf 404 oder No-Op. Neu: `GET /api/phoenix` wird abgerufen, das verschachtelte (mehrfach JSON-stringifizierte) `networkDetail` durchsucht und das Gerät per `entityId` gefunden; anschließend `DELETE /api/phoenix/appliance/{applianceId}` mit der dort hinterlegten ID — derselbe Weg, den auch alexa-remote2 (ioBroker) verwendet. Die bisherigen Kandidaten bleiben als Fallback, inklusive Verifikation gegen `behaviors/entities`.
- **Fix**: Umbenennen von Smart-Home-Geräten nutzt denselben Phoenix-Lookup: `PUT /api/phoenix/appliance/{applianceId}` mit der aufgelösten ID (einfacher Body und vollständiger Appliance-Datensatz mit neuem `friendlyName`), ebenfalls mit Verifikation.
- **Fix**: Probe-Ergebnisse überschreiben sich nicht mehr gegenseitig, wenn zwei Kandidaten denselben Pfad mit unterschiedlichem Body verwenden (Key-Kollision bei `POST /api/phoenix/smarthome/appliance`).
- **Debug**: Delete-Probe zeigt neu `phoenix_network_lookup` — den in `GET /api/phoenix` gefundenen Appliance-Datensatz zum Gerät.

## 1.2.0

- **Feature**: Geräte umbenennen — neuer ✏️-Button in jeder Tabellenzeile. Echo-Geräte werden über `PUT /api/devices-v2/device/{serial}` (mit `accountName`) umbenannt. Smart-Home-Geräte werden nach dem bewährten Kandidaten-Prinzip über cookie-authentifizierte Web-API-Endpunkte versucht (`PUT /api/phoenix/appliance/…`, `PUT /api/behaviors/entities/…`); nach jedem 2xx wird gegen `behaviors/entities` verifiziert, dass der neue Name wirklich übernommen wurde. Falls kein Kandidat bestätigt wird, erscheint der Hinweis, das Gerät in der Skill-Quelle (z.B. openHAB, Home Assistant) umzubenennen.
- **Feature**: Spalten-Sortierung — Klick auf einen Spaltenkopf sortiert die Tabelle auf-/absteigend (Name, Typ, Skill, Hersteller, Raum, Seriennummer, Quelle, Online-Status). Der aktive Sortierpfeil (▲/▼) wird im Header angezeigt.
- **Feature**: CSV-Export — neuer Button „⬇ CSV" in der Tabellen-Toolbar exportiert die aktuell gefilterte Geräteliste als Semikolon-getrennte CSV-Datei (UTF-8 mit BOM, direkt in Excel/LibreOffice öffenbar).
- **Cleanup**: Alte Legacy-Serverdateien entfernt (`server.py`, `server_patched.py`, `server_patched_entry.py`, `server_app_entry.py`, `alexa_openhab_login.py`, `login_result_patch.py`). Aktiv sind nur noch `server_clean.py` und `oh_style_login.py`; der Dockerfile-Normalisierungsblock für die historischen Syntax-Artefakte wurde durch einen einfachen `py_compile`-Check ersetzt.
- **Docs**: `DOCS.md` und `README.md` auf den aktuellen Stand gebracht — die veraltete LWA-/OAuth-Konfigurationsanleitung wurde durch den tatsächlichen Alexa-Web-Login-Ablauf ersetzt; Funktionsliste aktualisiert.
