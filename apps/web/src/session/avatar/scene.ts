/**
 * The 3D interviewer (three.js, MIT). It loads a GLB head from `modelUrl` when the file exists,
 * else it draws a plain built-in head. Either way the face blinks, looks around a little, follows
 * the agent's activity, and moves its mouth from the lip-sync pose.
 *
 * A GLB model needs blend shapes: Oculus visemes (viseme_aa ...) or ARKit (jawOpen, eyeBlinkLeft
 * ...). Bones named Head and Neck are turned for head movement when they exist.
 */
import * as THREE from "three";

import type { AgentActivity } from "../voice";
import type { LipSync } from "./lipsync";
import { REST_POSE, arkitFromPose, easePose, type MouthPose } from "./visemes";

/** Vertical field of view in degrees. Narrow, like a portrait lens, so the face is not distorted. */
const CAMERA_FOV = 24;

export interface AvatarScene {
  setActivity: (activity: AgentActivity) => void;
  setLipSync: (lipSync: LipSync | null) => void;
  dispose: () => void;
}

export interface AvatarOptions {
  modelUrl: string;
  reducedMotion: boolean;
}

/** One face, whatever it was built from. Values are 0..1. */
interface Face {
  root: THREE.Object3D;
  /** The point the camera looks at, in world space. */
  focus: THREE.Vector3;
  /** Distance from the focus to the camera. */
  distance: number;
  setMouth: (pose: MouthPose) => void;
  setBlink: (closed: number) => void;
  /** x: left (-) to right (+), y: down (-) to up (+), in radians. */
  setGaze: (x: number, y: number) => void;
  setBrows: (raise: number) => void;
  /** Head turn in radians: yaw (left/right), pitch (nod), roll (tilt). */
  setHead: (yaw: number, pitch: number, roll: number) => void;
  dispose: () => void;
}

export async function createAvatarScene(canvas: HTMLCanvasElement, options: AvatarOptions): Promise<AvatarScene> {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  renderer.toneMapping = THREE.ACESFilmicToneMapping;

  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(CAMERA_FOV, 1, 0.05, 50);
  scene.add(new THREE.HemisphereLight(0xdfe8f2, 0x2c3746, 1.4));
  const key = new THREE.DirectionalLight(0xffffff, 2.2);
  key.position.set(1.2, 1.6, 2.4);
  const rim = new THREE.DirectionalLight(0xf0a92e, 0.8); // the practice amber, from behind
  rim.position.set(-1.6, 1.2, -1.8);
  scene.add(key, rim);

  const face = (await loadModelFace(options.modelUrl)) ?? builtInFace();
  scene.add(face.root);
  camera.position.copy(face.focus).add(new THREE.Vector3(0, 0.02, face.distance));
  camera.lookAt(face.focus);

  const resize = () => {
    const { clientWidth: w, clientHeight: h } = canvas;
    if (!w || !h) return;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  };
  const observer = new ResizeObserver(resize);
  observer.observe(canvas);
  resize();

  let activity: AgentActivity = "idle";
  let lipSync: LipSync | null = null;
  let mouth = REST_POSE;
  let blinkAt = performance.now() + 1500;
  let gaze = { x: 0, y: 0, tx: 0, ty: 0, nextAt: 0 };
  let brows = 0;
  let last = performance.now();
  let frame = 0;
  const motion = options.reducedMotion ? 0 : 1;

  const tick = (now: number) => {
    frame = requestAnimationFrame(tick);
    const dt = Math.min(100, now - last);
    last = now;
    const t = now / 1000;

    // Mouth: lip sync while speaking. Without audio (mock voice) a soft talking rhythm.
    let target = REST_POSE;
    if (activity === "speaking") {
      target = lipSync
        ? lipSync.pose(dt)
        : { ...REST_POSE, open: 0.25 + 0.35 * Math.abs(Math.sin(t * 9) * Math.sin(t * 3.7)), wide: 0.3 };
    } else {
      lipSync?.pose(dt); // keeps HeadAudio's easing in step
    }
    mouth = easePose(mouth, target, dt);
    face.setMouth(mouth);

    // Blink every 2 to 5 seconds, 160 ms each.
    const sinceBlink = now - blinkAt;
    face.setBlink(sinceBlink >= 0 && sinceBlink < 160 ? Math.sin((sinceBlink / 160) * Math.PI) : 0);
    if (sinceBlink >= 160) blinkAt = now + 2000 + Math.random() * 3000;

    // Gaze: mostly at the candidate. Thinking looks up and to the side.
    if (now > gaze.nextAt) {
      const away = activity === "thinking" ? 1 : activity === "speaking" ? 0.35 : 0.15;
      const look = Math.random() < away;
      gaze = {
        ...gaze,
        tx: look ? (Math.random() - 0.5) * 0.4 : 0,
        ty: activity === "thinking" ? 0.18 : look ? (Math.random() - 0.5) * 0.12 : 0,
        nextAt: now + 800 + Math.random() * 1800,
      };
    }
    const g = 1 - Math.pow(0.75, dt / 16);
    gaze.x += (gaze.tx - gaze.x) * g;
    gaze.y += (gaze.ty - gaze.y) * g;
    face.setGaze(gaze.x, gaze.y);
    brows += ((activity === "thinking" ? 0.6 : activity === "speaking" ? mouth.open * 0.3 : 0) - brows) * g * 0.5;
    face.setBrows(brows);

    // Head: slow breathing sway, small nods while speaking, a tilt while listening.
    const speakNod = activity === "speaking" ? 0.035 * Math.sin(t * 2.3) + 0.03 * mouth.open : 0;
    const tilt = activity === "listening" ? 0.06 : 0;
    face.setHead(
      motion * (0.04 * Math.sin(t * 0.37) + gaze.x * 0.25),
      motion * (0.015 * Math.sin(t * 0.9) + speakNod - gaze.y * 0.2),
      motion * (tilt + 0.012 * Math.sin(t * 0.5)),
    );

    renderer.render(scene, camera);
  };
  frame = requestAnimationFrame(tick);

  return {
    setActivity: (a) => {
      activity = a;
      gaze.nextAt = 0;
    },
    setLipSync: (l) => {
      lipSync = l;
    },
    dispose: () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      face.dispose();
      renderer.dispose();
    },
  };
}

