import * as THREE from "three";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

const canvas = document.querySelector("#viewport-canvas");
const viewport = document.querySelector(".viewport");
const editor = document.querySelector("#document");
const modelInput = document.querySelector("#model-id");
const revisionLabel = document.querySelector("#revision");
const statusLabel = document.querySelector("#status");
const connection = document.querySelector("#connection");
const errorBox = document.querySelector("#error");
const applyButton = document.querySelector("#apply");
const emptyState = document.querySelector("#empty-state");
const assetCount = document.querySelector("#asset-count");
const sceneQuality = document.querySelector("#scene-quality");
const sceneTime = document.querySelector("#scene-time");
const lineCount = document.querySelector("#line-count");
const edgeButton = document.querySelector("#toggle-edges");

const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
renderer.outputColorSpace = THREE.SRGBColorSpace;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;

const scene = new THREE.Scene();
scene.background = new THREE.Color(0xe7e8e9);
const camera = new THREE.PerspectiveCamera(42, 1, 0.001, 1000);
camera.position.set(0.16, 0.12, 0.18);
const controls = new OrbitControls(camera, canvas);
controls.enableDamping = true;
controls.dampingFactor = 0.07;
controls.target.set(0, 0.02, 0);

scene.add(new THREE.HemisphereLight(0xffffff, 0x6b7072, 2.1));
const keyLight = new THREE.DirectionalLight(0xffffff, 2.6);
keyLight.position.set(3, 5, 4);
scene.add(keyLight);
const fillLight = new THREE.DirectionalLight(0xffe8d3, 1.1);
fillLight.position.set(-4, 2, -3);
scene.add(fillLight);
const grid = new THREE.GridHelper(2, 40, 0x9ca0a3, 0xc9cbcd);
grid.material.transparent = true;
grid.material.opacity = 0.65;
scene.add(grid);

const loader = new GLTFLoader();
let modelRoot = new THREE.Group();
scene.add(modelRoot);
let expectedRevision = 0;
let latestRevision = -1;
let latestBuild = -1;
let selectedQuality = "draft";
let eventSource = null;
let hasFramed = false;
let edgesVisible = true;

function setStatus(text, state = "") {
  statusLabel.textContent = text;
  connection.className = `connection ${state}`.trim();
}

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = !message;
}

function updateLineCount() {
  lineCount.textContent = String(editor.value ? editor.value.split("\n").length : 0);
}

function resizeRenderer() {
  const width = Math.max(1, viewport.clientWidth);
  const height = Math.max(1, viewport.clientHeight);
  renderer.setSize(width, height, false);
  camera.aspect = width / height;
  camera.updateProjectionMatrix();
}

new ResizeObserver(resizeRenderer).observe(viewport);
resizeRenderer();

function render() {
  controls.update();
  renderer.render(scene, camera);
  requestAnimationFrame(render);
}
render();

function fitView() {
  const bounds = new THREE.Box3().setFromObject(modelRoot);
  if (bounds.isEmpty()) return;
  const center = bounds.getCenter(new THREE.Vector3());
  const size = bounds.getSize(new THREE.Vector3());
  const radius = Math.max(size.length() * 0.5, 0.01);
  const direction = camera.position.clone().sub(controls.target).normalize();
  const halfVerticalFov = THREE.MathUtils.degToRad(camera.fov / 2);
  const verticalDistance = radius / Math.tan(halfVerticalFov);
  const horizontalDistance = radius / (
    Math.tan(halfVerticalFov) * Math.max(camera.aspect, 0.01)
  );
  const distance = Math.max(verticalDistance, horizontalDistance) * 1.35;
  camera.position.copy(center).add(direction.multiplyScalar(distance));
  camera.near = Math.max(radius / 500, 0.0001);
  camera.far = Math.max(radius * 100, 10);
  camera.updateProjectionMatrix();
  controls.target.copy(center);
  controls.update();
}

function multiply3(a, b) {
  const result = Array.from({ length: 3 }, () => [0, 0, 0]);
  for (let row = 0; row < 3; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      for (let index = 0; index < 3; index += 1) {
        result[row][column] += a[row][index] * b[index][column];
      }
    }
  }
  return result;
}

