# 2.11.2-rc1

- **Fix**: Relative Amazon-Weiterleitungen werden im Alexa-Login gegen die tatsächlich aufgerufene Amazon-URL aufgelöst statt pauschal gegen `www.amazon.com`.
- **Fix**: Der Proxy sendet Amazon als Referer nicht mehr die Home-Assistant-Ingress-URL.
- **Fix**: Erfolgs- und Fehlerseite führen über den korrekten Ingress-Pfad zurück zur App.
