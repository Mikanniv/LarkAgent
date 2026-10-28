import { mountCharacter } from "./character.js";
const mount = document.getElementById("modelPreview");
let character;
const description = document.getElementById("previewDescription");
mount.addEventListener("character-ready", () => { description.textContent = "移动鼠标，看看云雀转头、抬头和低头。"; });
mount.addEventListener("character-error", () => { description.textContent = "动态形象加载失败，请刷新重试。"; });
function show(form) {
  character?.destroy();
  character = mountCharacter(mount, form);
  description.textContent = form === "human" ? "正在加载云雀…" : "原始立绘 · 动态形象待制作";
  document.querySelectorAll("button[data-form]").forEach(button => {
    const active = button.dataset.form === form;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", String(active));
  });
}
document.addEventListener("pointermove", event => {
  if (!character?.supportsGaze) return;
  const r = mount.getBoundingClientRect();
  character.lookAt((event.clientX - r.left - r.width / 2) / 300, (event.clientY - r.top - r.height * .27) / 300);
}, { passive: true });
document.documentElement.addEventListener("pointerleave", () => character?.lookAt(0, 0));
window.addEventListener("blur", () => character?.lookAt(0, 0));
document.querySelectorAll("button[data-form]").forEach(button => button.onclick = () => show(button.dataset.form));
window.addEventListener("pagehide", () => character?.destroy(), { once: true });
show("human");
