/**
 * Converts a Microsoft Rocketbox avatar (MIT) into a small face-only GLB for the interviewer
 * avatar (IV-10). Run by hand, once per avatar; the output is committed under public/avatar/.
 *
 *   node scripts/avatar/convert-rocketbox.mjs <avatar folder> <output.glb>
 *
 * The folder holds <Name>_facial.fbx and the TGA textures of that avatar from
 * https://github.com/microsoft/Microsoft-Rocketbox (Assets/Avatars/Professions/<Name>).
 *
 * What it does:
 * - keeps the head, hair, eyelashes and glasses, and drops the body and clothes;
 * - keeps the 15 Oculus visemes and the ARKit shapes that scene.ts uses, renamed to the standard
 *   names (viseme_aa, jawOpen, ...);
 * - drops the skeleton: a "Head" node at the neck turns the whole face;
 * - shrinks the textures from 2048 px: the face to 1024 px JPEG, hair and glasses to 512 px PNG;
 * - welds, quantizes and compresses the mesh with Meshopt.
 */
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, join } from "node:path";

import { Document, NodeIO } from "@gltf-transform/core";
import { EXTMeshoptCompression, KHRMeshQuantization } from "@gltf-transform/extensions";
import { dedup, meshopt, prune, weld } from "@gltf-transform/functions";
import jpeg from "jpeg-js";
import { MeshoptEncoder } from "meshoptimizer";
import { PNG } from "pngjs";
import * as THREE from "three";
import { FBXLoader } from "three/addons/loaders/FBXLoader.js";
import { TGALoader } from "three/addons/loaders/TGALoader.js";

const [dir, out] = process.argv.slice(2);
if (!dir || !out) {
  console.error("usage: node scripts/avatar/convert-rocketbox.mjs <avatar folder> <output.glb>");
  process.exit(2);
}

// Rocketbox names, without the "blendShape1." prefix, to the names scene.ts reads.
const VISEMES = {
  AA_VI_00_Sil: "viseme_sil",
  AA_VI_01_PP: "viseme_PP",
  AA_VI_02_FF: "viseme_FF",
  AA_VI_03_TH: "viseme_TH",
  AA_VI_04_DD: "viseme_DD",
  AA_VI_05_KK: "viseme_kk",
  AA_VI_06_CH: "viseme_CH",
  AA_VI_07_SS: "viseme_SS",
  AA_VI_08_nn: "viseme_nn",
  AA_VI_09_RR: "viseme_RR",
  AA_VI_10_aa: "viseme_aa",
  AA_VI_11_E: "viseme_E",
  AA_VI_12_I: "viseme_I",
  AA_VI_13_O: "viseme_O",
  AA_VI_14_U: "viseme_U",
};
const ARKIT = [
  "BrowDownLeft", "BrowDownRight", "BrowInnerUp", "BrowOuterUpLeft", "BrowOuterUpRight",
  "CheekSquintLeft", "CheekSquintRight",
  "EyeBlinkLeft", "EyeBlinkRight",
  "EyeLookDownLeft", "EyeLookDownRight", "EyeLookInLeft", "EyeLookInRight",
  "EyeLookOutLeft", "EyeLookOutRight", "EyeLookUpLeft", "EyeLookUpRight",
  "EyeSquintLeft", "EyeSquintRight", "EyeWideLeft", "EyeWideRight",
  "JawOpen", "MouthClose", "MouthFunnel", "MouthPucker",
  "MouthPressLeft", "MouthPressRight", "MouthSmileLeft", "MouthSmileRight",
  "MouthStretchLeft", "MouthStretchRight",
];
const lowerFirst = (s) => s[0].toLowerCase() + s.slice(1);
function targetName(raw) {
  const name = raw.split(".").pop();
  if (VISEMES[name]) return VISEMES[name];
  const ak = /^AK_\d+_(.+)$/.exec(name);
  return ak && ARKIT.includes(ak[1]) ? lowerFirst(ak[1]) : null;
}

// ------------------------------------------------------------------------------ read the FBX

const files = readdirSync(dir);
const fbxFile = files.find((f) => f.endsWith("_facial.fbx"));
if (!fbxFile) throw new Error(`no *_facial.fbx in ${dir}`);

