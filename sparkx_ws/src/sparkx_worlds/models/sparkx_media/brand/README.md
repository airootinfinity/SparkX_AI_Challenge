# Brand sources

## Partner header (posters, start gate, start pad, flags, dashboards, video)

The official SparkX header, supplied by the organisers. Left to right is the partner priority:
**1 IIIT Allahabad · 2 STEMLearn.AI · 3 Airoot · 4 Presented at IIT Bombay Techfest.**
Wherever several logos stand together they keep this order; single-partner posters are shared out by
priority (see the table at the top of `sparkx_worlds/branding.py`).

| File | What it is |
|---|---|
| `header_strip_dark.png` | the header on its dark background (`#1d1d1f`): READMEs, host panel |
| `header_strip_on_dark.png` | the header with a transparent background, for dark surfaces: posters, referee dashboard, video footer |
| `header_logo_1_iiita.png` | IIIT Allahabad badge, cut from the header |
| `header_logo_2_stemlearn.png` | STEMLearn.AI, cut from the header |
| `header_logo_3_airoot.png` | Airoot, cut from the header |
| `header_logo_4_techfest.png` | "Presented at IIT Bombay Techfest", cut from the header |

To replace the header: put the new transparent version in `header_strip_on_dark.png` and the dark one
in `header_strip_dark.png`, cut the four logos again at the dividers, then run
`ros2 run sparkx_worlds make_textures` and rebuild. The worlds need no regeneration: they refer to the
poster textures by slot name.

## Rover livery (unchanged)

| File | What it is | Source |
|---|---|---|
| `airoot_logo_mask.png` | Airoot mark + wordmark (alpha mask, painted crimson `#e50227`) | rasterized from the crimson bodywork of the Airoot TurtleBot S1 R13 CAD |
| `airoot_mark_mask.png`, `airoot_wordmark_mask.png` | the two halves of the logo | same |
| `stemlearn_logo.png` | STEMLearn.AI horizontal logo | https://stemlearn.ai (official site asset) |
| `stemlearn_icon.png` | STEMLearn.AI icon | https://stemlearn.ai (official site asset) |

Theme (from the S1): ink `#191919`, crimson `#e50227`, off-white `#f0eff2`.
