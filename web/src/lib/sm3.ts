/**
 * SM3 国密摘要（浏览器端实现）——与后端/Java 逐字节一致。
 * 登录协议：password = sm3_hex(明文)，明文不出浏览器。
 */

const IV = [
  0x7380166f, 0x4914b2b9, 0x172442d7, 0xda8a0600,
  0xa96f30bc, 0x163138aa, 0xe38dee4d, 0xb0fb0e4e,
]

const rotl = (x: number, n: number): number => ((x << n) | (x >>> (32 - n))) >>> 0
const tJ = (j: number): number => (j < 16 ? 0x79cc4519 : 0x7a879d8a)

function ff(j: number, x: number, y: number, z: number): number {
  return j < 16 ? x ^ y ^ z : (x & y) | (x & z) | (y & z)
}
function gg(j: number, x: number, y: number, z: number): number {
  return j < 16 ? x ^ y ^ z : (x & y) | (~x & z)
}
const p0 = (x: number): number => x ^ rotl(x, 9) ^ rotl(x, 17)
const p1 = (x: number): number => x ^ rotl(x, 15) ^ rotl(x, 23)

function cf(v: number[], b: number[]): number[] {
  const w = b.slice()
  for (let j = 16; j < 68; j++) {
    w.push((p1(w[j - 16] ^ w[j - 9] ^ rotl(w[j - 3], 15)) ^ rotl(w[j - 13], 7) ^ w[j - 6]) >>> 0)
  }
  const w1: number[] = []
  for (let j = 0; j < 64; j++) w1.push((w[j] ^ w[j + 4]) >>> 0)

  let [a, bb, c, d, e, f, g, h] = v
  for (let j = 0; j < 64; j++) {
    const ss1 = rotl((rotl(a, 12) + e + rotl(tJ(j), j % 32)) >>> 0, 7)
    const ss2 = ss1 ^ rotl(a, 12)
    const tt1 = (ff(j, a, bb, c) + d + ss2 + w1[j]) >>> 0
    const tt2 = (gg(j, e, f, g) + h + ss1 + w[j]) >>> 0
    d = c
    c = rotl(bb, 9)
    bb = a
    a = tt1
    h = g
    g = rotl(f, 19)
    f = e
    e = p0(tt2)
  }
  const out = [a, bb, c, d, e, f, g, h]
  return v.map((x, i) => (x ^ out[i]) >>> 0)
}

export function sm3Hex(text: string): string {
  const data = new TextEncoder().encode(text)
  const padLen = (56 - ((data.length + 1) % 64)) % 64
  const padded = new Uint8Array(data.length + 1 + padLen + 8)
  padded.set(data)
  padded[data.length] = 0x80
  const bitLen = data.length * 8
  const dv = new DataView(padded.buffer)
  dv.setUint32(padded.length - 4, bitLen >>> 0)
  dv.setUint32(padded.length - 8, Math.floor(bitLen / 0x100000000))

  let v = IV.slice()
  for (let i = 0; i < padded.length; i += 64) {
    const block: number[] = []
    for (let k = 0; k < 16; k++) block.push(dv.getUint32(i + k * 4))
    v = cf(v, block)
  }
  return v.map((x) => x.toString(16).padStart(8, '0')).join('')
}
