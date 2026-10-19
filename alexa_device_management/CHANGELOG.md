# Changelog

## 3.6.0

- Home-Assistant-Geräte lassen sich in der Geräteübersicht als benanntes Alexa-Gesamtgerät mit mehreren Funktionen oder als mehrere einzelne Alexa-Geräte konfigurieren. Pro Funktion sind Name und Exportauswahl einstellbar; abgewählte Entitäten werden aus dem v6-Export entfernt und der Alexa-Abgleich startet automatisch.
- Mehrere Relais werden in einem Gesamtgerät als getrennte Alexa-ToggleController mit stabilen Instanzen angeboten. Beim Wechsel zurück zu einzelnen Geräten werden sie wieder zu eigenständigen PowerControllern.

## 3.5.3

- Fragt Amazons `legacyAppliance.entityId` gezielt im Gerätebestand ab. Diese stabile Herstellerkennung fehlte im bisherigen Überblick, obwohl sie in den Gerätedetails vorhanden ist; v6-Zuordnungen werden damit auch dann erkannt, wenn Amazons interne UUID nicht mit der nativen Endpunkt-ID übereinstimmt.

## 3.5.2

- Verknüpft aktive Alexa-Geräte mit opaken Amazon-IDs über die exakte GraphQL-`endpointId`. Dadurch stimmen v6-Zähler und Gerätezuordnung; nach Abwahl kann der Lifecycle-Abgleich dieselbe native ID gezielt aus Alexa entfernen. Hersteller- oder Namensähnlichkeit allein wird nicht als Gerätezuordnung verwendet.
- Eine gespeicherte Aktivierung/Abwahl startet den Alexa-Abgleich sofort im Hintergrund; laufende Abgleiche werden nach einer gleichzeitigen Änderung erneut ausgeführt.


## 3.5.1

- Fehlende Alexa-Erreichbarkeitsdaten werden als „unbekannt“ statt als „nicht erreichbar“ angezeigt; nur ausdrücklich als offline gemeldete Duplikate kommen für die automatische Bereinigung infrage.
- Die Geräteübersicht meldet eine fehlende v6-Konfiguration als API-/Versionskonflikt, statt mit einem JavaScript-Fehler auf leere Zähler zu fallen.

## 3.5.0

- „Weitere Infos“ fragt die aktuelle Alexa-Geräteregistrierung beim Öffnen erneut ab. Für den ausgewählten Eintrag werden `connectedVia`, Anbieterbeschreibung, Hersteller, Modell, Typen, Aliase und unterstützte Fähigkeiten angezeigt; der letzte Bestandsabruf bleibt separat gekennzeichnet.
- Wenn Alexa keine Zuordnung liefert oder die Live-Abfrage fehlschlägt, wird das ausdrücklich angezeigt statt alte Snapshot-Daten als aktuelle Alexa-Details auszugeben.

## 3.4.0

- Unerwartete Fehler bei Webanfragen protokollieren Route, interne Client-IP und Traceback; Query-Parameter, Header und Request-Inhalte bleiben außen vor, häufige Zugangsdaten im Fehlertext werden redigiert.
- Alexa-Gerätekacheln bieten „Weitere Infos“ mit den Rohdaten des letzten Alexa-Bestandsabrufs, dessen Zeitpunkt und betroffenen Fehlerquellen. Zugangsdatenfelder werden ausgeblendet.

## 3.3.2

- Debug-Antworten werden in schreibgeschützten Textfeldern angezeigt, damit sie auch in iOS-WebViews per langem Tippen markiert und kopiert werden können.

## 3.3.1

- Die Debug-Ausgabe lässt sich auf Mobilgeräten in eine Vollbildansicht vergrößern. JSON kann per langem Tippen markiert oder über eine iOS-kompatible Kopierfunktion übernommen werden.

## 3.3.0

- In der Alexa-Geräteliste können mehrere verwaiste oder nicht zugeordnete Geräte markiert und gemeinsam gelöscht werden. Der Löschauftrag zeigt den Fortschritt; fehlgeschlagene Geräte bleiben markiert.
- Bestätigte alte Home-Assistant-v5-Geräte senden im Hintergrund jetzt zuerst den offiziellen DeleteReport. Die App meldet sie erst nach einem vollständigen, frischen Alexa-Bestand als entfernt; angenommene, aber noch sichtbare Einträge bleiben zur Wiederholung vorgemerkt.
- Die Debug-Seite zeigt getrennte Status-Endpunkte für v5-Deployment/DeleteReport und v6-Veröffentlichung/Bereinigung. Der experimentelle GET-Delete-Probe wurde schreibgeschützt, destruktive Aufrufe liefern HTTP 410.

## 3.2.0

- Die Geräteübersicht verwendet einen persistenten HA- und Alexa-Gruppen-Cache. Sie zeigt vorhandene Daten sofort und aktualisiert veraltete Bestände im Hintergrund.
- Beim ersten Start ohne Cache erscheint die Oberfläche sofort mit einem Ladehinweis und aktualisiert sich automatisch, sobald die Hintergrundabfrage fertig ist. „Aktualisieren“ bleibt ein erzwungener Live-Abruf.

