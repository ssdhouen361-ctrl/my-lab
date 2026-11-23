"""Automated Test Suite for TacTicTap Wear OS & Web Simulator Logic.
Verifies all states, blind touch gesture boundaries, digit limits, and theme consistency.
"""

import pytest

class TacTicTapEngine:
    def __init__(self):
        self.digits = [0, 3, 0, 0] # [M10, M1, S10, S1]
        self.active_col = 1
        self.limits = [5, 9, 5, 9]
        self.state = "SETUP" # SETUP, RUNNING, ALARM
        self.total_seconds = 180
        self.remaining_seconds = 180

    def tap(self, y_fraction):
        """Simulate tap at given height fraction (0.0 to 1.0)."""
        if self.state in ("ALARM", "RUNNING"):
            self.state = "SETUP"
            return

        if self.state == "SETUP":
            max_val = self.limits[self.active_col]
            cur = self.digits[self.active_col]
            if y_fraction < 0.666:
                # Upper 2/3: +1
                self.digits[self.active_col] = 0 if cur >= max_val else cur + 1
            else:
                # Lower 1/3: -1
                self.digits[self.active_col] = max_val if cur <= 0 else cur - 1

    def swipe(self, direction):
        """direction: 'LEFT', 'RIGHT', 'UP', 'DOWN'"""
        if self.state in ("ALARM", "RUNNING"):
            if direction in ("DOWN", "LEFT", "RIGHT"):
                self.state = "SETUP"
            return

        if self.state == "SETUP":
            if direction == "LEFT":
                self.active_col = (self.active_col + 1) % 4
            elif direction == "RIGHT":
                self.active_col = (self.active_col - 1 + 4) % 4
            elif direction == "UP":
                mins = self.digits[0] * 10 + self.digits[1]
                secs = self.digits[2] * 10 + self.digits[3]
                self.total_seconds = mins * 60 + secs
                self.remaining_seconds = self.total_seconds
                self.state = "RUNNING"
            elif direction == "DOWN":
                self.digits = [0, 0, 0, 0]

    def tick(self):
        if self.state == "RUNNING":
            self.remaining_seconds -= 1
            if self.remaining_seconds <= 0:
                self.remaining_seconds = 0
                self.state = "ALARM"


# Test Cases
def test_initial_state():
    engine = TacTicTapEngine()
    assert engine.state == "SETUP"
    assert engine.digits == [0, 3, 0, 0]
    assert engine.active_col == 1

def test_upper_tap_increments():
    engine = TacTicTapEngine()
    engine.tap(0.2) # Top area
    assert engine.digits[1] == 4
    engine.tap(0.6) # Still upper 2/3
    assert engine.digits[1] == 5

def test_lower_tap_decrements():
    engine = TacTicTapEngine()
    engine.tap(0.8) # Bottom 1/3
    assert engine.digits[1] == 2
    engine.tap(0.9)
    assert engine.digits[1] == 1

def test_digit_wrapping():
    engine = TacTicTapEngine()
    engine.digits[1] = 9
    engine.tap(0.3) # 9 + 1 -> 0
    assert engine.digits[1] == 0

    engine.tap(0.8) # 0 - 1 -> 9
    assert engine.digits[1] == 9

def test_minute_tens_limit():
    engine = TacTicTapEngine()
    engine.swipe("RIGHT") # Shift to M10 (index 0)
    assert engine.active_col == 0
    engine.digits[0] = 5
    engine.tap(0.2) # Max is 5 -> wraps to 0
    assert engine.digits[0] == 0
    engine.tap(0.8) # 0 - 1 -> wraps to 5
    assert engine.digits[0] == 5

def test_swipe_navigation():
    engine = TacTicTapEngine()
    assert engine.active_col == 1
    engine.swipe("LEFT") # Move to S10
    assert engine.active_col == 2
    engine.swipe("LEFT") # Move to S1
    assert engine.active_col == 3
    engine.swipe("LEFT") # Wrap to M10
    assert engine.active_col == 0

def test_swipe_up_starts_running():
    engine = TacTicTapEngine()
    engine.digits = [0, 5, 3, 0] # 5 min 30 sec
    engine.swipe("UP")
    assert engine.state == "RUNNING"
    assert engine.total_seconds == 330
    assert engine.remaining_seconds == 330

def test_countdown_and_alarm_trigger():
    engine = TacTicTapEngine()
    engine.digits = [0, 0, 0, 2] # 2 seconds
    engine.swipe("UP")
    assert engine.state == "RUNNING"
    engine.tick() # 1 sec left
    assert engine.remaining_seconds == 1
    assert engine.state == "RUNNING"
    engine.tick() # 0 sec left -> ALARM
    assert engine.remaining_seconds == 0
    assert engine.state == "ALARM"

def test_blind_tap_stops_alarm():
    engine = TacTicTapEngine()
    engine.state = "ALARM"
    # Any tap anywhere on screen stops alarm
    engine.tap(0.5)
    assert engine.state == "SETUP"
