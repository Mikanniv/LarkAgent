import { mountCharacter } from "./character.js";
const native = window.yunqueDesktop;
const mount = document.getElementById("petMount");
let character, form, gaze = true, hit = false, dragging = false;
function render(state) {
  gaze = state.gazeEnabled;
  if (state.form !== form) {
    form = state.form;
    character?.destroy();
    character = mountCharacter(mount, form);
  }
  character?.setEnabled(gaze);
}
function updateHit(event) {
  if (dragging) return;
  const nextHit = Boolean(character?.hitTest(event.clientX, event.clientY));
  if (nextHit !== hit) { hit = nextHit; native?.setHitTest(hit); }
}
if (native) {
  native.onState(render);
  native.onCursor(point => { if (gaze) character?.lookAt(point.x, point.y); });
  native.getState().then(render);
  native.setHitTest(false);
  document.addEventListener("pointermove", updateHit);
  document.addEventListener("pointerdown", event => {
    if (event.button !== 0 || !hit) return;
    dragging = true; document.body.setPointerCapture(event.pointerId); native.beginDrag();
  });
  const endDrag = () => { if (dragging) { dragging = false; native.endDrag(); } };
  document.addEventListener("pointerup", endDrag);
  document.addEventListener("pointercancel", endDrag);
  window.addEventListener("blur", endDrag);
  document.addEventListener("contextmenu", event => { event.preventDefault(); native.showMenu(); });
} else render({ form: "bird", gazeEnabled: true });
