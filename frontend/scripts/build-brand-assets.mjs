/**
 * Derives the on-dark (reversed) brand lockups from the supplied artwork.
 *
 *   public/brand/fareqube-logo.png  →  fareqube-logo-dark.png
 *   public/brand/fareqube-mark.png  →  fareqube-mark-dark.png
 *
 * The supplied logo is navy-on-transparent, so on the deep-blue brand panels (the auth
 * pages) it is illegible; the old workaround was to sit it on a white card, which read as a
 * sticker stuck on the panel. Instead we knock it out: the wordmark, tagline and the mark's
 * blues go white, and the mark's orange chart segments stay orange so the accent survives.
 * At the sizes these are actually rendered (36–56px tall) merely lightening the blues was
 * not enough — they still disappeared into the panel.
 *
 * Re-run after replacing either source file:  node scripts/build-brand-assets.mjs
 */
import path from "node:path";
import sharp from "sharp";

const BRAND = path.join(import.meta.dirname, "..", "public", "brand");
const LOGO = path.join(BRAND, "fareqube-logo.png");
const MARK = path.join(BRAND, "fareqube-mark.png");

// x=786..854 is the one full-height transparent gutter in the logo — the mark sits left of
// it, the wordmark and tagline right of it.
const SPLIT = 820;
const ORANGE = [253, 186, 116]; // tailwind orange-300, bright enough to hold up on navy

/** Every visible pixel → white, except the orange family, which → ORANGE. Alpha is kept. */
async function knockout(img) {
  const { data, info } = await img.ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  for (let i = 0; i < data.length; i += info.channels) {
    const [r, g, b, a] = [data[i], data[i + 1], data[i + 2], data[i + 3]];
    if (a === 0) continue;
    const isOrange = r > 140 && r - b > 60 && r >= g && g > b;
    [data[i], data[i + 1], data[i + 2]] = isOrange ? ORANGE : [255, 255, 255];
  }
  return sharp(data, { raw: { width: info.width, height: info.height, channels: info.channels } })
    .png({ compressionLevel: 9 })
    .toBuffer();
}

const { width: W, height: H } = await sharp(LOGO).metadata();

const [mark, text] = await Promise.all([
  knockout(sharp(LOGO).extract({ left: 0, top: 0, width: SPLIT, height: H })),
  knockout(sharp(LOGO).extract({ left: SPLIT, top: 0, width: W - SPLIT, height: H })),
]);

await sharp({ create: { width: W, height: H, channels: 4, background: { r: 0, g: 0, b: 0, alpha: 0 } } })
  .composite([
    { input: mark, left: 0, top: 0 },
    { input: text, left: SPLIT, top: 0 },
  ])
  .png({ compressionLevel: 9 })
  .toFile(path.join(BRAND, "fareqube-logo-dark.png"));

await sharp(await knockout(sharp(MARK))).toFile(path.join(BRAND, "fareqube-mark-dark.png"));

console.log("wrote fareqube-logo-dark.png and fareqube-mark-dark.png");
