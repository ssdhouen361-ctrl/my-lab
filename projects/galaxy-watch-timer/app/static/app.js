/**
 * TacTicTap - Core State Machine & Touch Simulator
 */

// Audio feedback using Web Audio API for blind tactile confirmation
class HapticFeedback {
  constructor() {
    this.ctx = null;
  }
  init() {
    if (!this.ctx) {
      this.ctx = new (window.AudioContext || window.webkitAudioContext)();
    }
  }
  tapUp() {
    this.beep(880, 0.03, 'sine'); // High crisp tick (+1)
    if (navigator.vibrate) navigator.vibrate(15);
  }
  tapDown() {
    this.beep(440, 0.04, 'sine'); // Deeper tick (-1)
    if (navigator.vibrate) navigator.vibrate(20);
  }
  swipeCol() {
    this.beep(660, 0.05, 'triangle'); // Column shift
    if (navigator.vibrate) navigator.vibrate(25);
  }
  startTimer() {
    this.beep(1200, 0.1, 'square'); // Sharp start chime
    if (navigator.vibrate) navigator.vibrate([30, 40, 30]);
  }
  stopAlarm() {
    this.beep(520, 0.08, 'sine');
    if (navigator.vibrate) navigator.vibrate(40);
  }
  alarmTick() {
    this.beep(980, 0.08, 'sawtooth');
    if (navigator.vibrate) navigator.vibrate([100, 50, 100]);
  }
  beep(freq, duration, type = 'sine') {
    if (!this.ctx) return;
    try {
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = type;
      osc.frequency.setValueAtTime(freq, this.ctx.currentTime);
      gain.gain.setValueAtTime(0.12, this.ctx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, this.ctx.currentTime + duration);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start();
      osc.stop(this.ctx.currentTime + duration);
    } catch (e) {
      // AudioContext suspended or blocked
    }
  }
}

const haptics = new HapticFeedback();

// Application State
const STATE_SETUP = 'SETUP';
const STATE_RUNNING = 'RUNNING';
const STATE_ALARM = 'ALARM';

let currentState = STATE_SETUP;

// Digits [M10, M1, S10, S1]
let digits = [0, 3, 0, 0];
let activeCol = 1; // Default to minute-1

// Limits per column
const COL_LIMITS = [5, 9, 5, 9]; // Max 59:59

// Timer runtime
let totalSeconds = 0;
let remainingSeconds = 0;
let timerInterval = null;
let alarmInterval = null;

// DOM Elements
const watchScreen = document.getElementById('watchScreen');
const viewSetup = document.getElementById('viewSetup');
const viewRunning = document.getElementById('viewRunning');
const viewAlarm = document.getElementById('viewAlarm');
const digitElements = [
  document.getElementById('digit-m10'),
  document.getElementById('digit-m1'),
  document.getElementById('digit-s10'),
  document.getElementById('digit-s1'),
];
const runDigits = document.getElementById('run-digits');
const alarmDigits = document.getElementById('alarm-digits');
const ringBar = document.getElementById('ringBar');
const rippleOverlay = document.getElementById('rippleOverlay');
const themeSelect = document.getElementById('themeSelect');
const deviceSelect = document.getElementById('deviceSelect');

const CIRCUMFERENCE = 2 * Math.PI * 230; // 1445.13

// Render Setup View
function renderSetupDigits() {
  digitElements.forEach((el, idx) => {
    el.textContent = digits[idx];
    if (idx === activeCol) {
      el.classList.add('selected');
    } else {
      el.classList.remove('selected');
    }
  });
}

