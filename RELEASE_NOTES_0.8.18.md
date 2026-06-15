# Alexa Device Management 0.8.18

## Bugfix

- The Alexa App login now keeps the OpenID OAuth2 extension namespace canonical:
  `http://www.amazon.com/ap/ext/oauth/2`.
- The retail login host can still be regional, for example `www.amazon.de`, but the OpenID namespace is no longer generated as `www.amazon.de`.
- This fixes Amazon's generic 404 page (`Suchst du etwas?`) when the Home Assistant ingress login proxy opens `/auth/alexa-app/FORWARD/www.amazon.de/ap/signin?...`.

## Technical note

Amazon accepts the regional `/ap/signin` URL, but rejects the login request when `openid.ns.oa2` is generated with the regional retail domain. The proxy now rewrites only this namespace parameter while keeping the German Amazon login target and `de_DE` language parameter intact.
