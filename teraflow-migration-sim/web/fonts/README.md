# Local fonts

The console uses STIX Two Text for headings and IBM Plex Sans and Mono for text and data, all redistributed under the SIL Open Font License (`STIXTwoText-OFL.txt`, `IBMPlex-OFL.txt`). The application loads only these local assets and has no runtime CDN dependency; `src/web.py` serves only the files listed in `FONTS`.

| File | Role | Source (Google Fonts repository) |
| --- | --- | --- |
| `IBMPlexSans.ttf` | Body text and controls (variable, weights 100–700) | `ofl/ibmplexsans/IBMPlexSans[wdth,wght].ttf` |
| `STIXTwoText.ttf` | Headings (variable, weights 400–700) | `ofl/stixtwotext/STIXTwoText[wght].ttf` |
| `IBMPlexMono-Regular.ttf`, `IBMPlexMono-Medium.ttf` | Measurements, identifiers, logs | `ofl/ibmplexmono/` |

Downloaded on 8 November 2026 from https://github.com/google/fonts (branch `main`).
