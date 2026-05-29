# Authentifizierungsmechanismus

## Übersicht

Dieses Add-on verwendet **OAuth2 über Login with Amazon (LWA)** zur
Authentifizierung gegenüber der Amazon Alexa API. Es ist **nicht** möglich,
sich direkt mit dem eigenen Amazon-Konto (E-Mail + Passwort) anzumelden.

## Aktueller Ablauf

```
┌──────────────┐         ┌───────────────────────┐        ┌─────────────┐
│  Benutzer    │         │  Amazon Developer      │        │  Amazon     │
│  (Browser /  │         │  Console / LWA         │        │  Alexa API  │
│   Add-on UI) │         │  OAuth2 Server         │        │             │
└──────┬───────┘         └───────────┬───────────┘        └──────┬──────┘
       │                             │                            │
       │ 1. Client-ID, Secret        │                            │
       │    in Add-on eintragen      │                            │
       │    + Redirect-URI in        │                            │
       │    Developer Console        │                            │
       │                             │                            │
       │ 2. "Mit Amazon anmelden"    │                            │
       │    klicken in der App       │                            │
       ├────────────────────────────►│                            │
       │◄────────────────────────────┤ Amazon Login-Seite         │
       │                             │                            │
       │ 3. Bei Amazon einloggen     │                            │
       │    + Berechtigungen erteilen│                            │
       ├────────────────────────────►│                            │
       │                             │                            │
       │ 4. Redirect zurück zum      │                            │
       │    Add-on mit Auth-Code     │                            │
       │◄────────────────────────────┤                            │
       │                             │                            │
       │ 5. Add-on tauscht Code      │                            │
       │    gegen Tokens             │                            │
       │    (automatisch im          │                            │
       │     Hintergrund)            │                            │
       ├────────────────────────────►│                            │
       │◄────────────────────────────┤ Access + Refresh Token     │
       │                             │                            │
       │ 6. Refresh-Token wird       │                            │
       │    persistent gespeichert   │                            │
       │    (/data/oauth_tokens.json)│                            │
       │                             │                            │
       │ 7. API-Aufruf mit           │                            │
       │    Access-Token             │                            │
       ├─────────────────────────────┼───────────────────────────►│
       │◄────────────────────────────┼────────────────────────────┤
       │          Gerätedaten        │                            │
       │                             │                            │
       │ 8. Background-Refresh       │                            │
       │    erneuert Token auto-     │                            │
       │    matisch vor Ablauf       │                            │
       ├────────────────────────────►│                            │
       │◄────────────────────────────┤ Neuer Access-Token         │
```

### Konfigurationsparameter

| Parameter        | Beschreibung                                                   |
|------------------|----------------------------------------------------------------|
| `amazon_region`  | Amazon-Region (`eu`, `na`, `fe`). Standard: `eu`              |
| `client_id`      | OAuth2 Client-ID aus der Amazon Developer Console             |
| `client_secret`  | OAuth2 Client-Secret aus der Amazon Developer Console         |
| `refresh_token`  | *(Optional)* Manuell eingetragener Refresh-Token (Fallback)   |

### Schritte zur Einrichtung