function placementMatrix(placement) {
  const x = placement.x_axis;
  const y = placement.y_axis;
  const z = placement.z_axis;
  const cadRotation = [
    [x[0], y[0], z[0]],
    [x[1], y[1], z[1]],
    [x[2], y[2], z[2]],
  ];
  const convert = [[1, 0, 0], [0, 0, 1], [0, -1, 0]];
  const convertInverse = [[1, 0, 0], [0, 0, -1], [0, 1, 0]];
  const rotation = multiply3(multiply3(convert, cadRotation), convertInverse);
  const origin = placement.origin;
  const translation = [origin[0] / 1000, origin[2] / 1000, -origin[1] / 1000];
  return new THREE.Matrix4().set(
    rotation[0][0], rotation[0][1], rotation[0][2], translation[0],
    rotation[1][0], rotation[1][1], rotation[1][2], translation[1],
    rotation[2][0], rotation[2][1], rotation[2][2], translation[2],
    0, 0, 0, 1,
  );
}

function loadGlb(url) {
  return new Promise((resolve, reject) => {
    loader.load(url, (gltf) => resolve(gltf.scene), undefined, reject);
  });
}

function styleGeometry(root) {
  root.traverse((object) => {
    if (object.isMesh) {
      object.material = new THREE.MeshStandardMaterial({
        color: 0xbfc5c8,
        roughness: 0.48,
        metalness: 0.18,
        side: THREE.DoubleSide,
      });
    }
  });
}

function styleEdges(root) {
  root.name = "cadflow-edges";
  root.traverse((object) => {
    if (object.isLine || object.isLineSegments) {
      object.material = new THREE.LineBasicMaterial({ color: 0x35393c });
      object.renderOrder = 2;
    }
  });
}

function disposeRoot(root) {
  root.traverse((object) => {
    if (object.geometry) object.geometry.dispose();
    if (Array.isArray(object.material)) {
      object.material.forEach((material) => material.dispose());
    } else if (object.material) {
      object.material.dispose();
    }
  });
}

async function loadScene(preview) {
  if (preview.revision < latestRevision) return;
  if (preview.revision === latestRevision && preview.build <= latestBuild) return;
  const manifestUrl = new URL(preview.manifest, window.location.origin);
  const response = await fetch(manifestUrl, { cache: "no-store" });
  if (!response.ok) throw new Error(`Scene manifest returned ${response.status}`);
  const manifest = await response.json();
  const baseUrl = new URL(".", manifestUrl);
  const definitions = new Map(manifest.definitions.map((item) => [item.definition_id, item]));
  const geometryAssets = new Map(manifest.geometry_assets.map((item) => [item.asset_id, item]));
  const edgeAssets = new Map(manifest.edge_assets.map((item) => [item.asset_id, item]));
  const definitionScenes = new Map();

  await Promise.all(Array.from(definitions.values()).map(async (definition) => {
    const group = new THREE.Group();
    const geometry = geometryAssets.get(definition.geometry_asset_id);
    const edges = edgeAssets.get(definition.edge_asset_id);
    if (geometry) {
      const geometryRoot = await loadGlb(new URL(geometry.uri, baseUrl).href);
      styleGeometry(geometryRoot);
      group.add(geometryRoot);
    }
    if (edges) {
      const edgeRoot = await loadGlb(new URL(edges.uri, baseUrl).href);
      styleEdges(edgeRoot);
      edgeRoot.visible = edgesVisible;
      group.add(edgeRoot);
    }
    definitionScenes.set(definition.definition_id, group);
  }));

  const nextRoot = new THREE.Group();
  const nodeGroups = new Map();
  for (const node of manifest.nodes) {
    const group = new THREE.Group();
    group.name = node.node_id;
    group.matrixAutoUpdate = false;
    group.matrix.copy(placementMatrix(node.transform));
    const definitionScene = definitionScenes.get(node.definition_id);
    if (definitionScene) group.add(definitionScene.clone(true));
    nodeGroups.set(node.node_id, group);
  }
  for (const node of manifest.nodes) {
    const group = nodeGroups.get(node.node_id);
    const parent = node.parent_node_id ? nodeGroups.get(node.parent_node_id) : null;
    (parent || nextRoot).add(group);
  }

  scene.remove(modelRoot);
  disposeRoot(modelRoot);
  modelRoot = nextRoot;
  scene.add(modelRoot);
  latestRevision = preview.revision;
  latestBuild = preview.build;
  expectedRevision = Math.max(expectedRevision, preview.revision);
  revisionLabel.textContent = String(expectedRevision);
  sceneQuality.textContent = preview.quality === "final" ? "Final" : "Draft";
  sceneTime.textContent = preview.elapsed_ms ? `${preview.elapsed_ms} ms` : "Ready";
  assetCount.textContent = `${manifest.geometry_assets.length} assets`;
  emptyState.hidden = true;
  if (!hasFramed) {
    fitView();
    hasFramed = true;
  }
}

