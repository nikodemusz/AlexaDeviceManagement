# Authentifizierungsmechanismus

## Zielrichtung

Dieses Projekt verwendet künftig **keinen Login with Amazon OAuth/LWA Flow** und keine Amazon-Developer-Console-Konfiguration.

Der frühere Ansatz mit `client_id`, `client_secret`, `refresh_token`, App-Registration und OAuth-Token wurde verworfen, weil er für das eigentliche Ziel ungeeignet ist: die Verwaltung der privaten Alexa-Geräte eines bestehenden Amazon-Kontos.

## Geplanter Ansatz

Das Add-on soll sich am pragmatischen Ansatz der openHAB-Amazon-Echo-Control-Integration orientieren:

```text
Home Assistant OS App
  -> lokaler Login-Proxy
  -> Amazon-Weblogin im Browser
  -> Cookie-Jar im Add-on
  -> CSRF aus Cookie oder Alexa-Web-Endpunkt
  -> Alexa-Web-Endpunkte mit Cookie + CSRF aufrufen
```

Die lokale Session wird im Add-on gespeichert, voraussichtlich unter:

```text
/data/alexa_cookie_session.json
```

## Wichtige Abgrenzung

Dieser Weg ist **inoffiziell**. Er nutzt Amazon-Web-/Alexa-Web-Endpunkte, wie sie auch von Browser oder App-nahem Verhalten verwendet werden. Es gibt keine Garantie, dass Amazon diese Endpunkte dauerhaft unverändert lässt.

Das Projekt soll deshalb bewusst keine falsche Sicherheit durch Begriffe wie „offizielle Alexa API“, „OAuth Smart Home API“ oder „Developer Console Login“ vermitteln.

## Aktive Konfiguration

Aktuell sollen nur noch diese Add-on-Optionen sichtbar bleiben:

| Parameter | Beschreibung |
|---|---|
| `amazon_region` | Region, derzeit primär `eu` |
| `alexa_host` | Alexa-Webhost, z. B. `alexa.amazon.de` |

Nicht mehr verwendet und bewusst entfernt:

```text
client_id
client_secret
refresh_token
alexa_cookie
alexa_csrf
```

## Nächste technische Schritte

1. Alten LWA-/OAuth-Code aus dem Backend entfernen oder isolieren.
2. Einen klar benannten Cookie-Login-Proxy implementieren, z. B. unter `/auth/alexa-cookie/...`.
3. Nach erfolgreichem Login Cookie und CSRF speichern.
4. Geräteabruf gegen Alexa-Web-Endpunkte testen, z. B.:

```text
https://alexa.amazon.de/api/bootstrap
https://alexa.amazon.de/api/devices-v2/device
```

5. Erst danach UI und Geräteverwaltung ausbauen.
