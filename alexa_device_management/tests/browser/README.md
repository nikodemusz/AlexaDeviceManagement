Run `device_editor.cjs` with Node and Playwright to exercise the actual editor
JavaScript in Chromium. Install Playwright in a temporary directory, point
`ADM_PLAYWRIGHT_MODULE` at that directory's `node_modules/playwright`, and run:

```
node alexa_device_management/tests/browser/device_editor.cjs
```

Use Playwright's installed Chromium, or set `ADM_BROWSER_EXECUTABLE` to a local
Chrome/Edge executable. `ADM_UI_ARTIFACTS` optionally chooses the screenshot
directory; the default is a new temporary directory. The test only uses a local
HTTP server with fixture API responses. It verifies metadata save/reload,
sensor access restrictions, selection through filtering/reload, creation of a
group from exactly that selection, sticky controls on desktop/mobile, console
errors, and horizontal overflow. Python grouping tests cover native metadata
persistence and validation separately.
