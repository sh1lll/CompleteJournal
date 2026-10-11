# Code signing (optional, recommended before public release)

Unsigned builds work, but Windows SmartScreen and macOS Gatekeeper show a
warning on first launch. The **Desktop apps** workflow signs automatically as
soon as these repository secrets exist (Settings → Secrets and variables →
Actions). Without them, builds stay unsigned — nothing else changes.

## Windows (Authenticode)

1. Buy a code-signing certificate (OV or EV) from a CA such as DigiCert,
   Sectigo or SSL.com (~$100–400/year). EV certificates on hardware tokens
   need a cloud-signing service instead of a .pfx file.
2. Export it as a `.pfx` and add secrets:
   - `WIN_CERT_PFX` — the .pfx file, base64-encoded (`base64 -w0 cert.pfx`)
   - `WIN_CERT_PASSWORD` — its password

## macOS (Developer ID + notarization)

1. Join the Apple Developer Program (US$99/year).
2. Create a **Developer ID Application** certificate, export it from Keychain
   as `.p12`, and add secrets:
   - `MACOS_CERT_P12` — base64 of the .p12
   - `MACOS_CERT_PASSWORD` — its export password
   - `MACOS_SIGN_IDENTITY` — e.g. `Developer ID Application: Your Name (TEAMID)`
   - `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` (an app-specific password)
3. The workflow signs with the hardened runtime, notarizes with
   `notarytool`, and staples the ticket.

## Releases and updates

Push a version tag (e.g. `git tag v0.3.0 && git push origin v0.3.0`). The
workflow builds all three platforms, publishes them with `SHA256SUMS.txt`,
and the app's **Download and verify** button checks every download against
those checksums. With signed builds, a fully automatic install step can be
added on top of this.