1. Bei der [Amazon Developer Console](https://developer.amazon.com/) anmelden.
2. Unter **Apps & Services → Login with Amazon** ein neues Security Profile anlegen.
3. **Client ID** und **Client Secret** notieren und in den Add-on-Einstellungen eintragen.
4. Die **Redirect-URI** aus der App-UI kopieren und unter "Web Settings → Allowed Return URLs" im Security Profile registrieren.
5. Im Security Profile unter **"Allowed Scopes"** die Scopes `alexa:all` und `profile` hinzufügen/aktivieren.
6. In der App auf **"Mit Amazon anmelden"** klicken – der Rest passiert automatisch!

## Warum kann man sich nicht direkt mit dem Amazon-Konto anmelden?

Es gibt mehrere technische und rechtliche Gründe:

### 1. Amazon bietet keinen Passwort-basierten API-Zugang

Amazon stellt für Drittanbieter-Anwendungen **kein** API bereit, das eine direkte
Authentifizierung mit E-Mail und Passwort erlaubt (Resource Owner Password
Credentials Grant). Stattdessen erzwingt Amazon den OAuth2 Authorization Code
Flow über einen Browser.

### 2. OAuth2 ist der von Amazon vorgeschriebene Standard

Amazon erlaubt den Zugriff auf seine APIs ausschließlich über **Login with
Amazon (LWA)** – ein OAuth2-System. Das bedeutet:

- Der Benutzer muss sich **einmalig im Browser** bei Amazon anmelden und der App
  Berechtigungen erteilen.
- Die App erhält daraufhin einen **Authorization Code**, den sie gegen ein
  **Access-Token** und ein **Refresh-Token** tauscht.
- Das Access-Token hat eine kurze Lebensdauer (~60 Minuten) und wird bei Bedarf
  über das Refresh-Token erneuert.

Dieses Add-on implementiert den vollständigen OAuth2 Authorization Code Flow
**direkt in der App**. Der Benutzer klickt auf "Mit Amazon anmelden", wird zur
Amazon Login-Seite weitergeleitet, meldet sich dort an (inkl. MFA falls aktiv),
und wird automatisch zurück zur App geleitet. Der Refresh-Token wird im
Hintergrund gespeichert und automatisch erneuert.

### 3. Multi-Faktor-Authentifizierung (MFA)

Die meisten Amazon-Konten haben MFA aktiviert. Ein direkter Passwort-Login würde
den zweiten Faktor (SMS, OTP-App) erfordern, was in einem automatisierten
Headless-System nicht möglich ist. OAuth2 umgeht dieses Problem, da der Benutzer
sich interaktiv im Browser anmeldet, MFA bestätigt, und die App nur den
resultierenden Token erhält.

### 4. Sicherheit

Das Speichern von Amazon-E-Mail und -Passwort in einer Konfigurationsdatei wäre
ein erhebliches Sicherheitsrisiko. OAuth2-Tokens sind:

- **eingeschränkt** – sie gewähren nur die angeforderten Berechtigungen (Scopes)
- **widerrufbar** – der Benutzer kann den Zugriff jederzeit in seinen
  Amazon-Kontoeinstellungen widerrufen
- **kurzlebig** – Access-Tokens laufen nach ~60 Minuten ab

### 5. Amazon Terms of Service

Das automatisierte Anmelden mit Benutzername/Passwort (Credential Stuffing,
Scraping) verstößt gegen die Amazon-Nutzungsbedingungen und kann zur
Kontosperrung führen.

## Zusammenfassung

| Methode                     | Möglich? | Grund                                         |
|-----------------------------|----------|-----------------------------------------------|
| Direkt mit E-Mail/Passwort  | ❌ Nein  | Von Amazon nicht unterstützt, unsicher, TOS-Verstoß |
| OAuth2 (Login with Amazon)  | ✅ Ja    | Offizieller, sicherer Standard                |

## Aktueller Implementierungsstand

Die OAuth2-Kommunikation mit Amazon ist implementiert:

- ✅ Automatischer Token-Refresh im Backend (`POST https://api.amazon.com/auth/o2/token`)
- ✅ Auth-Status-Endpoint (`GET /api/auth-status`) zur Prüfung der Authentifizierung
- ✅ Geräteabruf über die Alexa Smart Home API (`GET /v2/devices`, Fallback: `GET /v2/appliances`)
- ✅ In-Memory Token-Cache mit automatischer Erneuerung vor Ablauf
- ✅ Regionsspezifische Endpoints (EU, NA, FE)
- ✅ Persistenter Token-Cache (überlebt Add-on-Neustart, gespeichert in `/data/token_cache.json`)
- ✅ Automatischer Background-Refresh alle 60 Sekunden, erneuert Token 5 Minuten vor Ablauf
- ✅ Token-Refresh-Status-Endpoint (`GET /api/token-refresh-status`)
- ✅ Integrierter OAuth2-Flow über Ingress (Browser-Redirect → Amazon Login → Callback)
- ✅ Refresh-Token wird automatisch in `/data/oauth_tokens.json` gespeichert
- ✅ Login/Logout UI mit CSRF-Schutz (State-Parameter)
- ✅ Redirect-URI Anzeige in der UI für einfache Registrierung in der Developer Console
- ✅ Info-Ansicht mit App-Version und angemeldetem Amazon-Benutzer

## Zukünftige Verbesserungen

- [ ] Validierung der Credentials beim Speichern der Konfiguration