## 3.1.1

- Die Bereinigung alter Alexa-v3-Endpunkte verwendet ausschließlich `forgetEndpoint` mit der tatsächlich aus Alexa gelesenen Endpunkt-ID. Unpassende Mutationen wie `deregisterEndpoint` und `deleteDeviceGroup` werden nicht mehr mit geratenen IDs aufgerufen.
- Wenn Alexa einen Eintrag in der alten Geräteliste zeigt, ihn aber nicht in der Endpunktregistrierung findet, erklärt die Fehlermeldung, dass die Quell-Skill-Konfiguration beziehungsweise ein `DeleteReport` geprüft werden muss. Zugangsdaten werden dadurch nicht verändert.

## 3.1.0

- „Abgleichsdienst installieren“ entfällt in der Hauptansicht. Die beschriebene Option „Alexa-Abgleich aktivieren“ richtet den Dienst beim Speichern der Einstellungen ein und zeigt einen nötigen HA-Neustart an.
- Wiederholtes Speichern schreibt eine unveränderte, bereits geladene Einrichtung nicht erneut. Fehler der HA-Konfigurationsprüfung bleiben sichtbar; bei fehlgeschlagener Einrichtung wird die vorherige YAML wiederhergestellt. Die Einrichtung startet weder HA neu noch eine zusätzliche Alexa-Synchronisation.

## 3.0.3

- Der automatische Abgleich entfernt auch abgewählte native Geräte ohne bisherigen Veröffentlichungsverlauf sowie alte v5-Duplikate. Nur aktuell ausgewählte Endpunkt-IDs bleiben erhalten; fremde Anbieter und Echos werden nicht anhand ihres Namens gelöscht.
- v5-Erkennung berücksichtigt normalisierte und verschachtelte Anbieterfelder. Fehlende/ungültige Auswahl blockiert Löschungen; erneute Auswahl wird direkt vor jeder Löschung geprüft und tatsächliche Entfernung mit frischem Alexa-Bestand bestätigt. UI zeigt verbliebene unerwünschte Geräte und fehlgeschlagene Bereinigung.

## 3.0.2

- Die 15 AWS-Testereignisse liegen als einzelne vollständige JSON-Dateien vor und werden weiterhin von der Offline-Testsuite geprüft.
- Lokales Hilfsskript setzt den HA-OAuth-Token zentral aus einer Umgebungsvariable ein und ersetzt auf Wunsch Endpunkt-IDs in allen passenden Tests. Private Ausgabedateien, explizite Neugenerierung nach Tokenwechsel und Tests für Fehlerfälle; keine Änderung der produktiven Authentifizierung und keine Geräteaktionen.

## 3.0.1

- Gemeinsame Offline-Tests für Lambda und Gateway prüfen Discovery, Gerätesteuerung und Status-Readback für Lampen, Steckdosen, Rollläden, Thermostate und Sensoren einschließlich Zisterne mit Litern/Prozent.
- Tests prüfen OAuth/Gateway-Authentifizierung, v5-Sperre, Fehlerzustände, EndpointHealth und die Übereinstimmung angekündigter und gelieferter Eigenschaften. 15 AWS-Testereignisse mit Platzhaltern und eine Anleitung ergänzen die automatischen Tests; keine echten Geräte werden in der Testsuite geschaltet.

## 3.0.0

- v6 ist die Hauptkonfiguration: Auswahl und Alexa-Namen bearbeiten die native YAML; v5-JSON bleibt als Archiv erhalten und wird nie mehr exportiert. Die Migrationsseite entfällt.
- Native Discovery ist unabhängig vom alten v5-Pfad. AddOrUpdateReport veröffentlicht dieselben v6-Endpunkte wie die Lambda, in größenbegrenzten Batches; fehlgeschlagene Veröffentlichungen werden erneut versucht.
- Erkannte HA-v5-Geräte werden automatisch und unabhängig von der früheren Auswahl entfernt. Native Endpunkte, Echos und fremde Anbieter bleiben geschützt; frischer Alexa-Bestand bestätigt Löschungen.
- Zähler zählen logische v6-Endpunkte, einschließlich mehrerer Messwerte pro Gerät. Der v6-Editor schützt vor parallelem Überschreiben und der 300-Endpunkt-Grenze.
- Upgrade erfordert die neue AWS-Lambda und den aktualisierten HA-Abgleichsdienst (HA-Neustart). Keine automatische Skill-Neuverknüpfung und keine automatische Freigabe archivierter Geräte.

## 2.24.0

- Auswahl strikt begrenzt, auch bei leerer Liste; Abgleich entfernt eindeutig identifizierte, nicht ausgewählte HA-Altgeräte und bewahrt aktive native v6-Geräte.
- A