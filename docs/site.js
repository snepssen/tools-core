"use strict";

const copyButtons = document.querySelectorAll("[data-copy]");
copyButtons.forEach((button) => {
  button.addEventListener("click", async () => {
    const original = button.textContent;
    try {
      await navigator.clipboard.writeText(button.dataset.copy);
      button.textContent = "Copied";
      button.dataset.state = "done";
    } catch {
      button.textContent = "Select command";
    }
    window.setTimeout(() => {
      button.textContent = original;
      delete button.dataset.state;
    }, 1600);
  });
});

const filterButtons = document.querySelectorAll("[data-filter]");
const toolCards = document.querySelectorAll("[data-kind]");
filterButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const filter = button.dataset.filter;
    filterButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    toolCards.forEach((card) => {
      const kinds = card.dataset.kind.split(" ");
      card.hidden = filter !== "all" && !kinds.includes(filter);
    });
  });
});

const signalCanvas = document.querySelector("#signalCanvas");
const signalToggle = document.querySelector("#signalToggle");
const signalStatus = document.querySelector("#signalStatus");
const beatButtons = document.querySelectorAll("[data-beat]");
let selectedBeat = 4;
let audioContext = null;
let signalNodes = [];
let stopTimer = 0;
let drawingFrame = 0;
let drawStart = performance.now();

function signalLabel() {
  const shown = selectedBeat < 1 ? selectedBeat.toFixed(2) : selectedBeat.toFixed(1);
  return `carrier 100 Hz · differential ${shown} Hz`;
}

function sizeCanvas() {
  const scale = window.devicePixelRatio || 1;
  const width = Math.max(280, signalCanvas.clientWidth);
  const height = Math.max(100, signalCanvas.clientHeight);
  signalCanvas.width = Math.round(width * scale);
  signalCanvas.height = Math.round(height * scale);
  const context = signalCanvas.getContext("2d");
  context.setTransform(scale, 0, 0, scale, 0, 0);
}

function drawSignal(now) {
  const context = signalCanvas.getContext("2d");
  const width = signalCanvas.clientWidth;
  const height = signalCanvas.clientHeight;
  context.clearRect(0, 0, width, height);
  context.strokeStyle = "#3a3a31";
  context.beginPath();
  context.moveTo(0, height / 2);
  context.lineTo(width, height / 2);
  context.stroke();

  const elapsed = (now - drawStart) / 1000;
  const moving = signalToggle.dataset.playing === "true";
  const phase = moving ? elapsed * selectedBeat * 1.35 : 0;
  [["#71e5d2", -1], ["#b69aff", 1]].forEach(([color, direction], index) => {
    context.strokeStyle = color;
    context.lineWidth = 2;
    context.beginPath();
    for (let x = 0; x <= width; x += 2) {
      const y = height / 2 + Math.sin(x * .055 + phase * direction + index * .7) * height * .25;
      if (x === 0) context.moveTo(x, y); else context.lineTo(x, y);
    }
    context.stroke();
  });
  drawingFrame = window.requestAnimationFrame(drawSignal);
}

function stopSignal(reason = "stopped") {
  window.clearTimeout(stopTimer);
  signalNodes.forEach((node) => {
    try { node.stop(); } catch { /* already stopped */ }
  });
  signalNodes = [];
  if (audioContext) audioContext.close();
  audioContext = null;
  signalToggle.dataset.playing = "false";
  signalToggle.textContent = "Start quiet signal";
  signalStatus.textContent = `${reason} · ${signalLabel()}`;
}

async function startSignal() {
  const Context = window.AudioContext || window.webkitAudioContext;
  if (!Context) {
    signalStatus.textContent = "Web Audio is unavailable in this browser";
    return;
  }
  audioContext = new Context();
  const master = audioContext.createGain();
  master.gain.setValueAtTime(0.0001, audioContext.currentTime);
  master.gain.exponentialRampToValueAtTime(0.028, audioContext.currentTime + .35);
  master.connect(audioContext.destination);
  [-1, 1].forEach((pan, index) => {
    const oscillator = audioContext.createOscillator();
    const panner = audioContext.createStereoPanner();
    oscillator.type = "sine";
    oscillator.frequency.value = 100 + (index ? selectedBeat / 2 : -selectedBeat / 2);
    panner.pan.value = pan;
    oscillator.connect(panner).connect(master);
    oscillator.start();
    signalNodes.push(oscillator);
  });
  signalToggle.dataset.playing = "true";
  signalToggle.textContent = "Stop signal";
  signalStatus.textContent = `playing quietly · ${signalLabel()}`;
  stopTimer = window.setTimeout(() => stopSignal("30-second limit reached"), 30000);
}

beatButtons.forEach((button) => {
  button.addEventListener("click", () => {
    const wasPlaying = signalToggle.dataset.playing === "true";
    if (wasPlaying) stopSignal();
    selectedBeat = Number(button.dataset.beat);
    beatButtons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
    signalStatus.textContent = `ready · ${signalLabel()}`;
    drawStart = performance.now();
    if (wasPlaying) startSignal();
  });
});

signalToggle.addEventListener("click", () => {
  if (signalToggle.dataset.playing === "true") stopSignal(); else startSignal();
});
document.addEventListener("visibilitychange", () => {
  if (document.hidden && signalToggle.dataset.playing === "true") stopSignal("page hidden");
});
window.addEventListener("pagehide", () => stopSignal("page closed"));
window.addEventListener("resize", sizeCanvas);
sizeCanvas();
drawingFrame = window.requestAnimationFrame(drawSignal);

const lyricToggle = document.querySelector("#lyricToggle");
const lyricStatus = document.querySelector("#lyricStatus");
const lyricWords = [...document.querySelectorAll("#lyricLine span")];
const lyricWindows = [
  [0, 420], [500, 650], [700, 1180], [1220, 1900],
  [2340, 2700], [2740, 3100], [3160, 3320], [3380, 3850], [3920, 4130], [4200, 5060],
];
let lyricFrame = 0;
let lyricStart = 0;

function stopLyrics() {
  window.cancelAnimationFrame(lyricFrame);
  lyricWords.forEach((word) => word.classList.remove("active"));
  lyricToggle.dataset.playing = "false";
  lyricToggle.textContent = "Play word timing";
}

function drawLyrics(now) {
  const elapsed = now - lyricStart;
  lyricWords.forEach((word, index) => {
    const [start, end] = lyricWindows[index];
    word.classList.toggle("active", elapsed >= start && elapsed < end);
  });
  lyricStatus.textContent = `00:${(elapsed / 1000).toFixed(3).padStart(6, "0")} / 00:05.200`;
  if (elapsed >= 5200) {
    stopLyrics();
    lyricStatus.textContent = "finished · the pause remains part of the timing";
    return;
  }
  lyricFrame = window.requestAnimationFrame(drawLyrics);
}

lyricToggle.addEventListener("click", () => {
  if (lyricToggle.dataset.playing === "true") {
    stopLyrics();
    lyricStatus.textContent = "stopped · 00:05.200 total";
    return;
  }
  stopLyrics();
  lyricToggle.dataset.playing = "true";
  lyricToggle.textContent = "Stop timing";
  lyricStart = performance.now();
  lyricFrame = window.requestAnimationFrame(drawLyrics);
});