// The loader asks for each texture by file name; we read the TGA files ourselves later.
const manager = new THREE.LoadingManager();
const stub = {
  path: "",
  setPath(p) {
    this.path = p;
    return this;
  },
  load: (name) => Object.assign(new THREE.Texture(), { name }),
};
manager.addHandler(/\.tga$/i, stub);
const fbx = readFileSync(join(dir, fbxFile));
const root = new FBXLoader(manager).parse(fbx.buffer.slice(fbx.byteOffset, fbx.byteOffset + fbx.byteLength), "");
root.updateMatrixWorld(true);

let mesh;
root.traverse((o) => {
  if (o.isMesh && o.morphTargetDictionary) mesh = o;
});
if (!mesh) throw new Error("no mesh with blend shapes");
const neckBone = root.getObjectByName("Bip01_Neck");
if (!neckBone) throw new Error("no Bip01_Neck bone");

// Rocketbox is in centimetres; the GLB is in metres with the neck at the origin.
const toMetres = new THREE.Matrix4().makeScale(0.01, 0.01, 0.01);
const world = toMetres.clone().multiply(mesh.matrixWorld);
const linear = new THREE.Matrix3().setFromMatrix4(world);
const normalMatrix = new THREE.Matrix3().getNormalMatrix(world);
const pivot = neckBone.getWorldPosition(new THREE.Vector3()).applyMatrix4(toMetres);

const geo = mesh.geometry;
const pos = geo.attributes.position;
const nor = geo.attributes.normal;
const uv = geo.attributes.uv;
const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
const materialKind = (m) => {
  const n = m.name.toLowerCase();
  if (n.includes("glasses")) return "glasses";
  if (n.includes("opacity")) return "opacity";
  if (n.includes("head")) return "head";
  return "body";
};

const vertex = new THREE.Vector3();
// Keep the head, hair (with eyelashes) and glasses triangles. The body material holds the
// clothes and the body below the neck.
const keep = { head: [], opacity: [], glasses: [] };
const index = geo.index;
const corner = (t) => (index ? index.getX(t) : t);
for (const group of geo.groups) {
  const kind = materialKind(materials[group.materialIndex]);
  if (kind === "body") continue;
  for (let t = group.start; t < group.start + group.count; t++) keep[kind].push(corner(t));
}

// --------------------------------------------------------------------------------- textures

function readTga(file) {
  const buf = readFileSync(join(dir, file));
  // TGALoader returns RGBA rows from top to bottom, the order glTF images use.
  const { data, width, height } = new TGALoader().parse(buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength));
  return { data, width, height };
}

/** Halves the image until it is at most `max` px wide. */
function shrink({ data, width, height }, max) {
  let img = { data: Uint8Array.from(data), width, height };
  while (img.width > max) {
    const w = img.width >> 1;
    const h = img.height >> 1;
    const half = new Uint8Array(w * h * 4);
    for (let y = 0; y < h; y++)
      for (let x = 0; x < w; x++)
        for (let c = 0; c < 4; c++) {
          const at = (yy, xx) => img.data[((y * 2 + yy) * img.width + (x * 2 + xx)) * 4 + c];
          half[(y * w + x) * 4 + c] = (at(0, 0) + at(0, 1) + at(1, 0) + at(1, 1) + 2) >> 2;
        }
    img = { data: half, width: w, height: h };
  }
  return img;
}

const encodeJpeg = (img, quality) => jpeg.encode({ data: img.data, width: img.width, height: img.height }, quality).data;
function encodePng(img) {
  const png = new PNG({ width: img.width, height: img.height });
  png.data = Buffer.from(img.data);
  return PNG.sync.write(png);
}
const find = (suffix) => files.find((f) => f.toLowerCase().endsWith(suffix));

// ------------------------------------------------------------------------------- build glTF

const doc = new Document();
const buffer = doc.createBuffer();
const scene = doc.createScene("Interviewer");
const headNode = doc.createNode("Head").setTranslation(pivot.toArray());
const faceNode = doc.createNode("Face");
headNode.addChild(faceNode);
scene.addChild(doc.createNode("Avatar").addChild(headNode));
const gltfMesh = doc.createMesh("Face");
faceNode.setMesh(gltfMesh);

const shapeNames = [];
const shapeIndex = [];
for (const [raw, i] of Object.entries(mesh.morphTargetDictionary)) {
  const name = targetName(raw);
  if (name && !shapeNames.includes(name)) {
    shapeNames.push(name);
    shapeIndex.push(i);
  }
}

