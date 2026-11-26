# PokerScribe demo video (Remotion)

Render on a machine that can reach remotion.media (your Mac is fine):

    npm install
    npx remotion render src/index.jsx Demo out/PokerScribe_demo.mp4

- Sound effects come from Remotion's library (@remotion/sfx, hosted on remotion.media). Cues are in `CUES` in src/index.jsx.
- Music: put a licensed track in `public/` and pass it in:
  `npx remotion render src/index.jsx Demo out/demo.mp4 --props='{"music":"track.mp3","musicVolume":0.5}'`
- Narration (ElevenLabs): save it as `public/narration.mp3`, then add `"narration":"narration.mp3"` to --props.
- Silent render (no sound effects): `--props='{"sfx":false}'`
- Preview and edit live: `npx remotion studio src/index.jsx`
- Scene lengths and transition length: timeline.json
