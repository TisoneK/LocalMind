/**
 * Minimal, dependency-free MD5 (hex) — used only to reproduce the backend's
 * tool-call id scheme (`tc-<tool>-iter<i>-<md5(args)[:6]>`, agent_workspace.py /
 * chat.py `_tool_call_payload`) on the frontend, so the live trajectory
 * projection and the server-persisted record agree on tool ids byte-for-byte.
 *
 * This is NOT for security — it exists so one projection (`turnProjection.ts`)
 * can be a faithful mirror of the backend's `build_run_tree`. Classic
 * implementation (RFC 1321), operating on UTF-8 bytes to match Python's
 * `hashlib.md5(s.encode())`.
 */

function toUtf8Bytes(str: string): number[] {
  // Match Python's str.encode() (UTF-8).
  const out: number[] = [];
  for (let i = 0; i < str.length; i++) {
    let code = str.charCodeAt(i);
    if (code < 0x80) {
      out.push(code);
    } else if (code < 0x800) {
      out.push(0xc0 | (code >> 6), 0x80 | (code & 0x3f));
    } else if (code >= 0xd800 && code <= 0xdbff && i + 1 < str.length) {
      // Surrogate pair → single code point.
      const hi = code;
      const lo = str.charCodeAt(i + 1);
      code = 0x10000 + ((hi - 0xd800) << 10) + (lo - 0xdc00);
      out.push(
        0xf0 | (code >> 18),
        0x80 | ((code >> 12) & 0x3f),
        0x80 | ((code >> 6) & 0x3f),
        0x80 | (code & 0x3f),
      );
      i++;
    } else {
      out.push(0xe0 | (code >> 12), 0x80 | ((code >> 6) & 0x3f), 0x80 | (code & 0x3f));
    }
  }
  return out;
}

function add32(a: number, b: number): number {
  return (a + b) & 0xffffffff;
}

function rol(num: number, cnt: number): number {
  return (num << cnt) | (num >>> (32 - cnt));
}

function cmn(q: number, a: number, b: number, x: number, s: number, t: number): number {
  return add32(rol(add32(add32(a, q), add32(x, t)), s), b);
}

function ff(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return cmn((b & c) | (~b & d), a, b, x, s, t);
}
function gg(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return cmn((b & d) | (c & ~d), a, b, x, s, t);
}
function hh(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return cmn(b ^ c ^ d, a, b, x, s, t);
}
function ii(a: number, b: number, c: number, d: number, x: number, s: number, t: number): number {
  return cmn(c ^ (b | ~d), a, b, x, s, t);
}

function toWords(bytes: number[]): number[] {
  const n = bytes.length;
  const words: number[] = [];
  for (let i = 0; i < n; i++) {
    words[i >> 2] = (words[i >> 2] || 0) | (bytes[i] << ((i % 4) * 8));
  }
  return words;
}

