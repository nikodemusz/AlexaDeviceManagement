# OpenHAB-style Alexa Login

Diese Version verwendet nicht mehr den alten LWA-/OAuth-Konfigurationsweg mit `client_id`, `client_secret` oder manuell hinterlegtem `refresh_token`.

Der aktive Startpunkt ist jetzt:

```text
/opt/alexa_device_management/web/server_clean.py
```

Der Login-Mechanismus liegt in:

```text
/opt/alexa_device_management/web/oh_style_login.py
```

## Prinzip

Der Ablauf orientiert sich an der aktuellen openHAB-Implementierung im Binding `org.openhab.binding.amazonechocontrol`:

1. Login-Start über `https://www.amazon.com/ap/signin`
2. `openid.return_to=https://www.amazon.com/ap/maplanding`
3. Zugriffstoken aus `maplanding` lesen
4. App über `https://api.amazon.com/auth/register` registrieren
5. Refresh-Token über `/ap/exchangetoken` in Web-Cookies tauschen
6. Marketplace über `/api/users/me` und `/api/endpoints` bestimmen
7. Session unter `/data/alexa_session.json` speichern

## Bewusst entfernte/ignorierte Altlasten

- Keine Benutzer-Konfiguration für `client_id`
- Keine Benutzer-Konfiguration für `client_secret`
- Keine Benutzer-Konfiguration für `refresh_token`
- Kein alter LWA-Loginpfad
- Kein `alexa-openhab`-Pfad im aktiven Server
- Keine Dockerfile-Quelltext-Patches als Runtime-Ersatz

Alte Dateien können noch im Repository vorhanden sein, werden aber vom Add-on nicht mehr gestartet. Der aktive Entrypoint ist `server_clean.py`.
