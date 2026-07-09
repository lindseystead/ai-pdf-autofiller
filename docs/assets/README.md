# Demo assets

## demo.gif (required for viral launch)

A **15–30 second GIF** at the top of the README is the highest-ROI marketing asset.

### What to record

1. Open `/playground` (local or deployed)
2. Drag `samples/sample_form.pdf` onto the upload zone
3. Show the pre-filled JSON (or paste it)
4. Click **Fill PDF**
5. Click **Download filled PDF**
6. Optionally flash the opened PDF for 2 seconds

### How to record

**macOS:** QuickTime → New Screen Recording, or [Kap](https://getkap.co)  
**Linux:** [Peek](https://github.com/phw/peek) or OBS → export as GIF  
**Windows:** ScreenToGif or OBS

### Where to save

```text
docs/assets/demo.gif
```

Then commit and push. The README references this path automatically.

### Tips

- Keep under 5 MB (use [ezgif.com](https://ezgif.com/optimize) to compress)
- 1280×720 or smaller is fine
- No audio needed
- Dark playground UI reads well on GitHub dark mode

### Alternative: GitHub-hosted video

Upload MP4 to a GitHub release or issue comment, then embed:

```markdown
https://github.com/user-attachments/assets/...
```

Replace the GIF block in README with the video URL if preferred.