/** MD5 hex digest of a string's UTF-8 bytes. */
export function md5Hex(input: string): string {
  const bytes = toUtf8Bytes(input);
  const n = bytes.length;
  const words = toWords(bytes);
  // Append the 0x80 padding bit.
  words[n >> 2] = (words[n >> 2] || 0) | (0x80 << ((n % 4) * 8));
  // Length in bits goes in the last two words of the padded message.
  const bitLenIndex = (((n + 8) >> 6) + 1) * 16 - 2;
  for (let i = (words.length); i <= bitLenIndex + 1; i++) words[i] = words[i] || 0;
  words[bitLenIndex] = n * 8;

  let a = 1732584193;
  let b = -271733879;
  let c = -1732584194;
  let d = 271733878;

  for (let i = 0; i < words.length; i += 16) {
    const olda = a;
    const oldb = b;
    const oldc = c;
    const oldd = d;
    const x = (j: number) => words[i + j] || 0;

    a = ff(a, b, c, d, x(0), 7, -680876936);
    d = ff(d, a, b, c, x(1), 12, -389564586);
    c = ff(c, d, a, b, x(2), 17, 606105819);
    b = ff(b, c, d, a, x(3), 22, -1044525330);
    a = ff(a, b, c, d, x(4), 7, -176418897);
    d = ff(d, a, b, c, x(5), 12, 1200080426);
    c = ff(c, d, a, b, x(6), 17, -1473231341);
    b = ff(b, c, d, a, x(7), 22, -45705983);
    a = ff(a, b, c, d, x(8), 7, 1770035416);
    d = ff(d, a, b, c, x(9), 12, -1958414417);
    c = ff(c, d, a, b, x(10), 17, -42063);
    b = ff(b, c, d, a, x(11), 22, -1990404162);
    a = ff(a, b, c, d, x(12), 7, 1804603682);
    d = ff(d, a, b, c, x(13), 12, -40341101);
    c = ff(c, d, a, b, x(14), 17, -1502002290);
    b = ff(b, c, d, a, x(15), 22, 1236535329);

    a = gg(a, b, c, d, x(1), 5, -165796510);
    d = gg(d, a, b, c, x(6), 9, -1069501632);
    c = gg(c, d, a, b, x(11), 14, 643717713);
    b = gg(b, c, d, a, x(0), 20, -373897302);
    a = gg(a, b, c, d, x(5), 5, -701558691);
    d = gg(d, a, b, c, x(10), 9, 38016083);
    c = gg(c, d, a, b, x(15), 14, -660478335);
    b = gg(b, c, d, a, x(4), 20, -405537848);
    a = gg(a, b, c, d, x(9), 5, 568446438);
    d = gg(d, a, b, c, x(14), 9, -1019803690);
    c = gg(c, d, a, b, x(3), 14, -187363961);
    b = gg(b, c, d, a, x(8), 20, 1163531501);
    a = gg(a, b, c, d, x(13), 5, -1444681467);
    d = gg(d, a, b, c, x(2), 9, -51403784);
    c = gg(c, d, a, b, x(7), 14, 1735328473);
    b = gg(b, c, d, a, x(12), 20, -1926607734);

    a = hh(a, b, c, d, x(5), 4, -378558);
    d = hh(d, a, b, c, x(8), 11, -2022574463);
    c = hh(c, d, a, b, x(11), 16, 1839030562);
    b = hh(b, c, d, a, x(14), 23, -35309556);
    a = hh(a, b, c, d, x(1), 4, -1530992060);
    d = hh(d, a, b, c, x(4), 11, 1272893353);
    c = hh(c, d, a, b, x(7), 16, -155497632);
    b = hh(b, c, d, a, x(10), 23, -1094730640);
    a = hh(a, b, c, d, x(13), 4, 681279174);
    d = hh(d, a, b, c, x(0), 11, -358537222);
    c = hh(c, d, a, b, x(3), 16, -722521979);
    b = hh(b, c, d, a, x(6), 23, 76029189);
    a = hh(a, b, c, d, x(9), 4, -640364487);
    d = hh(d, a, b, c, x(12), 11, -421815835);
    c = hh(c, d, a, b, x(15), 16, 530742520);
    b = hh(b, c, d, a, x(2), 23, -995338651);

    a = ii(a, b, c, d, x(0), 6, -198630844);
    d = ii(d, a, b, c, x(7), 10, 1126891415);
    c = ii(c, d, a, b, x(14), 15, -1416354905);
    b = ii(b, c, d, a, x(5), 21, -57434055);
    a = ii(a, b, c, d, x(12), 6, 1700485571);
    d = ii(d, a, b, c, x(3), 10, -1894986606);
    c = ii(c, d, a, b, x(10), 15, -1051523);
    b = ii(b, c, d, a, x(1), 21, -2054922799);
    a = ii(a, b, c, d, x(8), 6, 1873313359);
    d = ii(d, a, b, c, x(15), 10, -30611744);
    c = ii(c, d, a, b, x(6), 15, -1560198380);
    b = ii(b, c, d, a, x(13), 21, 1309151649);
    a = ii(a, b, c, d, x(4), 6, -145523070);
    d = ii(d, a, b, c, x(11), 10, -1120210379);
    c = ii(c, d, a, b, x(2), 15, 718787259);
    b = ii(b, c, d, a, x(9), 21, -343485551);

    a = add32(a, olda);
    b = add32(b, oldb);
    c = add32(c, oldc);
    d = add32(d, oldd);
  }

  const hex = (num: number): string => {
    let s = '';
    for (let j = 0; j < 4; j++) {
      s += ((num >> (j * 8)) & 0xff).toString(16).padStart(2, '0');
    }
    return s;
  };
  return hex(a) + hex(b) + hex(c) + hex(d);
}
