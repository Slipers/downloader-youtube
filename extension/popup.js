function $(id) { return document.getElementById(id); }

function showState(name) {
  ["idle", "linking", "error", "linked"].forEach((s) => {
    $(`state-${s}`).hidden = s !== name;
  });
}

function resetSteps() {
  document.querySelectorAll("#link-steps .step").forEach((el) => el.classList.remove("active", "done"));
}

function setStep(step, status) {
  const el = document.querySelector(`#link-steps .step[data-step="${step}"]`);
  if (!el) return;
  el.classList.remove("active", "done");
  el.classList.add(status);
}

function delay(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function runLinkFlow() {
  showState("linking");
  resetSteps();

  setStep("detect", "active");
  const pingResponse = await chrome.runtime.sendMessage({ type: "PING" });
  if (!pingResponse?.ok) {
    showState("error");
    return;
  }
  setStep("detect", "done");

  setStep("connect", "active");
  await delay(450);
  const linkResponse = await chrome.runtime.sendMessage({ type: "LINK" });
  if (!linkResponse?.ok) {
    showState("error");
    return;
  }
  setStep("connect", "done");

  setStep("finish", "active");
  await delay(350);
  setStep("finish", "done");
  await delay(250);

  showState("linked");
}

async function init() {
  const { paired } = await chrome.runtime.sendMessage({ type: "GET_PAIR_STATE" });
  showState(paired ? "linked" : "idle");
}

$("btn-link").addEventListener("click", runLinkFlow);
$("btn-retry").addEventListener("click", runLinkFlow);
$("btn-unlink").addEventListener("click", async () => {
  await chrome.storage.local.set({ paired: false, token: "" });
  showState("idle");
});

init();
