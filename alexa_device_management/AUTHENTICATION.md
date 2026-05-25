# Authentifizierungsmechanismus

## Übersicht

Dieses Add-on verwendet **OAuth2 über Login with Amazon (LWA)** zur
Authentifizierung gegenüber der Amazon Alexa API. Es ist **nicht** möglich,
sich direkt mit dem eigenen Amazon-Konto (E-Mail + Passwort) anzumelden.

## Aktueller Ablauf

```
┌──────────────┐         ┌───────────────────────┐        ┌─────────────┐
│  Benutzer    │         │  Amazon Developer      │        │  Amazon     │
│  (Add-on     │         │  Console / LWA         │        │  Alexa API  │
│   Config)    │         │  OAuth2 Server         │        │             │
└──────┬───────┘         └───────────┬───────────┘        └──────┬──────┘
       │                             │                            │
       │ 1. Client-ID, Secret,       │                            │
       │    Refresh-Token eintragen  │                            │
       │    (Add-on Einstellungen)   │                            │
       ├────────────────────────────►│                            │
       │                             │                            │
       │ 2. Add-on tauscht           │                            │
       │    Refresh-Token gegen      │                            │
       │    Access-Token             │                            │
       │    (POST /auth/o2/token)    │                            │
       ├────────────────────────────►│                            │
       │◄────────────────────────────┤ Access-Token               │
       │                             │                            │
       │ 3. API-Aufruf mit           │                            │
       │    Access-Token             │                            │
       ├─────────────────────────────┼───────────────────────────►│
       │◄────────────────────────────┼────────────────────────────┤
       │          Gerätedaten        │                            │
```

### Konfigurationsparameter

| Parameter        | Beschreibung                                                   |
|------------------|----------------------------------------------------------------|
| `amazon_region`  | Amazon-Region (`eu`, `na`, `fe`). Standard: `eu`              |
| `client_id`      | OAuth2 Client-ID aus der Amazon Developer Console             |
| `client_secret`  | OAuth2 Client-Secret aus der Amazon Developer Console         |
| `refresh_token`  | OAuth2 Refresh-Token, erhalten über den LWA-Auth-Flow         |

### Schritte zum Erhalt der Credentials

1. Bei der [Amazon Developer Console](https://developer.amazon.com/) anmelden.
2. Unter **Apps & Services → Login with Amazon** ein neues Security Profile anlegen.
3. **Client ID** und **Client Secret** notieren.
4. Den Login-with-Amazon-OAuth2-Flow durchführen, um einen **Refresh Token** zu erhalten.
5. Alle Werte in der Add-on-Konfiguration eintragen.

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

Dieses Add-on kann **keinen** interaktiven Browser-Login durchführen, da es ein
Headless-Backend ist. Daher muss der Benutzer den OAuth2-Flow **einmalig extern**
durchführen und den resultierenden Refresh-Token manuell in die Konfiguration
eintragen.

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

> ⚠️ Die tatsächliche OAuth2-Kommunikation mit Amazon ist noch **nicht
> implementiert** (siehe `server.py`, Zeile 119–123). Aktuell werden
> Demo-Geräte angezeigt. Die Konfigurationsfelder existieren bereits, die
> Token-Erneuerung und der API-Aufruf sind als nächster Schritt geplant.

## Zukünftige Verbesserungen

- [ ] Automatischer Token-Refresh im Backend (`POST https://api.amazon.com/auth/o2/token`)
- [ ] Integrierter OAuth2-Flow über Ingress (Browser-Redirect → Amazon Login → Callback)
- [ ] Validierung der Credentials beim Speichern der Konfiguration
