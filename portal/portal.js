"use strict";
const $ = (id) => document.getElementById(id);
let connected = false;
let busy = false;
let output = "";

function notice(text, error = false) {
  $("notice").textContent = text;
  $("notice").classList.toggle("error", error);
}
function controls() {
  $("run").disabled = busy || !connected;
  $("connect").disabled = busy || !$("device").value;
  $("refresh").disabled = busy || connected;
  $("device").disabled = busy || connected;
  $("disconnect").disabled = busy;
  $("example").disabled = busy;
  $("connect").hidden = connected;
  $("disconnect").hidden = !connected;
}
async function api(path, value) {
  const options = value === undefined ? {} : {
    method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(value)
  };
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "The request failed.");
  return data;
}
function connection(value, serial = "") {
  connected = value;
  $("connectionBadge").classList.toggle("online", value);
  $("connectionLabel").textContent = value ? `UNO Q · ${serial}` : "Disconnected";
  controls();
}
async function refresh() {
  busy = true;
  controls();
  try {
    const data = await api("/api/devices");
    $("device").replaceChildren();
    for (const device of data.devices) {
      const option = document.createElement("option");
      option.value = device.state === "device" ? device.serial : "";
      option.disabled = device.state !== "device";
      option.textContent = `${device.serial} · ${device.state === "device" ? "USB available" : device.state}`;
      $("device").append(option);
    }
    if (data.preferred_serial && data.devices.some(d => d.serial === data.preferred_serial && d.state === "device")) {
      $("device").value = data.preferred_serial;
    } else {
      const ready = data.devices.find(d => d.state === "device");
      if (ready) $("device").value = ready.serial;
    }
    if (!data.devices.length) {
      $("device").append(new Option("No USB boards found", ""));
    }
    notice($("device").value ? "Board found. Run Laya Q in App Lab, then connect here." : "Plug in your UNO Q with a USB data cable, open App Lab, then refresh.");
  } catch (error) {
    $("device").replaceChildren(new Option("Device discovery unavailable", ""));
    notice(error.message, true);
  } finally {
    busy = false;
    controls();
  }
}
async function loadExample() {
  try {
    const example = await api("/api/example");
    $("state").value = typeof example.state === "string" ? example.state : JSON.stringify(example.state, null, 2);
    $("questions").value = JSON.stringify(example.questions, null, 2);
  } catch (error) { notice(error.message, true); }
}
$("refresh").addEventListener("click", refresh);
$("example").addEventListener("click", loadExample);
$("device").addEventListener("change", controls);
$("connect").addEventListener("click", async () => {
  busy = true; controls(); notice("Connecting to Laya Q on your board…");
  try {
    const data = await api("/api/connect", {serial: $("device").value});
    connection(true, data.serial);
    notice("Connected. Your requests will run on the UNO Q over USB.");
  } catch (error) { notice(error.message, true); }
  finally { busy = false; controls(); }
});
$("disconnect").addEventListener("click", async () => {
  busy = true; controls();
  try { await api("/api/disconnect", {}); connection(false); notice("Disconnected from the board."); }
  catch (error) { notice(error.message, true); }
  finally { busy = false; controls(); }
});
$("run").addEventListener("click", async () => {
  let request;
  try {
    let state = $("state").value;
    if (!state.trim()) throw new Error("Add a state before sending your request.");
    if (/^[\[{]/.test(state.trim())) {
      try { state = JSON.parse(state); } catch { throw new Error("The state looks like JSON but could not be parsed. Check its syntax."); }
    }
    const questions = JSON.parse($("questions").value);
    if (!questions || Array.isArray(questions) || typeof questions !== "object" || !Object.keys(questions).length) throw new Error("Questions must be a nonempty JSON object.");
    request = {state, questions};
  } catch (error) { notice(error.message, true); return; }
  busy = true; controls(); document.body.classList.add("busy");
  $("run").textContent = "Running on board…";
  notice("Sending over USB. The UNO Q matrix shows inference activity.");
  try {
    const data = await api("/api/predict", request);
    output = JSON.stringify(data.result, null, 2);
    $("emptyResult").hidden = true;
    $("resultArea").hidden = false;
    $("output").textContent = output;
    $("elapsed").textContent = `${(data.elapsed_ms / 1000).toFixed(2)} s`;
    $("answers").replaceChildren();
    for (const [name, answer] of Object.entries(data.result.answers || {})) {
      const card = document.createElement("div"); card.className = "answer";
      const label = document.createElement("div"); label.className = "answer-name"; label.textContent = name;
      const value = document.createElement("div"); value.className = "answer-value";
      const selected = answer && typeof answer === "object" ? (answer.choice ?? answer.score ?? answer.noul) : answer;
      value.textContent = selected === undefined ? "See JSON result" : typeof selected === "object" ? JSON.stringify(selected) : String(selected);
      card.append(label, value); $("answers").append(card);
    }
    $("copy").disabled = false;
    notice("Result received. Your board is ready for the next request.");
  } catch (error) { notice(error.message, true); }
  finally { busy = false; controls(); document.body.classList.remove("busy"); $("run").textContent = "Send to UNO Q →"; }
});
$("copy").addEventListener("click", async () => {
  try { await navigator.clipboard.writeText(output); notice("Result JSON copied."); }
  catch { notice("Clipboard unavailable. Select and copy the JSON result.", true); }
});
document.addEventListener("keydown", event => {
  if ((event.ctrlKey || event.metaKey) && event.key === "Enter" && !$("run").disabled) $("run").click();
});
refresh();
loadExample();
