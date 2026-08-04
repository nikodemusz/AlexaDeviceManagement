# Changelog

## 2.14.1-rc1

- **Fix**: Die Release-Einträge werden wieder direkt im sichtbaren `CHANGELOG.md` gepflegt; der bisherige Verlauf bleibt in `CHANGELOG-legacy.md` erhalten.

## 2.14.0-rc1

- **Geräteverwaltung**: Home-Assistant-Export und Alexa-Gerätebestand sind in einer gemeinsamen Ansicht zusammengeführt.
- **Status**: Vorhandene, ausstehende, doppelte und nur noch in Alexa vorhandene Endpunkte werden pro Entity angezeigt.
- **Ausblenden**: HA-Geräte, einzelne Entities und reine Alexa-Endpunkte können unabhängig vom Export verborgen werden.
- **Bedienung**: Export, Alexa-Gruppen, Umbenennen, Löschen, Deployment und Synchronisierung sind auf einer Seite verfügbar.

## 2.13.0-rc1

- **Event Gateway**: Neue, geänderte und entfernte Endpunkte werden offiziell per `AddOrUpdateReport` und `DeleteReport` an Alexa gemeldet.
- **Konfiguration**: Skill-Zugangsdaten werden ausschließlich über `!secret` referenziert.
- **Lifecycle**: Änderungen werden gegen den zuletzt tatsächlich ausgerollten Bestand berechnet.

Ältere Einträge: [CHANGELOG-legacy.md](CHANGELOG-legacy.md)
