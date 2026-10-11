/** IV-10: the camera frames the face from its vertices at rest, not from its blend shapes. */
import * as THREE from "three";
import { expect, it } from "vitest";

import { restBox } from "./scene";

it("IV-10: blend shape offsets do not move or grow the framing box", () => {
  const geometry = new THREE.BoxGeometry(0.2, 0.3, 0.2);
  const offsets = new Float32Array(geometry.getAttribute("position").count * 3).fill(0);
  offsets[1] = -0.5; // one shape pulls a vertex far down, as a jaw shape moves the chin
  geometry.morphAttributes.position = [new THREE.BufferAttribute(offsets, 3)];
  geometry.morphTargetsRelative = true;
  const root = new THREE.Group().add(new THREE.Mesh(geometry));
  root.position.y = 1.6;

  expect(new THREE.Box3().setFromObject(root).min.y).toBeLessThan(1.0); // three.js counts the shape
  const box = restBox(root);
  expect(box.min.y).toBeCloseTo(1.45);
  expect(box.max.y).toBeCloseTo(1.75);
  expect((box.min.x + box.max.x) / 2).toBeCloseTo(0);
});
