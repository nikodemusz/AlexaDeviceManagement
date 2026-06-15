# Alexa Device Management 0.8.15

## Was wurde korrigiert?

Diese Version trennt den neuen Alexa-Web/App-Login sauber von der alten Amazon-LWA/API-Key-Anmeldung.

## Änderungen

- Eine vorhandene alte Konfiguration mit `client_id`, `client_secret` oder `refresh_token` markiert das Add-on nicht mehr als verbunden.
- Die UI blendet den Alexa-Web-Login nicht mehr aus, nur weil alte LWA-Zugangsdaten vorhanden sind.
- Ohne gültige Alexa-Web-Session fällt `/api/devices` nicht mehr auf den alten Alexa-API-Tokenpfad zurück.
- Stattdessen wird klar gemeldet, dass die Alexa-Web-Session verbunden werden muss.

## Hintergrund

Die alte Loginmethode über Amazon LWA/API-Key gehört nicht mehr zum aktuellen Ziel dieses Add-ons. Das Add-on soll die frühere Geräteverwaltung der entfernten Alexa-Weboberfläche ersetzen und nutzt dafür den Alexa-Web/App-Loginpfad. Alte Konfigurationswerte dürfen deshalb den neuen Login nicht mehr blockieren.
