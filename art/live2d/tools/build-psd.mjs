// Re-encodes existing RGBA pixels as PSD layers without retouching or resizing.
// Artwork alignment and motion authoring belong in Cubism, not this serializer.
import fs from 'node:fs';
import path from 'node:path';
import zlib from 'node:zlib';

const u16 = value => { const b = Buffer.alloc(2); b.writeUInt16BE(value); return b; };
const i16 = value => { const b = Buffer.alloc(2); b.writeInt16BE(value); return b; };
const u32 = value => { const b = Buffer.alloc(4); b.writeUInt32BE(value); return b; };
const i32 = value => { const b = Buffer.alloc(4); b.writeInt32BE(value); return b; };
const ascii = value => Buffer.from(value, 'ascii');
const section = bytes => Buffer.concat([u32(bytes.length), bytes]);

function paeth(a, b, c) {
  const p = a + b - c, pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
  return pa <= pb && pa <= pc ? a : pb <= pc ? b : c;
}

function readRgbaPng(file) {
  const png = fs.readFileSync(file);
  if (!png.subarray(0, 8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) throw new Error(`Not a PNG: ${file}`);
  let width, height, channels;
  const compressed = [];
  for (let offset = 8; offset + 12 <= png.length;) {
    const size = png.readUInt32BE(offset), type = png.toString('ascii', offset + 4, offset + 8);
    if (offset + size + 12 > png.length) throw new Error(`Truncated PNG: ${file}`);
    const data = png.subarray(offset + 8, offset + 8 + size);
    if (type === 'IHDR') {
      width = data.readUInt32BE(0); height = data.readUInt32BE(4);
      if (data[8] !== 8 || ![2,6].includes(data[9]) || data[10] || data[11] || data[12]) throw new Error(`Expected non-interlaced 8-bit RGB/RGBA PNG: ${file}`);
      channels = data[9] === 6 ? 4 : 3;
      if (!width || !height || width > 4096 || height > 4096) throw new Error(`Unsupported image dimensions: ${file}`);
    } else if (type === 'IDAT') compressed.push(data);
    offset += size + 12;
    if (type === 'IEND') break;
  }
  if (!channels) throw new Error(`Missing PNG header: ${file}`);
  const stride = width * channels, rows = zlib.inflateSync(Buffer.concat(compressed));
  if (rows.length !== (stride + 1) * height) throw new Error(`Unexpected PNG scanline size: ${file}`);
  const decoded = Buffer.alloc(stride * height);
  for (let y = 0; y < height; y++) {
    const filter = rows[y * (stride + 1)];
    if (filter > 4) throw new Error(`Unsupported PNG filter: ${file}`);
    for (let x = 0; x < stride; x++) {
      const at = y * stride + x, left = x >= channels ? decoded[at - channels] : 0;
      const up = y ? decoded[at - stride] : 0, upperLeft = y && x >= channels ? decoded[at - stride - channels] : 0;
      const prediction = [0, left, up, Math.floor((left + up) / 2), paeth(left, up, upperLeft)][filter];
      decoded[at] = (rows[y * (stride + 1) + x + 1] + prediction) & 255;
    }
  }
  const planes = Array.from({length:4}, () => Buffer.alloc(width * height));
  for (let pixel = 0; pixel < width * height; pixel++) {
    for (let channel = 0; channel < 3; channel++) planes[channel][pixel] = decoded[pixel * channels + channel];
    planes[3][pixel] = channels === 4 ? decoded[pixel * channels + 3] : 255;
  }
  return {width, height, planes};
}

function layerRecord(layer) {
  const {image, name, visible = true, left = 0, top = 0} = layer;
  const title = ascii(name);
  if (!title.length || title.length > 255 || !/^[\x20-\x7e]+$/.test(name)) throw new Error('Layer names must be short ASCII identifiers.');
  const pascal = Buffer.concat([Buffer.from([title.length]), title, Buffer.alloc((4 - (title.length + 1) % 4) % 4)]);
  const extra = Buffer.concat([u32(0), u32(0), pascal]);
  return Buffer.concat([
    i32(top), i32(left), i32(top + image.height), i32(left + image.width), u16(4),
    ...[0,1,2,-1].map((id, index) => Buffer.concat([i16(id), u32(image.planes[index].length + 2)])),
    ascii('8BIMnorm'), Buffer.from([255, 0, visible ? 0 : 2, 0]), section(extra),
  ]);
}

const manifestPath = path.resolve(process.argv[2] || 'art/live2d/human-v1/source.json');
const manifest = JSON.parse(fs.readFileSync(manifestPath, 'utf8')), base = path.dirname(manifestPath);
const layers = manifest.layers.map(layer => ({...layer, image:readRgbaPng(path.resolve(base, layer.file))}));
const composite = readRgbaPng(path.resolve(base, manifest.reference));
if (composite.width !== manifest.width || composite.height !== manifest.height) throw new Error('Reference dimensions do not match canvas.');
if (!layers.length || layers.length > 100) throw new Error('Expected 1 to 100 artwork layers.');
let layerInfo = Buffer.concat([
  i16(-layers.length), ...layers.map(layerRecord),
  ...layers.flatMap(layer => layer.image.planes.map(plane => Buffer.concat([u16(0), plane]))),
]);
if (layerInfo.length % 2) layerInfo = Buffer.concat([layerInfo, Buffer.alloc(1)]);
const header = Buffer.concat([ascii('8BPS'), u16(1), Buffer.alloc(6), u16(4), u32(manifest.height), u32(manifest.width), u16(8), u16(3)]);
const psd = Buffer.concat([header, u32(0), u32(0), section(Buffer.concat([section(layerInfo), u32(0)])), u16(0), ...composite.planes]);
const output = path.resolve(base, manifest.output);
fs.writeFileSync(output, psd);
console.log(JSON.stringify({output, width:manifest.width, height:manifest.height, layers:layers.map(({name, visible = true})=>({name,visible})), bytes:psd.length}));