function texture(name, file, kind) {
  if (!file) return null;
  const img = shrink(readTga(file), kind === "png" ? 512 : 1024); // hair and glasses are small on screen
  const image = kind === "png" ? encodePng(img) : encodeJpeg(img, kind === "normal" ? 92 : 85);
  return doc.createTexture(name).setImage(new Uint8Array(image)).setMimeType(kind === "png" ? "image/png" : "image/jpeg");
}

const prefix = basename(find("_head_color.tga") ?? "").replace("_head_color.tga", "");
const headMat = doc
  .createMaterial("head")
  .setBaseColorTexture(texture("head_color", find("_head_color.tga"), "color"))
  .setNormalTexture(texture("head_normal", find("_head_normal.tga"), "normal"))
  .setRoughnessFactor(0.62)
  .setMetallicFactor(0);
const opacityMat = doc
  .createMaterial("hair")
  .setBaseColorTexture(texture("hair", files.find((f) => f === `${prefix}_opacity_color.tga`), "png"))
  .setAlphaMode("MASK")
  .setAlphaCutoff(0.35)
  .setDoubleSided(true)
  .setRoughnessFactor(0.7)
  .setMetallicFactor(0);
const glassesMat = doc
  .createMaterial("glasses")
  .setBaseColorTexture(texture("glasses", find("_glasses_opacity_color.tga"), "png"))
  .setAlphaMode("BLEND")
  .setDoubleSided(true)
  .setRoughnessFactor(0.25)
  .setMetallicFactor(0.3);

const morphPos = geo.morphAttributes.position;
const delta = new THREE.Vector3();
const normal = new THREE.Vector3();
for (const [kind, material] of [
  ["head", headMat],
  ["opacity", opacityMat],
  ["glasses", glassesMat],
]) {
  const corners = keep[kind];
  if (!corners.length) continue;
  const n = corners.length;
  const P = new Float32Array(n * 3);
  const N = new Float32Array(n * 3);
  const T = new Float32Array(n * 2);
  corners.forEach((src, k) => {
    vertex.fromBufferAttribute(pos, src).applyMatrix4(world).sub(pivot).toArray(P, k * 3);
    normal.fromBufferAttribute(nor, src).applyMatrix3(normalMatrix).normalize().toArray(N, k * 3);
    T[k * 2] = uv.getX(src);
    T[k * 2 + 1] = 1 - uv.getY(src); // glTF has the UV origin at the top left
  });
  const accessor = (array, type) => doc.createAccessor().setArray(array).setType(type).setBuffer(buffer);
  const prim = doc
    .createPrimitive()
    .setAttribute("POSITION", accessor(P, "VEC3"))
    .setAttribute("NORMAL", accessor(N, "VEC3"))
    .setAttribute("TEXCOORD_0", accessor(T, "VEC2"))
    .setMaterial(material);
  shapeIndex.forEach((i, s) => {
    const D = new Float32Array(n * 3);
    const src = morphPos[i];
    corners.forEach((c, k) => {
      delta.fromBufferAttribute(src, c);
      if (!geo.morphTargetsRelative) delta.sub(vertex.fromBufferAttribute(pos, c));
      delta.applyMatrix3(linear).toArray(D, k * 3);
    });
    // The writer takes mesh.extras.targetNames from these names; GLTFLoader reads them.
    prim.addTarget(doc.createPrimitiveTarget(shapeNames[s]).setAttribute("POSITION", accessor(D, "VEC3")));
  });
  gltfMesh.addPrimitive(prim);
}
gltfMesh.setWeights(new Array(shapeNames.length).fill(0));

doc.createExtension(KHRMeshQuantization).setRequired(true);
doc.createExtension(EXTMeshoptCompression).setRequired(true).setEncoderOptions({ method: EXTMeshoptCompression.EncoderMethod.QUANTIZE });
await MeshoptEncoder.ready;
await doc.transform(weld(), dedup(), prune(), meshopt({ encoder: MeshoptEncoder, level: "medium" }));

const io = new NodeIO().registerExtensions([KHRMeshQuantization, EXTMeshoptCompression]).registerDependencies({
  "meshopt.encoder": MeshoptEncoder,
});
const glb = await io.writeBinary(doc);
writeFileSync(out, glb);
const tris = Object.fromEntries(Object.entries(keep).map(([k, v]) => [k, v.length / 3]));
console.log(`${out}: ${(glb.byteLength / 1024).toFixed(0)} KB, ${shapeNames.length} shapes, triangles`, tris);
