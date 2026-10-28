const artwork = {
  human: { file: "human-seated.png", label: "蓝发黄眼的云雀坐姿立绘" },
  chibi: { file: "chibi.png", label: "云雀 Q版小人立绘" },
  bird: { file: "bird.png", label: "云雀蓝色小鸟立绘" },
};

export function mountCharacter(container, form = "human") {
  const selected = artwork[form] ? form : "human";
  const source = artwork[selected];
  container.dataset.form = selected;
  container.dataset.renderer = "static-art";
  const art = document.createElement("div");
  art.className = "character-art";
  const image = document.createElement("img");
  image.alt = source.label;
  image.draggable = false;
  image.decoding = "async";
  art.append(image);
  container.replaceChildren(art);

  let pixels = null, pixelWidth = 0, pixelHeight = 0, disposed = false;
  let player = null, canvas = null, animation = 0, enabled = true, lastTime = 0;
  let targetX = 0, targetY = 0, currentX = 0, currentY = 0, sampleTime = 0;
  const clamp = value => Number.isFinite(value) ? Math.max(-1, Math.min(1, value)) : 0;

  function animate(now) {
    animation = 0;
    if (disposed || !player) return;
    const dt = Math.min(.05, Math.max(0, (now - lastTime) / 1000 || 0));
    lastTime = now;
    const ease = 1 - Math.exp(-dt * 8);
    currentX += ((enabled ? targetX : 0) - currentX) * ease;
    currentY += ((enabled ? targetY : 0) - currentY) * ease;
    // Drive the authored X/Y keyforms directly; a diagonal look adds no roll.
    player.setParameter("ParamAngleX", currentX * 25);
    player.setParameter("ParamAngleY", -currentY * 24);
    player.setParameter("ParamAngleZ", 0);
    player.setParameter("ParamEyeBallX", currentX * .65);
    player.setParameter("ParamEyeBallY", -currentY * .55);
    player.update(dt);
    player.draw();
    if (now - sampleTime > 120) {
      container.dataset.headX = (currentX * 25).toFixed(1);
      container.dataset.headY = (-currentY * 24).toFixed(1);
      sampleTime = now;
    }
    if (!document.hidden) animation = requestAnimationFrame(animate);
  }

  function resume() {
    if (player && !disposed && !document.hidden && !animation) {
      lastTime = performance.now();
      animation = requestAnimationFrame(animate);
    }
  }

  async function loadRig() {
    try {
      const { P2LPlayer } = await import("./live2d/runtime/p2l.js");
      if (disposed) return;
      canvas = document.createElement("canvas");
      canvas.setAttribute("role", "img");
      canvas.setAttribute("aria-label", "云雀分层动态形象");
      Object.assign(canvas.style, { position: "absolute", inset: "0", width: "100%", height: "100%", pointerEvents: "none" });
      art.style.position = "relative";
      art.append(canvas);
      const rig = await P2LPlayer.create(canvas,
        new URL("./live2d/runtime/p2l_runtime.wasm", import.meta.url).href,
        new URL("./live2d/human/yunque.p2lrt", import.meta.url).href);
      rig.stop();
      if (disposed) { rig.dispose(); return; }
      player = rig;
      // Only automatic blinking. Head direction is controlled above, without idle swaying.
      player.behaviors(1);
      player.update(0); player.draw();
      image.style.visibility = "hidden";
      image.setAttribute("aria-hidden", "true");
      container.dataset.renderer = "layered-rig";
      container.dataset.tracking = String(enabled);
      resume();
      container.dispatchEvent(new CustomEvent("character-ready"));
    } catch (error) {
      player?.dispose(); player = null; canvas?.remove(); canvas = null;
      if (!disposed) {
        container.dataset.renderer = "static-art";
        container.dispatchEvent(new CustomEvent("character-error", { detail: error.message }));
      }
    }
  }
  function prepareHitArea() {
    if (disposed || !image.naturalWidth || !image.naturalHeight) return;
    // Only opaque artwork intercepts desktop clicks; transparent margins pass through.
    const scale = Math.min(1, 512 / Math.max(image.naturalWidth, image.naturalHeight));
    const mask = document.createElement("canvas");
    mask.width = pixelWidth = Math.max(1, Math.round(image.naturalWidth * scale));
    mask.height = pixelHeight = Math.max(1, Math.round(image.naturalHeight * scale));
    const context = mask.getContext("2d", { willReadFrequently: true });
    if (!context) return;
    try {
      context.drawImage(image, 0, 0, pixelWidth, pixelHeight);
      pixels = context.getImageData(0, 0, pixelWidth, pixelHeight).data;
    } catch {
      pixels = null;
    }
  }
  image.addEventListener("load", prepareHitArea, { once: true });
  image.src = new URL(`./branding/characters/${source.file}`, import.meta.url).href;
  if (selected === "human") {
    document.addEventListener("visibilitychange", resume);
    loadRig();
  }

  return {
    get supportsGaze() { return Boolean(player); },
    lookAt(x, y) { targetX = clamp(x); targetY = clamp(y); },
    setEnabled(value) {
      enabled = Boolean(value);
      container.dataset.tracking = String(enabled);
      if (!enabled) targetX = targetY = currentX = currentY = 0;
    },
    hitTest(clientX, clientY) {
      if (!pixels || disposed) return false;
      const rect = image.getBoundingClientRect();
      if (!rect.width || !rect.height || clientX < rect.left || clientY < rect.top || clientX >= rect.right || clientY >= rect.bottom) return false;
      const x = Math.min(pixelWidth - 1, Math.floor((clientX - rect.left) / rect.width * pixelWidth));
      const y = Math.min(pixelHeight - 1, Math.floor((clientY - rect.top) / rect.height * pixelHeight));
      return pixels[(y * pixelWidth + x) * 4 + 3] > 24;
    },
    destroy() {
      disposed = true;
      pixels = null;
      cancelAnimationFrame(animation);
      document.removeEventListener("visibilitychange", resume);
      player?.dispose(); player = null;
      image.removeEventListener("load", prepareHitArea);
      art.remove();
    },
  };
}