// ------------------------------------------------------------------------------- GLB model

async function loadModelFace(url: string): Promise<Face | null> {
  if (!url) return null;
  // Without the file, the web server answers with the app's index.html, so check the type first.
  const response = await fetch(url).catch(() => null);
  if (!response?.ok || (response.headers.get("content-type") ?? "").includes("text/html")) return null;
  const [{ GLTFLoader }, { MeshoptDecoder }] = await Promise.all([
    import("three/addons/loaders/GLTFLoader.js"),
    import("three/addons/libs/meshopt_decoder.module.js"),
  ]);
  let gltf: Awaited<ReturnType<InstanceType<typeof GLTFLoader>["parseAsync"]>>;
  try {
    gltf = await new GLTFLoader().setMeshoptDecoder(MeshoptDecoder).parseAsync(await response.arrayBuffer(), new URL(".", new URL(url, location.href)).href);
  } catch {
    return null; // not a GLB: use the built-in head
  }
  const root = gltf.scene;
  const morphs: THREE.Mesh[] = [];
  root.traverse((o) => {
    if (o instanceof THREE.Mesh && o.morphTargetDictionary && o.morphTargetInfluences) morphs.push(o);
  });
  if (!morphs.length) return null;

  // Some exporters prefix the names, for example "blendShape1.jawOpen".
  const targets = new Map<string, { influences: number[]; index: number }[]>();
  for (const m of morphs) {
    for (const [key, index] of Object.entries(m.morphTargetDictionary ?? {})) {
      const name = key.split(".").pop() ?? key;
      targets.set(name, [...(targets.get(name) ?? []), { influences: m.morphTargetInfluences!, index }]);
    }
  }
  const set = (name: string, value: number) => {
    for (const t of targets.get(name) ?? []) t.influences[t.index] = value;
  };
  const has = (name: string) => targets.has(name);
  const hasVisemes = has("viseme_aa");

  const headBone = root.getObjectByName("Head");
  const neckBone = root.getObjectByName("Neck");
  const turn = headBone ?? root;
  const rest = turn.quaternion.clone();
  const neckRest = neckBone?.quaternion.clone();

  // Frame the top of the model: the face and a little neck. A face-only model (convert-rocketbox)
  // fits whole; a full body shows from the chest up.
  root.updateMatrixWorld(true);
  const box = restBox(root);
  const size = box.getSize(new THREE.Vector3());
  const shown = Math.min(size.y * 1.04, 0.42);
  const focus = new THREE.Vector3((box.min.x + box.max.x) / 2, box.max.y - shown * 0.5, (box.min.z + box.max.z) / 2);
  const distance = (shown * 0.5) / Math.tan(THREE.MathUtils.degToRad(CAMERA_FOV / 2)) + size.z / 2;

  const euler = new THREE.Euler();
  const q = new THREE.Quaternion();
  return {
    root,
    focus,
    distance,
    setMouth: (pose) => {
      if (hasVisemes) {
        set("viseme_aa", pose.open * (1 - pose.round) * 0.8);
        set("viseme_O", pose.round * pose.open);
        set("viseme_U", pose.round * (1 - pose.open));
        set("viseme_I", pose.wide * (1 - pose.open) * 0.6);
        set("viseme_E", pose.wide * pose.open * 0.6);
        set("viseme_PP", pose.closed);
      } else {
        for (const [name, value] of Object.entries(arkitFromPose(pose))) set(name, value);
      }
    },
    setBlink: (closed) => {
      if (has("eyeBlinkLeft")) {
        set("eyeBlinkLeft", closed);
        set("eyeBlinkRight", closed);
      } else set("eyesClosed", closed);
    },
    setGaze: (x, y) => {
      set("eyeLookOutLeft", Math.max(0, -x) * 2);
      set("eyeLookInRight", Math.max(0, -x) * 2);
      set("eyeLookInLeft", Math.max(0, x) * 2);
      set("eyeLookOutRight", Math.max(0, x) * 2);
      set("eyeLookUpLeft", Math.max(0, y) * 3);
      set("eyeLookUpRight", Math.max(0, y) * 3);
      set("eyeLookDownLeft", Math.max(0, -y) * 3);
      set("eyeLookDownRight", Math.max(0, -y) * 3);
    },
    setBrows: (raise) => {
      set("browInnerUp", raise * 0.6);
      set("browOuterUpLeft", raise * 0.3);
      set("browOuterUpRight", raise * 0.3);
    },
    setHead: (yaw, pitch, roll) => {
      const share = neckBone && neckRest ? 0.6 : 1;
      turn.quaternion.copy(rest).multiply(q.setFromEuler(euler.set(pitch * share, yaw * share, roll * share)));
      if (neckBone && neckRest) {
        neckBone.quaternion.copy(neckRest).multiply(q.setFromEuler(euler.set(pitch * 0.4, yaw * 0.4, roll * 0.4)));
      }
    },
    dispose: () => disposeTree(root),
  };
}