// Format Seconds to MM:SS
function formatTime(sec) {
  const m = Math.floor(sec / 60);
  const s = sec % 60;
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

// Switch Application State
function switchState(newState) {
  currentState = newState;
  viewSetup.classList.remove('active');
  viewRunning.classList.remove('active');
  viewAlarm.classList.remove('active');

  if (newState === STATE_SETUP) {
    clearInterval(timerInterval);
    clearInterval(alarmInterval);
    viewSetup.classList.add('active');
    renderSetupDigits();
  } else if (newState === STATE_RUNNING) {
    viewRunning.classList.add('active');
    haptics.startTimer();
    startRunningCountdown();
  } else if (newState === STATE_ALARM) {
    clearInterval(timerInterval);
    viewAlarm.classList.add('active');
    startAlarmSound();
  }
}

// Running Countdown Loop
function startRunningCountdown() {
  updateRunningDisplay();
  timerInterval = setInterval(() => {
    remainingSeconds--;
    if (remainingSeconds <= 0) {
      remainingSeconds = 0;
      updateRunningDisplay();
      switchState(STATE_ALARM);
    } else {
      updateRunningDisplay();
    }
  }, 1000);
}

function updateRunningDisplay() {
  runDigits.textContent = formatTime(remainingSeconds);
  if (totalSeconds > 0) {
    const fraction = remainingSeconds / totalSeconds;
    const offset = CIRCUMFERENCE * (1 - fraction);
    ringBar.style.strokeDashoffset = offset;
  }
}

// Alarm Flashing & Haptics
function startAlarmSound() {
  alarmDigits.textContent = '00:00';
  haptics.alarmTick();
  alarmInterval = setInterval(() => {
    haptics.alarmTick();
  }, 1000);
}

// Action Handlers
function adjustActiveDigit(delta) {
  haptics.init();
  const max = COL_LIMITS[activeCol];
  let val = digits[activeCol] + delta;
  if (val > max) val = 0;
  if (val < 0) val = max;
  digits[activeCol] = val;

  if (delta > 0) haptics.tapUp();
  else haptics.tapDown();

  renderSetupDigits();
}

function shiftColumn(direction) {
  haptics.init();
  activeCol = (activeCol + direction + 4) % 4;
  haptics.swipeCol();
  renderSetupDigits();
}

function triggerStart() {
  const mins = digits[0] * 10 + digits[1];
  const secs = digits[2] * 10 + digits[3];
  totalSeconds = mins * 60 + secs;
  if (totalSeconds <= 0) {
    // If 0, default to 3 minutes
    digits = [0, 3, 0, 0];
    totalSeconds = 180;
  }
  remainingSeconds = totalSeconds;
  switchState(STATE_RUNNING);
}

function triggerReset() {
  haptics.init();
  haptics.stopAlarm();
  switchState(STATE_SETUP);
}

// Create Visual Touch Ripple
function createRipple(x, y) {
  const rect = watchScreen.getBoundingClientRect();
  const ripple = document.createElement('div');
  ripple.classList.add('ripple');
  const size = 120;
  ripple.style.width = `${size}px`;
  ripple.style.height = `${size}px`;
  ripple.style.left = `${x - rect.left - size / 2}px`;
  ripple.style.top = `${y - rect.top - size / 2}px`;
  rippleOverlay.appendChild(ripple);
  setTimeout(() => ripple.remove(), 400);
}

// Touch & Pointer Gesture Recognition (Blind Friendly)
let startX = 0;
let startY = 0;
let startTime = 0;
const SWIPE_THRESHOLD = 40; // px threshold for gesture
const TAP_TIMEOUT = 300; // ms

watchScreen.addEventListener('pointerdown', (e) => {
  startX = e.clientX;
  startY = e.clientY;
  startTime = Date.now();
  haptics.init();
});

watchScreen.addEventListener('pointerup', (e) => {
  const endX = e.clientX;
  const endY = e.clientY;
  const diffX = endX - startX;
  const diffY = endY - startY;
  const duration = Date.now() - startTime;
  const distance = Math.hypot(diffX, diffY);

  createRipple(endX, endY);

  // Alarm State: Any Tap stops the alarm
  if (currentState === STATE_ALARM) {
    triggerReset();
    return;
  }

  // Running State: Down swipe or tap can cancel/return
  if (currentState === STATE_RUNNING) {
    if (diffY > SWIPE_THRESHOLD || distance < 20) {
      triggerReset();
    }
    return;
  }

  // Setup State Gestures
  if (currentState === STATE_SETUP) {
    // Check if Swipe
    if (distance > SWIPE_THRESHOLD) {
      if (Math.abs(diffX) > Math.abs(diffY)) {
        // Horizontal Swipe
        if (diffX < 0) {
          // Swipe Left -> next column
          shiftColumn(1);
        } else {
          // Swipe Right -> prev column
          shiftColumn(-1);
        }
      } else {
        // Vertical Swipe
        if (diffY < 0) {
          // Swipe Up -> Start Timer Immediately
          triggerStart();
        } else {
          // Swipe Down -> Reset to 00:00
          digits = [0, 0, 0, 0];
          haptics.stopAlarm();
          renderSetupDigits();
        }
      }
    } else {
      // Tap Gesture
      const rect = watchScreen.getBoundingClientRect();
      const relY = endY - rect.top;
      const height = rect.height;

      // Upper 2/3: +1, Lower 1/3: -1
      if (relY < height * 0.666) {
        adjustActiveDigit(1);
      } else {
        adjustActiveDigit(-1);
      }
    }
  }
});

// UI Dropdown Controls
themeSelect.addEventListener('change', (e) => {
  document.body.className = e.target.value;
});

deviceSelect.addEventListener('change', (e) => {
  const size = e.target.value;
  document.documentElement.style.setProperty('--watch-dim', `${size}px`);
});

// Keyboard Accessibility Shortcuts
window.addEventListener('keydown', (e) => {
  if (e.key === 'ArrowUp') adjustActiveDigit(1);
  if (e.key === 'ArrowDown') adjustActiveDigit(-1);
  if (e.key === 'ArrowLeft') shiftColumn(-1);
  if (e.key === 'ArrowRight') shiftColumn(1);
  if (e.key === 'Enter') triggerStart();
  if (e.key === 'Escape') triggerReset();
});

// Initial Render
renderSetupDigits();
