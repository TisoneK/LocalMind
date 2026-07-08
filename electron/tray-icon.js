/**
 * LocalMind Tray Icon Generator
 *
 * Creates a simple tray icon using nativeImage.
 * The icon is a green circle on a transparent background,
 * rendered pixel-by-pixel into a small RGBA buffer.
 *
 * This avoids needing to ship an icon file for the tray.
 * For production builds you should replace this with a proper .ico/.icns/.png.
 */

const { nativeImage } = require('electron');

/**
 * Create a tray icon as a nativeImage.
 * Generates a 16x16 green circle on a transparent background.
 *
 * @returns {Electron.NativeImage}
 */
function createTrayIcon() {
  const size = 16;
  const rgba = Buffer.alloc(size * size * 4, 0); // start fully transparent

  const centerX = size / 2;
  const centerY = size / 2;
  const radius = size / 2 - 1; // leave 1px padding

  // Green color: RGB(76, 175, 80) -- Material Design green
  const r = 76;
  const g = 175;
  const b = 80;
  const a = 255;

  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      const dx = x - centerX;
      const dy = y - centerY;
      const distance = Math.sqrt(dx * dx + dy * dy);

      const offset = (y * size + x) * 4;

      if (distance <= radius) {
        // Anti-alias the edge: fade alpha within 1 pixel of the radius
        if (distance > radius - 1) {
          const edgeAlpha = Math.round(a * (radius - distance + 1));
          rgba[offset] = r;
          rgba[offset + 1] = g;
          rgba[offset + 2] = b;
          rgba[offset + 3] = Math.max(0, Math.min(255, edgeAlpha));
        } else {
          rgba[offset] = r;
          rgba[offset + 1] = g;
          rgba[offset + 2] = b;
          rgba[offset + 3] = a;
        }
      }
      // Outside the circle remains transparent (already zeroed)
    }
  }

  const image = nativeImage.createFromBuffer(rgba, {
    width: size,
    height: size,
    scaleFactor: 1.0,
  });

  // On macOS the tray should be a template image (monochrome).
  // Our green circle looks good on all platforms, but on macOS we
  // mark it as a template image so it adapts to light/dark menu bars.
  if (process.platform === 'darwin') {
    return image.resize({ width: 22, height: 22 });
  }

  return image;
}

module.exports = { createTrayIcon };