/**
 * The box around the model's vertices at rest. Box3.setFromObject also grows the box by every
 * blend shape offset (three.js adds the morph targets), which made a face model look off-center.
 */
export function restBox(root: THREE.Object3D): THREE.Box3 {
  const box = new THREE.Box3();
  const v = new THREE.Vector3();
  root.updateMatrixWorld(true);
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    const position = o.geometry.getAttribute("position");
    for (let i = 0; i < position.count; i++) box.expandByPoint(v.fromBufferAttribute(position, i).applyMatrix4(o.matrixWorld));
  });
  return box;
}

// --------------------------------------------------------------------------- built-in head

/** A plain, friendly head made of simple shapes. Used until a real model file is added. */
function builtInFace(): Face {
  const root = new THREE.Group();
  const head = new THREE.Group();
  head.position.set(0, 1.6, 0);
  root.add(head);

  const mat = (color: number, roughness = 0.7) => new THREE.MeshStandardMaterial({ color, roughness });
  const skin = mat(0xc98f6b, 0.6);
  const dark = mat(0x2a2522, 0.85);
  const white = mat(0xf4f1ec, 0.4);
  const iris = mat(0x3b2a20, 0.3);
  const mouthInside = mat(0x4a1f1f, 0.9);
  const lip = mat(0xa8625a, 0.55);
  const suit = mat(0x3a4f63, 0.8);
  const shirt = mat(0xf3f6f8, 0.7);

  const add = (parent: THREE.Object3D, mesh: THREE.Mesh, x: number, y: number, z: number) => {
    mesh.position.set(x, y, z);
    parent.add(mesh);
    return mesh;
  };

  // Shoulders, collar and neck do not turn with the head.
  const shoulders = add(root, new THREE.Mesh(new THREE.SphereGeometry(0.3, 40, 24), suit), 0, 1.27, -0.02);
  shoulders.scale.set(1.2, 0.55, 0.6);
  const collar = add(root, new THREE.Mesh(new THREE.ConeGeometry(0.045, 0.07, 3), shirt), 0, 1.415, 0.105);
  collar.rotation.set(Math.PI, 0, 0);
  add(root, new THREE.Mesh(new THREE.CylinderGeometry(0.038, 0.048, 0.12, 24), skin), 0, 1.46, -0.01);

  const skull = add(head, new THREE.Mesh(new THREE.SphereGeometry(0.1, 48, 32), skin), 0, 0.02, 0);
  skull.scale.set(0.9, 1.18, 1);
  const hair = add(
    head,
    new THREE.Mesh(new THREE.SphereGeometry(0.104, 48, 24, 0, Math.PI * 2, 0, Math.PI * 0.42), dark),
    0,
    0.035,
    -0.006,
  );
  hair.scale.set(0.92, 1.12, 1.02);
  hair.rotation.x = -0.35;
  for (const side of [-1, 1]) {
    const ear = add(head, new THREE.Mesh(new THREE.SphereGeometry(0.018, 16, 12), skin), side * 0.09, 0.01, -0.005);
    ear.scale.set(0.5, 1.2, 0.8);
  }
  const nose = add(head, new THREE.Mesh(new THREE.SphereGeometry(0.014, 16, 12), skin), 0, -0.005, 0.098);
  nose.scale.set(0.9, 1.4, 1);

  // Eyes: each is a group, so gaze turns the iris and blinks squash the whole eye.
  const eyes: THREE.Group[] = [];
  const brows: THREE.Mesh[] = [];
  for (const side of [-1, 1]) {
    const eye = new THREE.Group();
    eye.position.set(side * 0.034, 0.03, 0.084);
    head.add(eye);
    add(eye, new THREE.Mesh(new THREE.SphereGeometry(0.014, 24, 16), white), 0, 0, 0).scale.set(1.2, 0.85, 0.6);
    add(eye, new THREE.Mesh(new THREE.SphereGeometry(0.0072, 20, 14), iris), 0, 0, 0.0075).scale.set(1, 1, 0.5);
    eyes.push(eye);
    const brow = add(head, new THREE.Mesh(new THREE.BoxGeometry(0.03, 0.005, 0.006), dark), side * 0.035, 0.052, 0.088);
    brow.rotation.z = side * -0.12;
    brows.push(brow);
  }

  // Mouth: a dark opening inside a lip ring. Both scale with the pose.
  const mouth = new THREE.Group();
  mouth.position.set(0, -0.045, 0.091);
  mouth.rotation.x = -0.2;
  head.add(mouth);
  const opening = add(mouth, new THREE.Mesh(new THREE.CircleGeometry(0.02, 32), mouthInside), 0, 0, 0);
  const lips = add(mouth, new THREE.Mesh(new THREE.TorusGeometry(0.02, 0.0045, 10, 40), lip), 0, 0, 0.001);

  return {
    root,
    focus: new THREE.Vector3(0, 1.55, 0),
    distance: 1.25,
    setMouth: (p) => {
      const sx = 1 + p.wide * 0.35 - p.round * 0.35;
      const sy = 0.12 + p.open * 0.75 + p.round * 0.25 - p.closed * 0.1;
      opening.scale.set(sx, Math.max(0.05, sy), 1);
      lips.scale.set(sx, Math.max(0.2, sy), 1);
    },
    setBlink: (closed) => eyes.forEach((e) => e.scale.set(1, Math.max(0.08, 1 - closed), 1)),
    setGaze: (x, y) => eyes.forEach((e) => e.rotation.set(-y, x, 0)),
    setBrows: (raise) => brows.forEach((b) => (b.position.y = 0.052 + raise * 0.008)),
    setHead: (yaw, pitch, roll) => head.rotation.set(pitch, yaw, roll),
    dispose: () => disposeTree(root),
  };
}

function disposeTree(root: THREE.Object3D) {
  root.traverse((o) => {
    if (!(o instanceof THREE.Mesh)) return;
    o.geometry.dispose();
    for (const m of Array.isArray(o.material) ? o.material : [o.material]) m.dispose();
  });
}