function connectEvents() {
  if (eventSource) eventSource.close();
  const modelId = modelInput.value.trim();
  if (!modelId) return;
  eventSource = new EventSource(`/events/${encodeURIComponent(modelId)}`);
  eventSource.addEventListener("open", () => setStatus("Connected", "ready"));
  eventSource.addEventListener("revision_pending", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.revision < latestRevision) return;
    setStatus(`Meshing r${payload.revision}`);
    sceneTime.textContent = "Building";
  });
  eventSource.addEventListener("revision_ready", async (event) => {
    const payload = JSON.parse(event.data);
    try {
      await loadScene(payload);
      setStatus(`Ready r${payload.revision}`, "ready");
      showError("");
    } catch (error) {
      setStatus("Load failed", "failed");
      showError(error.message || String(error));
    }
  });
  eventSource.addEventListener("revision_failed", (event) => {
    const payload = JSON.parse(event.data);
    if (payload.revision < latestRevision) return;
    setStatus(`Failed r${payload.revision}`, "failed");
    showError(payload.error || "Preview build failed");
  });
  eventSource.onerror = () => setStatus("Reconnecting");
}

async function selectModel() {
  expectedRevision = 0;
  latestRevision = -1;
  latestBuild = -1;
  revisionLabel.textContent = "0";
  showError("");
  connectEvents();
  const modelId = modelInput.value.trim();
  if (!modelId) return;
  try {
    const response = await fetch(`/models/${encodeURIComponent(modelId)}`, { cache: "no-store" });
    if (response.status === 404) return;
    if (!response.ok) throw new Error(`Model state returned ${response.status}`);
    const state = await response.json();
    expectedRevision = state.revision;
    revisionLabel.textContent = String(expectedRevision);
    if (state.preview) {
      await loadScene(state.preview);
      setStatus(`Ready r${state.revision}`, "ready");
    }
  } catch (error) {
    showError(error.message || String(error));
  }
}

document.querySelector("#apply-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const modelId = modelInput.value.trim();
  const documentText = editor.value.trim();
  if (!modelId || !documentText) return;
  applyButton.disabled = true;
  setStatus("Applying");
  showError("");
  try {
    const response = await fetch(`/models/${encodeURIComponent(modelId)}/apply`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        document: documentText,
        expected_revision: expectedRevision,
        quality: selectedQuality,
      }),
    });
    const payload = await response.json();
    if (!response.ok || payload.status !== "ok") {
      if (Number.isInteger(payload.revision)) {
        expectedRevision = payload.revision;
        revisionLabel.textContent = String(expectedRevision);
      }
      throw new Error(payload.error || `Apply returned ${response.status}`);
    }
    expectedRevision = payload.revision;
    revisionLabel.textContent = String(expectedRevision);
    editor.value = "";
    updateLineCount();
    setStatus(`Committed r${payload.revision}`);
  } catch (error) {
    setStatus("Apply failed", "failed");
    showError(error.message || String(error));
  } finally {
    applyButton.disabled = false;
  }
});

document.querySelectorAll(".quality-button").forEach((button) => {
  button.addEventListener("click", () => {
    selectedQuality = button.dataset.quality;
    document.querySelectorAll(".quality-button").forEach((item) => {
      item.classList.toggle("active", item === button);
    });
  });
});

document.querySelector("#fit-view").addEventListener("click", fitView);
edgeButton.addEventListener("click", () => {
  edgesVisible = !edgesVisible;
  edgeButton.classList.toggle("active", edgesVisible);
  modelRoot.traverse((object) => {
    if (object.name === "cadflow-edges") object.visible = edgesVisible;
  });
});
editor.addEventListener("input", updateLineCount);
editor.addEventListener("keydown", (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
    event.preventDefault();
    document.querySelector("#apply-form").requestSubmit();
  }
});
modelInput.addEventListener("change", selectModel);
modelInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    event.preventDefault();
    modelInput.blur();
  }
});

updateLineCount();
selectModel();
