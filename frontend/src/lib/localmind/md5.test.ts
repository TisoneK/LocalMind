import { describe, it, expect } from 'vitest';
import { md5Hex } from './md5';

// RFC 1321 / standard MD5 test vectors — proves md5Hex matches Python's
// hashlib.md5(s.encode()).hexdigest(), which the tool-id scheme depends on.
describe('md5Hex', () => {
  it('matches known vectors', () => {
    expect(md5Hex('')).toBe('d41d8cd98f00b204e9800998ecf8427e');
    expect(md5Hex('a')).toBe('0cc175b9c0f1b6a831c399e269772661');
    expect(md5Hex('abc')).toBe('900150983cd24fb0d6963f7d28e17f72');
    expect(md5Hex('message digest')).toBe('f96b697d7cb7938d525a2f31aaf161d0');
    expect(md5Hex('abcdefghijklmnopqrstuvwxyz')).toBe('c3fcd3d76192e4007dfb496cca67e13b');
    expect(md5Hex('The quick brown fox jumps over the lazy dog')).toBe(
      '9e107d9d372bb6826bd81d3542a419d6',
    );
  });

  it('handles UTF-8 like Python str.encode()', () => {
    // md5('café'.encode()) == md5(b'caf\xc3\xa9')
    expect(md5Hex('café')).toBe('07117fe4a1ebd544965dc19573183da2');
  });

  it('produces the 6-char prefix the tool-id scheme uses', () => {
    // tc id uses hexdigest()[:6] of the tool_args string.
    expect(md5Hex('{"path": "notes.txt"}').slice(0, 6)).toHaveLength(6);
  });
});
